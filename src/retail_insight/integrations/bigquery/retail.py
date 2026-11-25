"""Scoped relational tools, with isolated local execution and bounded warehouse jobs.

The model supplies SQL, never credentials, physical sources or authorization scope.
Source validation is separate from analytical expression choice: arbitrary joins,
CTEs, windows and compositions are permitted over the documented safe relations.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import decimal
import hashlib
import json
import math
import multiprocessing
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError, UnsupportedError
from sqlglot.expressions.dml import DML
from sqlglot.optimizer.scope import traverse_scope

DEFINITIONS = (
    "scoped-retail-v1; sales contains qualifying item purchases, excluding Cancelled/Returned "
    "at both item and order level. transactions contains all current statuses. Revenue uses "
    "sale_price; orders and customers require distinct IDs. Runtime access includes all brands; use explicit SQL filters for a requested brand. "
    "Optional reference filters apply before joins and history. purchased_at is the item's created_at. Use UTC half-open periods. Current "
    "statuses cannot reconstruct historical status changes, delivery or refund events. "
    "Qualifying sales may include Processing/Shipped; sale_price is not a refunded amount "
    "or evidence of cash collection. Currency is not specified. "
    "Customer geography is available only through query_state_summary."
)
PRODUCT_COLUMNS = ["product_id", "product_name", "brand", "category"]
SALE_COLUMNS = [
    "item_id",
    "order_id",
    "user_id",
    "product_id",
    "sale_price",
    "purchased_at",
    "brand",
    "category",
    "product_name",
    "item_status",
    "order_status",
]
RELATIONS = {"sales", "transactions", "products"}
DEFAULT_SOURCE_DATASET = "bigquery-public-data.thelook_ecommerce"
FORBIDDEN_COLUMNS = {
    "email",
    "first_name",
    "last_name",
    "name",
    "street_address",
    "postal_code",
    "zip",
    "zipcode",
    "latitude",
    "longitude",
    "ip_address",
    "phone",
    "phone_number",
    "state",
    "city",
    "country",
    "address",
    "gender",
    "age",
}
# Pure scalar/aggregate functions only. This is an execution capability boundary,
# not a list of metrics or question types. Unknown/custom/remote routines fail closed.
PURE_FUNCTIONS = {
    "AND",
    "OR",
    "XOR",
    "ABS",
    "ACOS",
    "ASIN",
    "ATAN",
    "ATAN2",
    "CEIL",
    "FLOOR",
    "ROUND",
    "TRUNC",
    "SIGN",
    "SQRT",
    "POW",
    "POWER",
    "EXP",
    "LN",
    "LOG",
    "LOG10",
    "MOD",
    "SUM",
    "AVG",
    "COUNT",
    "COUNT_IF",
    "MIN",
    "MAX",
    "MIN_BY",
    "MAX_BY",
    "ANY_VALUE",
    "ARRAY_AGG",
    "ARRAY_CONCAT_AGG",
    "STDDEV",
    "STDDEV_POP",
    "STDDEV_SAMP",
    "VARIANCE",
    "VARIANCE_POP",
    "VARIANCE_SAMP",
    "VAR_POP",
    "VAR_SAMP",
    "CORR",
    "COVAR_POP",
    "COVAR_SAMP",
    "APPROX_DISTINCT",
    "APPROX_COUNT_DISTINCT",
    "APPROX_QUANTILES",
    "COALESCE",
    "NULLIF",
    "IF",
    "CASE",
    "CAST",
    "TRY_CAST",
    "SAFE_DIVIDE",
    "SAFE_ADD",
    "SAFE_SUBTRACT",
    "SAFE_MULTIPLY",
    "SAFE_NEGATE",
    "GREATEST",
    "LEAST",
    "ROW_NUMBER",
    "RANK",
    "DENSE_RANK",
    "NTILE",
    "LAG",
    "LEAD",
    "FIRST_VALUE",
    "FORMAT",
    "LAST_VALUE",
    "NTH_VALUE",
    "PERCENT_RANK",
    "CUME_DIST",
    "PERCENTILE_CONT",
    "PERCENTILE_DISC",
    "LOWER",
    "UPPER",
    "LENGTH",
    "CHAR_LENGTH",
    "CONCAT",
    "CONCAT_WS",
    "SUBSTRING",
    "STRPOS",
    "TRIM",
    "LTRIM",
    "RTRIM",
    "REPLACE",
    "SPLIT",
    "ARRAY_TO_STRING",
    "REGEXP_LIKE",
    "REGEXP_EXTRACT",
    "REGEXP_EXTRACT_ALL",
    "REGEXP_REPLACE",
    "STARTS_WITH",
    "ENDS_WITH",
    "CONTAINS_SUBSTR",
    "TIME_TO_STR",
    "STR_TO_DATE",
    "STR_TO_TIME",
    "DATE",
    "DATETIME",
    "TIMESTAMP",
    "TIME",
    "DATE_TRUNC",
    "DATETIME_TRUNC",
    "TIMESTAMP_TRUNC",
    "TIME_TRUNC",
    "DATE_ADD",
    "DATE_SUB",
    "DATE_DIFF",
    "DATEDIFF",
    "DATETIME_ADD",
    "DATETIME_SUB",
    "DATETIME_DIFF",
    "TIMESTAMP_ADD",
    "TIMESTAMP_SUB",
    "TIMESTAMPDIFF",
    "TIME_ADD",
    "TIME_SUB",
    "TIME_DIFF",
    "EXTRACT",
    "DATE_FROM_PARTS",
    "DATE_FROM_UNIX_DATE",
    "UNIX_DATE",
    "UNIX_SECONDS",
    "UNIX_MILLIS",
    "UNIX_MICROS",
    "UNIX_TO_TIME",
    "CURRENT_DATE",
    "CURRENT_TIME",
    "CURRENT_TIMESTAMP",
    "CURRENT_DATETIME",
    "TS_OR_DS_TO_DATE",
    "TS_OR_DS_TO_DATETIME",
    "TS_OR_DS_TO_TIMESTAMP",
    "LAST_DAY",
    "LAST_DAY_OF_MONTH",
    "GENERATE_DATE_ARRAY",
    "GENERATE_TIMESTAMP_ARRAY",
    "GENERATE_SERIES",
    "UNNEST",
    "ARRAY",
    "ARRAY_SIZE",
    "ARRAY_LENGTH",
    "ARRAY_CONCAT",
    "ARRAY_SLICE",
    "ARRAY_REVERSE",
    "STRUCT",
    "EXISTS",
    "IFNULL",
    "BOOL_AND",
    "BOOL_OR",
    "LOGICAL_AND",
    "LOGICAL_OR",
    "IS_INF",
    "IS_NAN",
    "TO_CHAR",
    "TO_JSON_STRING",
    "JSON_EXTRACT_SCALAR",
}


class DataError(Exception):
    """A safe, model-visible tool failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _read_query(sql: str, sources: set[str]) -> tuple[exp.Expr, list[exp.Table]]:
    if not sql.strip() or len(sql.encode()) > 30_000:
        raise DataError("invalid_request", "Supply one SELECT query under 30 KB.")
    try:
        statements = sqlglot.parse(sql, read="bigquery")
    except ParseError:
        raise DataError("invalid_request", "SQL could not be parsed as BigQuery SQL.") from None
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
        raise DataError("denied", "Only one read-only SELECT query is permitted.")
    tree = statements[0]
    blocked_types = (
        exp.DDL,
        DML,
        exp.Command,
        exp.Into,
        exp.Lock,
        exp.TableSample,
        exp.Version,
    )
    for node in tree.walk():
        if isinstance(node, blocked_types):
            raise DataError(
                "denied", "Scripts, writes, sampling and external operations are denied."
            )
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise DataError("denied", "Recursive queries are not enabled.")
        if isinstance(node, exp.Identifier) and node.name.startswith("__"):
            raise DataError("denied", "The query requests a reserved identifier.")
        if isinstance(node, exp.Column) and node.name.lower() in FORBIDDEN_COLUMNS:
            raise DataError("denied", "The query requests a private or reserved identifier.")
        if isinstance(node, exp.Func):
            if isinstance(node, exp.Anonymous) or node.sql_name() not in PURE_FUNCTIONS:
                raise DataError(
                    "denied", "That function is not an enabled pure analytical built-in."
                )
            if isinstance(node.parent, exp.Dot):
                raise DataError("denied", "Qualified/custom routines are not permitted.")
        if isinstance(node, exp.Parameter) and node.name.startswith("__"):
            raise DataError("denied", "Reserved parameters cannot be supplied by the analyst.")
    for cte in tree.find_all(exp.CTE):
        if cte.alias_or_name.lower() in sources:
            raise DataError("denied", "CTEs cannot shadow authorized source names.")
    tables: list[exp.Table] = []
    try:
        for scope in traverse_scope(tree):
            for _, source in scope.selected_sources.values():
                if isinstance(source, exp.Table):
                    if (
                        source.catalog
                        or source.db
                        or not isinstance(source.this, exp.Identifier)
                        or source.name.lower() not in sources
                    ):
                        raise DataError(
                            "denied", "Only documented authorized relations are available."
                        )
                    tables.append(source)
    except OptimizeError:
        raise DataError(
            "invalid_request", "SQL aliases are ambiguous; use distinct relation aliases."
        ) from None
    # No unvisited table source may hide inside an unsupported relational construct.
    resolved = {id(table) for table in tables}
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if id(table) not in resolved and (
            table.catalog or table.db or table.name.lower() not in cte_names
        ):
            raise DataError("denied", "The query contains an unresolved source.")
    return tree, tables


def _literal(value: Any) -> exp.Expr:
    if value is None:
        return exp.Null()
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise DataError("invalid_request", "Parameters must be finite JSON values.")
        return exp.Literal.number(str(value))
    if isinstance(value, str) and len(value) <= 10_000:
        return exp.Literal.string(value)
    raise DataError("invalid_request", "Parameters must be scalar JSON values.")


def _bind(tree: exp.Expr, parameters: dict[str, Any] | None) -> exp.Expr:
    values = parameters or {}
    names = {parameter.name for parameter in tree.find_all(exp.Parameter)}
    if names != set(values) or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", n) for n in names):
        raise DataError(
            "invalid_request", "Provide exactly the named scalar parameters used by SQL."
        )
    for parameter in list(tree.find_all(exp.Parameter)):
        parameter.replace(_literal(values[parameter.name]))
    return tree


def _source_dataset(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Warehouse source must be a trusted project.dataset identifier")
    return value


def _freeze_clock(tree: exp.Expr, as_of: dt.datetime | None) -> exp.Expr:
    """Freeze volatile SQL clock expressions before either backend executes them."""
    if as_of is None:
        return tree
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("SQL clock must be timezone-aware")
    for node in list(tree.walk()):
        if not isinstance(
            node, (exp.CurrentDate, exp.CurrentDatetime, exp.CurrentTime, exp.CurrentTimestamp)
        ):
            continue
        zone = node.args.get("this")
        if zone is not None and not (isinstance(zone, exp.Literal) and zone.is_string):
            raise DataError("invalid_request", "Clock timezone must be a literal or bound string.")
        try:
            instant = as_of.astimezone(ZoneInfo(zone.this) if zone else dt.UTC)
        except (ValueError, ZoneInfoNotFoundError):
            raise DataError("invalid_request", "Clock timezone is not recognized.") from None
        if isinstance(node, exp.CurrentTimestamp):
            kind, value = "TIMESTAMP", as_of.astimezone(dt.UTC).isoformat()
        elif isinstance(node, exp.CurrentDate):
            kind, value = "DATE", instant.date().isoformat()
        elif isinstance(node, exp.CurrentDatetime):
            kind, value = "DATETIME", instant.replace(tzinfo=None).isoformat()
        else:
            kind, value = "TIME", instant.time().isoformat()
        node.replace(
            exp.Cast(
                this=exp.Literal.string(value), to=exp.DataType.build(kind, dialect="bigquery")
            )
        )
    return tree


def source_table(
    dataset: str, table: str, snapshot_at: dt.datetime | None = None, *, alias: str | None = None
) -> str:
    """Trusted physical source, optionally pinned to a warehouse version by the harness."""
    _source_dataset(dataset)
    if table not in {"products", "orders", "order_items", "users"}:
        raise ValueError("Unknown physical source table")
    source = f"`{dataset}.{table}`"
    if alias is not None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
            raise ValueError("Invalid physical source alias")
        source += f" AS {alias}"
    if snapshot_at is not None:
        if snapshot_at.utcoffset() is None:
            raise ValueError("Warehouse snapshot timestamp must be timezone-aware")
        source += f" FOR SYSTEM_TIME AS OF TIMESTAMP '{snapshot_at.astimezone(dt.UTC).isoformat()}'"
    return source


def _base_relation(
    name: str,
    brands: tuple[str, ...] | None,
    source_dataset: str,
    snapshot_at: dt.datetime | None = None,
) -> exp.Select:
    scope = "TRUE" if brands is None else "p.brand IN UNNEST(@__scope_brands)"
    products = f"""SELECT p.id AS product_id, p.name AS product_name, p.brand, p.category
        FROM {source_table(source_dataset, "products", snapshot_at, alias="p")} WHERE {scope}"""
    if name == "products":
        return cast(exp.Select, sqlglot.parse_one(products, read="bigquery"))
    statuses = (
        "AND i.status NOT IN ('Cancelled', 'Returned') "
        "AND o.status NOT IN ('Cancelled', 'Returned')"
        if name == "sales"
        else ""
    )
    sql = f"""SELECT i.id AS item_id, i.order_id, i.user_id, i.product_id,
        i.sale_price, i.created_at AS purchased_at, p.brand, p.category,
        p.name AS product_name, i.status AS item_status, o.status AS order_status
        FROM {source_table(source_dataset, "order_items", snapshot_at, alias="i")}
        JOIN {source_table(source_dataset, "orders", snapshot_at, alias="o")}
          ON o.order_id = i.order_id AND o.user_id = i.user_id
        JOIN {source_table(source_dataset, "products", snapshot_at, alias="p")} ON p.id = i.product_id
        WHERE {scope} {statuses}"""
    return cast(exp.Select, sqlglot.parse_one(sql, read="bigquery"))


def compile_query(
    sql: str,
    brands: tuple[str, ...] | None,
    parameters: dict | None = None,
    *,
    source_dataset: str = DEFAULT_SOURCE_DATASET,
    as_of: dt.datetime | None = None,
    snapshot_at: dt.datetime | None = None,
) -> str:
    """Replace every resolved physical logical source with a scoped projection."""
    tree, tables = _read_query(sql, RELATIONS)
    _bind(tree, parameters)
    _freeze_clock(tree, as_of)
    _source_dataset(source_dataset)
    for table in tables:
        alias = table.alias_or_name
        table.replace(
            _base_relation(table.name.lower(), brands, source_dataset, snapshot_at).subquery(
                alias=alias
            )
        )
    return tree.sql(dialect="bigquery")


def _json_value(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    if isinstance(value, bytes):
        raise DataError(
            "invalid_request", "Binary results are not supported; request textual aggregates."
        )
    return value


def _result(
    columns: list[str],
    rows: list,
    total_rows: int | None,
    sql: str,
    backend: str,
    job_id: str | None = None,
    bytes_processed: int = 0,
    truncated: bool = False,
) -> dict:
    if len(columns) != len(set(columns)):
        raise DataError("invalid_request", "Give result columns distinct aliases.")
    result = {
        "sql": sql,
        "columns": columns,
        "rows": [{k: _json_value(v) for k, v in zip(columns, row, strict=True)} for row in rows],
        "total_rows": total_rows,
        "truncated": truncated,
        "backend": backend,
        "job_id": job_id,
        "bytes_processed": bytes_processed,
        "definitions": DEFINITIONS,
        "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
        "executed_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    if len(json.dumps(result).encode()) > 250_000:
        raise DataError(
            "limit_reached", "Result exceeds 250 KB; request a smaller aggregate or page."
        )
    return result


def _fixture_views(connection: Any, brands: tuple[str, ...] | None) -> None:
    connection.execute("CREATE TABLE allowed_brands (brand VARCHAR)")
    if brands is not None and brands:
        connection.executemany("INSERT INTO allowed_brands VALUES (?)", [(b,) for b in brands])
    where = "" if brands is None else "WHERE brand IN (SELECT brand FROM allowed_brands)"
    connection.execute(f"CREATE VIEW products AS SELECT * FROM fixture_products {where}")
    connection.execute("""CREATE VIEW transactions AS
        SELECT i.item_id, i.order_id, i.user_id, i.product_id, i.sale_price, i.purchased_at,
            p.brand, p.category, p.product_name, i.item_status, o.order_status
        FROM fixture_items i JOIN fixture_orders o
            ON o.order_id = i.order_id AND o.user_id = i.user_id
        JOIN products p ON p.product_id = i.product_id""")
    connection.execute("""CREATE VIEW sales AS SELECT * FROM transactions
        WHERE item_status NOT IN ('Cancelled', 'Returned')
          AND order_status NOT IN ('Cancelled', 'Returned')""")


def _register_results(connection: Any, results: dict[str, dict]) -> None:
    for name, artifact in results.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            raise DataError("invalid_request", "Invalid result handle.")
        columns = artifact["columns"]
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", col) for col in columns):
            raise DataError("invalid_request", "Result columns must have ordinary SQL aliases.")
        rows = artifact["rows"]
        types = []
        for column in columns:
            values = [row.get(column) for row in rows if row.get(column) is not None]
            if values and all(isinstance(v, bool) for v in values):
                kind = "BOOLEAN"
            elif values and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
                kind = "BIGINT"
            elif values and all(isinstance(v, (int, float)) for v in values):
                kind = "DOUBLE"
            elif any(isinstance(v, (dict, list)) for v in values):
                raise DataError(
                    "invalid_request", "Flatten nested results before local SQL analysis."
                )
            else:
                kind = "VARCHAR"
            types.append(f'"{column}" {kind}')
        connection.execute(f'CREATE TABLE "{name}" ({", ".join(types)})')
        if rows:
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(
                f'INSERT INTO "{name}" VALUES ({placeholders})',
                [[row.get(c) for c in columns] for row in rows],
            )


def _local_worker(sender: Any, payload: dict) -> None:
    """Child process: trusted fixture initialization, then admitted SQL only."""
    try:
        import duckdb

        with duckdb.connect(
            config={
                "enable_external_access": "false",
                "memory_limit": "256MB",
                "threads": "1",
                "max_temp_directory_size": "0B",
            }
        ) as connection:
            connection.execute("SET TimeZone = 'UTC'")
            if payload.get("fixture"):
                connection.execute(payload["fixture"])
                _fixture_views(connection, payload["brands"])
            else:
                _register_results(connection, payload["results"])
            cursor = connection.execute(payload["sql"])
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchmany(payload["row_limit"] + 1)
            truncated = len(rows) > payload["row_limit"]
            result = _result(
                columns,
                rows[: payload["row_limit"]],
                None if truncated else len(rows),
                payload["logical_sql"],
                "fixture" if payload.get("fixture") else "local",
                truncated=truncated,
            )
            sender.send({"ok": result})
    except DataError as exc:
        sender.send({"error": {"code": exc.code, "message": exc.message}})
    except Exception as exc:
        # DuckDB may include raw SQL/file paths in errors. Retain an actionable category only.
        kind = type(exc).__name__
        message = {
            "BinderException": "SQL columns/types could not be resolved. Check describe_data and use explicit casts/aliases.",
            "ConversionException": "SQL type conversion failed. Use valid dates or SAFE_CAST.",
            "OutOfMemoryException": "Local query exceeded its memory allowance; request a smaller aggregate.",
        }.get(
            kind, "Local SQL execution failed. Check BigQuery-compatible SQL and reduce the result."
        )
        sender.send({"error": {"code": "invalid_request", "message": message}})
    finally:
        sender.close()


async def _run_local(payload: dict, timeout: float) -> dict:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_local_worker, args=(sender, payload), daemon=True)
    process.start()
    sender.close()
    try:
        ready = await asyncio.to_thread(receiver.poll, max(0.01, timeout))
        if not ready:
            raise DataError("limit_reached", "Local query timed out; simplify the query.")
        try:
            message = receiver.recv()
        except EOFError:
            raise DataError(
                "limit_reached", "Local query worker stopped before returning a result."
            ) from None
        if "error" in message:
            raise DataError(**message["error"])
        return message["ok"]
    finally:
        if process.is_alive():
            process.terminate()
        await asyncio.to_thread(process.join, 0.5)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 0.5)
        receiver.close()
        process.close()


async def analyze_results(
    results: dict[str, dict],
    sql: str,
    timeout: float = 5,
    *,
    as_of: dt.datetime | None = None,
) -> dict:
    """Query session-authorized result snapshots by their handle, without warehouse access."""
    if not results or len(results) > 10:
        raise DataError("invalid_request", "Select between one and ten existing result handles.")
    if any(result.get("truncated") for result in results.values()):
        raise DataError(
            "invalid_request",
            "A source result is truncated; obtain a complete smaller result first.",
        )
    if len(json.dumps(results).encode()) > 1_000_000:
        raise DataError(
            "limit_reached", "Selected result snapshots exceed the local analysis allowance."
        )
    tree, _ = _read_query(sql, {key.lower() for key in results})
    _bind(tree, None)
    _freeze_clock(tree, as_of)
    result = await _run_local(
        {
            "results": results,
            "sql": tree.sql(dialect="duckdb"),
            "logical_sql": sql,
            "row_limit": 200,
        },
        timeout,
    )
    result["parents"] = list(results)
    if as_of is not None:
        result["executed_at"] = as_of.astimezone(dt.UTC).isoformat()
    return result


class QueryGateway:
    def __init__(
        self,
        brands: tuple[str, ...] | None,
        project: str = "",
        backend: str = "bigquery",
        fixture_path: Path | None = None,
        max_bytes: int = 100_000_000,
        row_limit: int = 200,
        *,
        source_dataset: str = DEFAULT_SOURCE_DATASET,
        clock: Callable[[], dt.datetime] | None = None,
        snapshot_at: dt.datetime | None = None,
    ):
        if backend not in {"bigquery", "fixture"}:
            raise ValueError("backend must be bigquery or fixture")
        if not 1 <= row_limit <= 1000 or max_bytes < 1:
            raise ValueError("Invalid query resource limits")
        self.brands = brands
        self.project = project
        self.backend = backend
        self.fixture_path = fixture_path
        self.max_bytes = max_bytes
        self.row_limit = row_limit
        self.source_dataset = _source_dataset(source_dataset)
        self.clock = clock
        self.snapshot_at = snapshot_at
        self._client: Any = None
        self._job_ids: dict[str, str] = {}
        self._submitted: set[str] = set()

    def begin_turn(self) -> None:
        """Start a fresh retry namespace after the previous turn has settled.

        Identical retries within a turn recover one warehouse job. A later user
        turn must be allowed to submit a new job and observe newly available data.
        The caller serializes turns and awaits their cancellation/cleanup first.
        """
        self._job_ids.clear()
        self._submitted.clear()

    def describe_data(self, topic_or_relations: str = "") -> dict:
        return {
            "relations": {
                "sales": SALE_COLUMNS,
                "transactions": SALE_COLUMNS,
                "products": PRODUCT_COLUMNS,
            },
            "column_types": {
                "purchased_at": "TIMESTAMP UTC",
                "sale_price": "FLOAT64",
                "item_id/order_id/user_id/product_id": "INT64",
                "other_columns": "STRING",
            },
            "definitions": DEFINITIONS,
            "scope": list(self.brands) if self.brands is not None else "all brands",
            "joins": "sales/transactions.product_id = products.product_id; one row per order item",
            "inactivity_default": "90 days; define as-of boundary, eligible denominator and last authorized purchase before that boundary; zero denominator is undefined.",
            "geography": "query_state_summary returns only state aggregates, suppressing groups below five customers; no raw user geography.",
            "sql": "Use BigQuery SQL over these relations only. CTEs, joins, unions, windows and pure analytical built-ins are supported. Query parameters are scalar JSON values named with @name.",
        }

    async def query(self, sql: str, parameters: dict | None = None, timeout: float = 30) -> dict:
        if timeout <= 0:
            raise DataError("limit_reached", "The query deadline has expired.")
        as_of = self.clock() if self.clock is not None else None
        compiled = compile_query(
            sql,
            self.brands,
            parameters,
            source_dataset=self.source_dataset,
            as_of=as_of,
            snapshot_at=self.snapshot_at,
        )
        if self.backend == "fixture":
            if self.fixture_path is None or not self.fixture_path.is_file():
                raise DataError(
                    "invalid_request", "Fixture backend requires an existing synthetic fixture."
                )
            tree, _ = _read_query(sql, RELATIONS)
            _bind(tree, parameters)
            _freeze_clock(tree, as_of)
            try:
                local_sql = tree.sql(dialect="duckdb", unsupported_level=sqlglot.ErrorLevel.RAISE)
            except UnsupportedError:
                raise DataError(
                    "invalid_request",
                    "That BigQuery expression is not supported by the fixture engine.",
                ) from None
            result = await _run_local(
                {
                    "fixture": self.fixture_path.read_text(),
                    "brands": self.brands,
                    "sql": local_sql,
                    "logical_sql": sql,
                    "row_limit": self.row_limit,
                },
                timeout,
            )
        else:
            result = await self._warehouse(compiled, sql, timeout)
        result["parameters"] = parameters or {}
        result["scope"] = list(self.brands) if self.brands is not None else "all brands"
        if as_of is not None:
            result["executed_at"] = as_of.astimezone(dt.UTC).isoformat()
        return result

    def _execute_bigquery(self, compiled: str, logical: str, timeout: float, job_id: str) -> dict:
        from google.api_core import exceptions as cloud_errors
        from google.cloud import bigquery

        deadline = time.monotonic() + timeout

        def remaining() -> float:
            value = deadline - time.monotonic()
            if value <= 0:
                raise DataError("limit_reached", "The warehouse query deadline expired.")
            return value

        try:
            if self._client is None:
                self._client = bigquery.Client(project=self.project or None)
            parameters = (
                []
                if self.brands is None
                else [bigquery.ArrayQueryParameter("__scope_brands", "STRING", list(self.brands))]
            )
            config = bigquery.QueryJobConfig(
                dry_run=True, use_query_cache=False, query_parameters=parameters
            )
            dry = self._client.query(compiled, job_config=config, timeout=remaining(), retry=None)
            if (dry.total_bytes_processed or 0) > self.max_bytes:
                raise DataError(
                    "limit_reached",
                    "Query exceeds the warehouse byte allowance; narrow the period or selected columns.",
                )
            config = bigquery.QueryJobConfig(
                maximum_bytes_billed=self.max_bytes,
                query_parameters=parameters,
                use_query_cache=True,
            )
            try:
                self._submitted.add(job_id)
                job = self._client.query(
                    compiled,
                    job_config=config,
                    job_id=job_id,
                    timeout=remaining(),
                    retry=None,
                    job_retry=None,
                )
            except cloud_errors.Conflict:
                job = self._client.get_job(job_id, timeout=remaining(), retry=None)
            rows = job.result(
                timeout=remaining(),
                retry=None,
                job_retry=None,
                page_size=self.row_limit,
                max_results=self.row_limit,
            )
            columns = [field.name for field in rows.schema]
            values = [tuple(row.values()) for row in rows]
            total = rows.total_rows
            return _result(
                columns,
                values,
                total,
                logical,
                "bigquery",
                job.job_id,
                int(job.total_bytes_processed or 0),
                total > len(values),
            )
        except DataError:
            raise
        except cloud_errors.BadRequest:
            raise DataError(
                "invalid_request",
                "BigQuery rejected the SQL or resource limit. Check column names, types, built-ins and query size.",
            ) from None
        except cloud_errors.Forbidden:
            raise DataError(
                "denied",
                "Warehouse credentials do not permit this query. Scope cannot be expanded.",
            ) from None
        except (TimeoutError, cloud_errors.DeadlineExceeded):
            raise DataError(
                "limit_reached", "Warehouse query timed out; cancellation was requested."
            ) from None
        except cloud_errors.GoogleAPICallError:
            raise DataError(
                "retryable_failure", "Warehouse is temporarily unavailable; no result was returned."
            ) from None
        except Exception:
            raise DataError(
                "retryable_failure",
                "Warehouse initialization or execution failed; check local credentials/configuration.",
            ) from None

    async def _warehouse(self, compiled: str, logical: str, timeout: float) -> dict:
        # Identical retries in this gateway recover the same warehouse job rather
        # than submitting another billable job when a response was lost.
        query_key = hashlib.sha256(compiled.encode()).hexdigest()
        job_id = self._job_ids.setdefault(query_key, "retail_" + uuid.uuid4().hex)
        try:
            async with asyncio.timeout(timeout):
                return await asyncio.to_thread(
                    self._execute_bigquery, compiled, logical, timeout, job_id
                )
        except (TimeoutError, asyncio.CancelledError, DataError) as exc:
            if self._client is not None and job_id in self._submitted:
                try:
                    async with asyncio.timeout(1):
                        await asyncio.to_thread(
                            self._client.cancel_job, job_id, timeout=1, retry=None
                        )
                except Exception:
                    pass
            if isinstance(exc, TimeoutError):
                raise DataError(
                    "limit_reached", "Warehouse query timed out; cancellation was requested."
                ) from None
            raise

    async def state_summary(
        self, start: str, end: str, status_definition: str = "qualifying", timeout: float = 30
    ) -> dict:
        try:
            start_date, end_date = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        except ValueError:
            raise DataError(
                "invalid_request", "State summary requires ISO dates YYYY-MM-DD."
            ) from None
        if start_date >= end_date:
            raise DataError(
                "invalid_request", "The start date must precede the exclusive end date."
            )
        statuses = {
            "qualifying": "i.status NOT IN ('Cancelled','Returned') AND o.status NOT IN ('Cancelled','Returned')",
            "complete": "i.status = 'Complete' AND o.status = 'Complete'",
            "all": "TRUE",
        }
        if status_definition not in statuses:
            raise DataError(
                "invalid_request", "State summary statuses: qualifying, complete, or all."
            )
        if self.backend == "fixture":
            raise DataError("invalid_request", "This synthetic fixture has no customer geography.")
        scope = "TRUE" if self.brands is None else "p.brand IN UNNEST(@__scope_brands)"
        sql = f"""SELECT u.state, COUNT(DISTINCT i.user_id) AS customers,
            COUNT(DISTINCT i.order_id) AS orders, SUM(i.sale_price) AS revenue
            FROM {source_table(self.source_dataset, "order_items", self.snapshot_at, alias="i")}
            JOIN {source_table(self.source_dataset, "orders", self.snapshot_at, alias="o")}
              ON o.order_id=i.order_id AND o.user_id=i.user_id
            JOIN {source_table(self.source_dataset, "products", self.snapshot_at, alias="p")} ON p.id=i.product_id
            JOIN {source_table(self.source_dataset, "users", self.snapshot_at, alias="u")} ON u.id=i.user_id
            WHERE {scope} AND {statuses[status_definition]}
              AND i.created_at >= TIMESTAMP '{start_date.isoformat()}'
              AND i.created_at < TIMESTAMP '{end_date.isoformat()}'
            GROUP BY u.state HAVING COUNT(DISTINCT i.user_id) >= 5 ORDER BY revenue DESC, u.state"""
        result = await self._warehouse(
            sql, f"state_summary({start!r}, {end!r}, {status_definition!r})", timeout
        )
        result["definitions"] = (
            f"State aggregates, status={status_definition}, UTC [{start},{end}); only groups with "
            "at least five distinct customers are returned. Suppressed states are omitted, "
            "so visible totals may not equal all-brand-scope totals. No individual geography is exposed."
        )
        result["scope"] = list(self.brands) if self.brands is not None else "all brands"
        if self.clock is not None:
            result["executed_at"] = self.clock().astimezone(dt.UTC).isoformat()
        return result
