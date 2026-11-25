"""Composable SQL over authorized inventory records and public facility metadata."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import multiprocessing
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from retail_insight.integrations.bigquery.retail import (
    DEFAULT_SOURCE_DATASET,
    DataError,
    QueryGateway,
    _bind,
    _freeze_clock,
    _read_query,
    _result,
    _source_dataset,
)

DEFAULT_FIXTURE = Path(__file__).with_name("fixtures.json")
DEFINITIONS = (
    "scoped-inventory-v1. Each inventory row represents one recorded inventory unit. "
    "stock contains records with created_at <= as_of and (sold_at IS NULL OR "
    "sold_at > as_of), excluding invalid chronology. This models unsold stock, not physical "
    "availability or reservations. inventory includes all authorized records for quality checks. "
    "Apply COUNT(DISTINCT inventory_id) when joins may duplicate units. cost is recorded "
    "inventory cost, not retail price/profit; currency is unspecified. Missing cost is unknown. "
    "inventory_center_id comes from the inventory item; catalog_center_id is the product's "
    "current catalog assignment. Do not substitute one for the other. Missing/unmapped centers "
    "must remain in an Unknown bucket so stock totals reconcile. Distinct products across "
    "centers are nonadditive. snapshot_at is physical table version; as_of is business cutoff. "
    "Current records do not reconstruct historical knowledge or movements. No capacities, "
    "reservations, incoming purchase orders, supplier lead times or confirmed shipment origins "
    "are available. Demand requires a scoped sales artifact; this service has no sales relation."
)
PRODUCT_COLUMNS = ["product_id", "product_name", "brand", "category", "catalog_center_id"]
INVENTORY_COLUMNS = [
    "inventory_id",
    "product_id",
    "created_at",
    "sold_at",
    "cost",
    "inventory_center_id",
    "catalog_center_id",
    "product_name",
    "brand",
    "category",
]
CENTER_COLUMNS = ["center_id", "center_name", "center_latitude", "center_longitude"]


def _physical(dataset: str, table: str, alias: str, snapshot_at: dt.datetime | None) -> str:
    _source_dataset(dataset)
    if table not in {"products", "inventory_items", "distribution_centers"}:
        raise ValueError("Unknown physical inventory source")
    source = f"`{dataset}.{table}` AS {alias}"
    if snapshot_at is not None:
        if snapshot_at.utcoffset() is None:
            raise ValueError("Snapshot timestamp must be timezone-aware")
        source += " FOR SYSTEM_TIME AS OF TIMESTAMP " + repr(
            snapshot_at.astimezone(dt.UTC).isoformat()
        )
    return source


def _relation(
    name: str,
    brands: tuple[str, ...] | None,
    dataset: str,
    as_of: dt.datetime,
    snapshot_at: dt.datetime | None,
    *,
    fixture: bool = False,
) -> exp.Select:
    def table(name: str, alias: str) -> str:
        return f"raw_{name} AS {alias}" if fixture else _physical(dataset, name, alias, snapshot_at)

    scope = "TRUE" if brands is None else "p.brand IN UNNEST(@__scope_brands)"
    if fixture and brands is not None:
        scope = "p.brand IN (SELECT brand FROM allowed_brands)"
    if name == "centers":
        query = f"""SELECT d.id AS center_id, d.name AS center_name,
          d.latitude AS center_latitude, d.longitude AS center_longitude
          FROM {table("distribution_centers", "d")}"""
    elif name == "products":
        query = f"""SELECT p.id AS product_id, p.name AS product_name, p.brand, p.category,
          p.distribution_center_id AS catalog_center_id FROM {table("products", "p")}
          WHERE {scope}"""
    else:
        cutoff = exp.Literal.string(as_of.astimezone(dt.UTC).isoformat()).sql(dialect="bigquery")
        stock = (
            f"AND i.created_at <= TIMESTAMP({cutoff}) "
            f"AND (i.sold_at IS NULL OR i.sold_at > TIMESTAMP({cutoff})) "
            "AND (i.sold_at IS NULL OR i.sold_at >= i.created_at)"
            if name == "stock"
            else ""
        )
        query = f"""SELECT i.id AS inventory_id, i.product_id, i.created_at, i.sold_at,
          i.cost, i.product_distribution_center_id AS inventory_center_id,
          p.distribution_center_id AS catalog_center_id, p.name AS product_name,
          p.brand, p.category FROM {table("inventory_items", "i")}
          JOIN {table("products", "p")} ON p.id = i.product_id WHERE {scope} {stock}"""
    relation = sqlglot.parse_one(query, read="bigquery")
    assert isinstance(relation, exp.Select)
    return relation


def compile_domain_query(
    sql: str,
    brands: tuple[str, ...] | None,
    *,
    role: str,
    as_of: dt.datetime,
    parameters: dict | None = None,
    source_dataset: str = DEFAULT_SOURCE_DATASET,
    snapshot_at: dt.datetime | None = None,
    fixture: bool = False,
) -> str:
    if role not in {"inventory", "distribution"}:
        raise ValueError("Unknown domain")
    if as_of.utcoffset() is None:
        raise ValueError("Business cutoff must be timezone-aware")
    sources = {"products", "inventory", "stock"}
    if role == "distribution":
        sources.add("centers")
    tree, tables = _read_query(sql, sources)
    _bind(tree, parameters)
    _freeze_clock(tree, as_of)
    for table in tables:
        table.replace(
            _relation(
                table.name.lower(), brands, source_dataset, as_of, snapshot_at, fixture=fixture
            ).subquery(alias=table.alias_or_name)
        )
    return tree.sql(
        dialect="duckdb" if fixture else "bigquery", unsupported_level=sqlglot.ErrorLevel.RAISE
    )


_FIXTURE_SCHEMA = {
    "products": [
        ("id", "BIGINT"),
        ("name", "VARCHAR"),
        ("brand", "VARCHAR"),
        ("category", "VARCHAR"),
        ("distribution_center_id", "BIGINT"),
    ],
    "inventory_items": [
        ("id", "BIGINT"),
        ("product_id", "BIGINT"),
        ("created_at", "TIMESTAMPTZ"),
        ("sold_at", "TIMESTAMPTZ"),
        ("cost", "DECIMAL(18,4)"),
        ("product_distribution_center_id", "BIGINT"),
    ],
    "distribution_centers": [
        ("id", "BIGINT"),
        ("name", "VARCHAR"),
        ("latitude", "DOUBLE"),
        ("longitude", "DOUBLE"),
    ],
}


def _fixture_worker(sender: Any, payload: dict) -> None:
    try:
        import duckdb

        with duckdb.connect(
            config={
                "enable_external_access": "false",
                "memory_limit": "256MB",
                "threads": "1",
                "max_temp_directory_size": "0B",
            }
        ) as con:
            con.execute("SET TimeZone = 'UTC'")
            con.execute("CREATE TABLE allowed_brands (brand VARCHAR)")
            if payload["brands"]:
                con.executemany(
                    "INSERT INTO allowed_brands VALUES (?)", [(b,) for b in payload["brands"]]
                )
            for table, fields in _FIXTURE_SCHEMA.items():
                con.execute(
                    f"CREATE TABLE raw_{table} ({','.join(n + ' ' + t for n, t in fields)})"
                )
                rows = payload["fixture"].get(table, [])
                if rows:
                    con.executemany(
                        f"INSERT INTO raw_{table} VALUES ({','.join('?' for _ in fields)})",
                        [[row.get(n) for n, _ in fields] for row in rows],
                    )
            cursor = con.execute(payload["compiled"])
            columns = [field[0] for field in cursor.description]
            rows = cursor.fetchmany(payload["row_limit"] + 1)
            truncated = len(rows) > payload["row_limit"]
            sender.send(
                {
                    "ok": _result(
                        columns,
                        rows[: payload["row_limit"]],
                        None if truncated else len(rows),
                        payload["sql"],
                        "fixture",
                        truncated=truncated,
                    )
                }
            )
    except Exception as exc:
        code = exc.code if isinstance(exc, DataError) else "invalid_request"
        message = (
            exc.message
            if isinstance(exc, DataError)
            else (
                "Inventory query failed; verify documented columns, types and BigQuery SQL. "
                f"Error category: {type(exc).__name__}."
            )
        )
        sender.send({"error": {"code": code, "message": message}})
    finally:
        sender.close()


async def _run_fixture(payload: dict, timeout: float) -> dict:
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_fixture_worker, args=(sender, payload), daemon=True)
    process.start()
    sender.close()
    try:
        if not await asyncio.to_thread(receiver.poll, max(0.01, timeout)):
            raise DataError("limit_reached", "Inventory fixture query timed out.")
        try:
            result = receiver.recv()
        except EOFError:
            raise DataError("limit_reached", "Inventory fixture worker stopped.") from None
        if "error" in result:
            raise DataError(**result["error"])
        return result["ok"]
    finally:
        if process.is_alive():
            process.terminate()
        await asyncio.to_thread(process.join, 0.5)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 0.5)
        receiver.close()
        process.close()


class DomainGateway(QueryGateway):
    """The model chooses SQL; code fixes source, scope, cutoff and resource limits."""

    def __init__(self, role: str, brands: tuple[str, ...] | None, **kwargs: Any):
        if role not in {"inventory", "distribution"}:
            raise ValueError("Unknown inventory domain")
        if kwargs.get("fixture_path") is None:
            kwargs["fixture_path"] = DEFAULT_FIXTURE
        super().__init__(brands, **kwargs)
        self.role = role

    def describe_data(self, topic_or_relations: str = "") -> dict:
        relations = {
            "products": PRODUCT_COLUMNS,
            "inventory": INVENTORY_COLUMNS,
            "stock": INVENTORY_COLUMNS,
        }
        if self.role == "distribution":
            relations["centers"] = CENTER_COLUMNS
        return {
            "relations": relations,
            "definitions": DEFINITIONS,
            "column_types": {
                "created_at/sold_at": "TIMESTAMP UTC",
                "cost": "FLOAT64 in BigQuery; fixed-decimal synthetic fixture",
                "all *_id": "INT64",
                "center_latitude/center_longitude": "FLOAT64",
            },
            "scope": list(self.brands) if self.brands is not None else "all brands",
            "joins": "stock/inventory.product_id = products.product_id; inventory_center_id = centers.center_id (LEFT JOIN to preserve unknown centers).",
            "sql": "BigQuery SELECT over documented relations only. Named scalar parameters @name. Pure expressions, CTEs, windows and joins allowed. stock already applies the trusted as_of cutoff; use inventory for other historical cutoffs and data-quality counts.",
        }

    describe = describe_data

    async def query(self, sql: str, parameters: dict | None = None, timeout: float = 30) -> dict:
        if timeout <= 0:
            raise DataError("limit_reached", "The query deadline expired.")
        as_of = self.clock() if self.clock else dt.datetime.now(dt.UTC)
        compiled = compile_domain_query(
            sql,
            self.brands,
            role=self.role,
            as_of=as_of,
            parameters=parameters,
            source_dataset=self.source_dataset,
            snapshot_at=self.snapshot_at,
            fixture=self.backend == "fixture",
        )
        if self.backend == "fixture":
            if self.fixture_path is None or not self.fixture_path.is_file():
                raise DataError("invalid_request", "Inventory fixture file is unavailable.")
            fixture = json.loads(self.fixture_path.read_text())
            result = await _run_fixture(
                {
                    "fixture": fixture,
                    "brands": self.brands,
                    "compiled": compiled,
                    "sql": sql,
                    "row_limit": self.row_limit,
                },
                timeout,
            )
        else:
            result = await self._warehouse(compiled, sql, timeout)
        result.update(
            {
                "definitions": DEFINITIONS,
                "parameters": parameters or {},
                "scope": list(self.brands) if self.brands is not None else "all brands",
                "as_of": as_of.isoformat(),
                "snapshot_at": self.snapshot_at.isoformat() if self.snapshot_at else None,
                "source_dataset": self.source_dataset
                if self.backend == "bigquery"
                else "synthetic-domain-fixture",
                "metric_version": "scoped-inventory-v1",
            }
        )
        return result
