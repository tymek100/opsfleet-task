"""Validate synthetic retrieval examples offline, independently of the application.

This checks the frozen fixture and reference evidence. It neither runs the agent
nor grades future LLM answers. It is not the production SQL security boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import jsonschema
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

ROOT = Path(__file__).resolve().parents[1]
VIRTUAL_RELATIONS = {"sales", "transactions", "products"}


def set_scope(connection: duckdb.DuckDBPyConnection, brands: list[str]) -> None:
    """Bind fixture scope outside the example SQL and before joins/history."""
    connection.execute("CREATE OR REPLACE TABLE fixture_allowed_brands (brand VARCHAR)")
    connection.executemany("INSERT INTO fixture_allowed_brands VALUES (?)", [(b,) for b in brands])
    connection.execute("""
        CREATE OR REPLACE VIEW products AS
        SELECT p.* FROM fixture_products AS p
        JOIN fixture_allowed_brands AS a ON a.brand = p.brand
    """)
    connection.execute("""
        CREATE OR REPLACE VIEW transactions AS
        SELECT i.item_id, i.order_id, i.user_id, i.product_id, i.sale_price,
               i.purchased_at, p.brand, p.category, p.product_name,
               i.item_status, o.order_status
        FROM fixture_items AS i
        JOIN fixture_orders AS o ON o.order_id = i.order_id AND o.user_id = i.user_id
        JOIN products AS p ON p.product_id = i.product_id
    """)
    connection.execute("""
        CREATE OR REPLACE VIEW sales AS
        SELECT * FROM transactions
        WHERE item_status NOT IN ('Cancelled', 'Returned')
          AND order_status NOT IN ('Cancelled', 'Returned')
    """)


def transpile_example(sql: str) -> str:
    statements = sqlglot.parse(sql, read="bigquery")
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
        raise ValueError("Each example query must contain one read-only SELECT statement")
    tree = statements[0]
    for cte in tree.find_all(exp.CTE):
        if cte.alias_or_name.lower() in VIRTUAL_RELATIONS:
            raise ValueError("Example CTEs cannot shadow the scoped virtual relations")
    for scope in traverse_scope(tree):
        for _, source in scope.selected_sources.values():
            if isinstance(source, exp.Table) and (
                source.catalog or source.db or source.name.lower() not in VIRTUAL_RELATIONS
            ):
                raise ValueError(f"Example uses a non-virtual source: {source.sql()}")
    return tree.sql(dialect="duckdb")


def compare(actual: Any, expected: Any, location: str) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise AssertionError(f"{location}: result columns differ")
        for key in expected:
            compare(actual[key], expected[key], f"{location}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise AssertionError(f"{location}: row counts differ")
        for index, (value, wanted) in enumerate(zip(actual, expected, strict=True)):
            compare(value, wanted, f"{location}[{index}]")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or not math.isclose(
            actual, expected, rel_tol=1e-9, abs_tol=1e-9
        ):
            raise AssertionError(f"{location}: expected {expected!r}, got {actual!r}")
    elif actual != expected:
        raise AssertionError(f"{location}: expected {expected!r}, got {actual!r}")


def rows_for(connection: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = connection.execute(transpile_example(sql))
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def check_fixture_oracles(connection: duckdb.DuckDBPyConnection) -> None:
    """Independently enumerated fixture totals expose scope/status/grain mistakes."""
    set_scope(connection, ["Calvin Klein"])
    compare(
        rows_for(
            connection,
            """
            SELECT SUM(sale_price) AS revenue, COUNT(*) AS items,
                   COUNT(DISTINCT order_id) AS orders, COUNT(DISTINCT user_id) AS customers
            FROM sales WHERE purchased_at >= '2026-01-01' AND purchased_at < '2026-04-01'
        """,
        ),
        [{"revenue": 375.0, "items": 7, "orders": 6, "customers": 5}],
        "fixture.Calvin_Klein.Q1",
    )
    compare(
        rows_for(connection, "SELECT SUM(sale_price) AS revenue FROM sales"),
        [{"revenue": 455.0}],
        "fixture.Calvin_Klein.all_history",
    )
    compare(
        rows_for(connection, "SELECT SUM(sale_price) AS revenue FROM sales WHERE order_id = 10"),
        [{"revenue": 125.0}],
        "fixture.Calvin_Klein.mixed_brand_order",
    )
    set_scope(connection, ["Levi's"])
    compare(
        rows_for(connection, "SELECT SUM(sale_price) AS revenue FROM sales"),
        [{"revenue": 1900.0}],
        "fixture.other_brand",
    )
    set_scope(connection, ["Calvin Klein", "Levi's"])
    compare(
        rows_for(connection, "SELECT SUM(sale_price) AS revenue FROM sales"),
        [{"revenue": 2355.0}],
        "fixture.all_brands",
    )


def validate(path: Path) -> tuple[int, int, int]:
    collection = json.loads(path.read_text())
    schema_path = ROOT / "knowledge/golden/bootstrap.schema.json"
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        collection
    )
    fixture = ROOT / collection["fixture"]["path"]
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    if digest != collection["fixture"]["sha256"]:
        raise AssertionError(
            "Frozen fixture digest changed; review and revalidate the seed evidence"
        )

    ids: set[str] = set()
    query_count = 0
    fact_count = 0
    # Never install/load extensions or read external files for fixture SQL.
    with duckdb.connect(config={"enable_external_access": "false"}) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        connection.execute(fixture.read_text())
        check_fixture_oracles(connection)
        for example in collection["examples"]:
            key = example["id"]
            if key in ids:
                raise AssertionError(f"Duplicate example ID: {key}")
            ids.add(key)
            set_scope(connection, example["scope"]["brands"])
            results: dict[str, list[dict[str, Any]]] = {}
            for query in example["queries"]:
                query_id = query["id"]
                if query_id in results:
                    raise AssertionError(f"Duplicate query ID in {key}: {query_id}")
                rows = rows_for(connection, query["sql"])
                compare(rows, query["evidence"]["rows"], f"{key}.{query_id}")
                results[query_id] = rows
                query_count += 1
            for fact in example["checked_facts"]:
                actual = results[fact["query_id"]][fact["row"]][fact["column"]]
                compare(actual, fact["expected"], f"{key}.checked_fact.{fact['column']}")
                fact_count += 1
            print(f"PASS {key} ({len(results)} queries)")
    return len(ids), query_count, fact_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, default=ROOT / "knowledge/golden/bootstrap.json")
    args = parser.parse_args()
    examples, queries, facts = validate(args.collection)
    print(f"Validated {examples} examples, {queries} SQL queries, {facts} explicit evidence facts.")
    print("Offline synthetic evidence only; no live BigQuery, agent run or human approval.")


if __name__ == "__main__":
    main()
