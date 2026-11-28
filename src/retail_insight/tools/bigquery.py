"""Read-only SQL against three public TheLook tables, with bounded query cost."""

import asyncio
import json

import sqlglot
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.expressions.dml import DML
from sqlglot.optimizer.scope import Scope, traverse_scope

from retail_insight.config import Settings
from retail_insight.core.tool import Tool, ToolArgs

DATASET = "bigquery-public-data.thelook_ecommerce"
TABLES = ("order_items", "orders", "products")
ROW_LIMIT = 100


def validate_sql(sql: str) -> str:
    statements = sqlglot.parse(sql, read="bigquery")
    if len(statements) != 1 or not isinstance(
        statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)
    ):
        raise ValueError("Use one read-only SELECT query.")
    tree = statements[0]
    if tree.find(exp.Into) or any(
        isinstance(node, (exp.DDL, DML, exp.Command)) for node in tree.walk()
    ):
        raise ValueError("Writes, scripts and exports are not available.")
    # Reject user-defined/remote functions; standard parsed SQL functions remain available.
    if tree.find(exp.Anonymous) or any(
        isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func) for node in tree.walk()
    ):
        raise ValueError(
            "Use standard SQL functions; custom, remote and AI functions are unavailable."
        )
    for scope in traverse_scope(tree):
        for source in scope.sources.values():
            if isinstance(source, Scope):
                continue  # A CTE/subquery is checked through its own scope.
            if not isinstance(source, exp.Table) or not isinstance(source.this, exp.Identifier):
                raise ValueError("Use ordinary tables or CTEs.")
            if (
                source.name not in TABLES
                or source.catalog not in ("", "bigquery-public-data")
                or source.db not in ("", "thelook_ecommerce")
            ):
                raise ValueError(
                    "Available tables: order_items, orders, products in the public TheLook dataset."
                )
            source.set("catalog", exp.Identifier(this="bigquery-public-data", quoted=True))
            source.set("db", exp.Identifier(this="thelook_ecommerce"))
    return tree.sql(dialect="bigquery")


class QueryArgs(ToolArgs):
    sql: str


class BigQueryTools:
    def __init__(self, settings: Settings, *, client=None):
        self.settings, self._client = settings, client

    @property
    def client(self):
        if self._client is None:
            if not self.settings.google_cloud_project:
                raise ValueError(
                    "Set GOOGLE_CLOUD_PROJECT and run gcloud auth application-default login."
                )
            self._client = bigquery.Client(project=self.settings.google_cloud_project)
        return self._client

    def tools(self) -> list[Tool]:
        return [
            Tool(
                "describe_tables",
                "Read the schema of order_items, orders and products before writing SQL.",
                ToolArgs,
                self.describe_tables,
            ),
            Tool(
                "query_bigquery",
                "Run one read-only BigQuery SELECT. Use short table names or the public TheLook dataset. At most 100 rows are returned; compute aggregates in SQL.",
                QueryArgs,
                self.query,
            ),
        ]

    async def describe_tables(self) -> dict:
        def read():
            return {
                "dataset": DATASET,
                "tables": {
                    name: [
                        {"name": f.name, "type": f.field_type}
                        for f in self.client.get_table(
                            f"{DATASET}.{name}",
                            retry=None,  # type: ignore[arg-type]  # SDK supports None: no retries.
                            timeout=15,
                        ).schema
                    ]
                    for name in TABLES
                },
            }

        return await asyncio.to_thread(read)

    async def query(self, sql: str) -> dict:
        try:
            sql = validate_sql(sql)
        except (ValueError, SqlglotError) as exc:
            return {"error": str(exc)}

        def run():
            rows = self.client.query_and_wait(
                sql,
                job_config=bigquery.QueryJobConfig(
                    use_legacy_sql=False,
                    maximum_bytes_billed=self.settings.max_query_bytes,
                    job_timeout_ms=30_000,
                ),
                max_results=ROW_LIMIT + 1,
                api_timeout=15,
                wait_timeout=30,
                retry=None,  # type: ignore[arg-type]  # SDK supports None: no retries.
                job_retry=None,  # type: ignore[arg-type]  # SDK supports None: no retries.
            )
            values = [dict(row) for row in rows]
            return json.loads(
                json.dumps(
                    {"sql": sql, "rows": values[:ROW_LIMIT], "truncated": len(values) > ROW_LIMIT},
                    default=str,
                )
            )

        try:
            return await asyncio.to_thread(run)
        except GoogleAPICallError as exc:
            return {"error": exc.message[:600]}
        except TimeoutError:
            return {"error": "BigQuery exceeded its 30-second wait limit; narrow the query."}

    def close(self):
        if self._client is not None:
            self._client.close()
