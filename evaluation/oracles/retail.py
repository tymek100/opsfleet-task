"""Independent Decimal/set references; no application SQL or query gateway imports."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PERIODS = {
    "q4": ("2025-10-01", "2026-01-01"),
    "q1": ("2026-01-01", "2026-04-01"),
    "q2": ("2026-04-01", "2026-07-01"),
    "empty": ("2030-01-01", "2030-04-01"),
    "jan": ("2026-01-01", "2026-02-01"),
}
SCOPES: dict[str, tuple[str, ...] | None] = {
    "Calvin Klein": ("Calvin Klein",),
    "Levi's": ("Levi's",),
    "all brands": None,
}


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def fixture_file(name: str, suffix: str = ".json") -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or suffix not in {".json", ".sql"}:
        raise ValueError("Invalid fixture identifier")
    return FIXTURES / f"{name}{suffix}"


def load_fixture(name: str) -> dict[str, Any]:
    raw = json.loads(fixture_file(name).read_text())
    validate_rows(raw)
    return raw


def fixture_digest(name: str) -> str:
    return hashlib.sha256(fixture_file(name).read_bytes()).hexdigest()


def validate_rows(raw: dict[str, Any]) -> None:
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "synthetic",
        "products",
        "orders",
        "items",
    }:
        raise ValueError("Unexpected fixture fields")
    if raw["schema_version"] != 1 or raw["synthetic"] is not True:
        raise ValueError("Only versioned synthetic fixtures are supported")
    fields = {
        "products": {"product_id", "brand", "category", "product_name"},
        "orders": {"order_id", "user_id", "order_status"},
        "items": {
            "item_id",
            "order_id",
            "user_id",
            "product_id",
            "sale_price",
            "purchased_at",
            "item_status",
        },
    }
    for table, required in fields.items():
        if not isinstance(raw[table], list):
            raise ValueError("Fixture tables must be row lists")
        for row in raw[table]:
            if not isinstance(row, dict) or set(row) != required:
                raise ValueError(f"Unexpected fields in {table}")
            for key, value in row.items():
                if value is None and key in {"sale_price", "item_status", "order_status"}:
                    continue
                if key.endswith("_id"):
                    if type(value) is not int or value < 1:
                        raise ValueError("Fixture identities must be positive integers")
                elif not isinstance(value, str) or not value.strip():
                    raise ValueError("Fixture scalar fields must be nonempty strings")
    products = {p["product_id"]: p for p in raw["products"]}
    orders = {o["order_id"]: o for o in raw["orders"]}
    if len(products) != len(raw["products"]) or len(orders) != len(raw["orders"]):
        raise ValueError("Duplicate product/order IDs")
    seen: set[int] = set()
    for item in raw["items"]:
        if item["item_id"] in seen or item["product_id"] not in products:
            raise ValueError("Invalid item/product reference_scope")
        seen.add(item["item_id"])
        if item["order_id"] not in orders or orders[item["order_id"]]["user_id"] != item["user_id"]:
            raise ValueError("Item owner differs from order owner")
        try:
            valid_price = item["sale_price"] is None or Decimal(item["sale_price"]).is_finite()
        except InvalidOperation:
            valid_price = False
        if not valid_price:
            raise ValueError("Fixture prices must be finite")
        instant(item["purchased_at"])


def render_sql(raw: dict[str, Any]) -> str:
    """Render trusted fixture rows, preserving values without application compiler reuse."""
    validate_rows(raw)

    def literal(value: Any) -> str:
        if value is None:
            return "NULL"
        return str(value) if isinstance(value, int) else "'" + str(value).replace("'", "''") + "'"

    tables = [
        (
            "products",
            "product_id INTEGER, brand VARCHAR, category VARCHAR, product_name VARCHAR",
            ["product_id", "brand", "category", "product_name"],
        ),
        (
            "orders",
            "order_id INTEGER, user_id INTEGER, order_status VARCHAR",
            ["order_id", "user_id", "order_status"],
        ),
        (
            "items",
            "item_id INTEGER, order_id INTEGER, user_id INTEGER, product_id INTEGER, "
            "sale_price DOUBLE, purchased_at TIMESTAMP, item_status VARCHAR",
            [
                "item_id",
                "order_id",
                "user_id",
                "product_id",
                "sale_price",
                "purchased_at",
                "item_status",
            ],
        ),
    ]
    statements = ["-- Synthetic evaluation data; separate from runtime Golden Knowledge."]
    for name, ddl, columns in tables:
        statements.append(f"CREATE TABLE fixture_{name} ({ddl});")
        if raw[name]:
            rows = [
                "(" + ", ".join(literal(row[col]) for col in columns) + ")" for row in raw[name]
            ]
            statements.append(f"INSERT INTO fixture_{name} VALUES\n" + ",\n".join(rows) + ";")
    return "\n".join(statements) + "\n"


def transactions(
    raw: dict[str, Any], reference_scope: str, *, qualifying: bool = True
) -> list[dict[str, Any]]:
    products = {p["product_id"]: p for p in raw["products"]}
    orders = {o["order_id"]: o for o in raw["orders"]}
    brands = SCOPES[reference_scope]
    selected = []
    for item in raw["items"]:
        product, order = products[item["product_id"]], orders[item["order_id"]]
        if brands is not None and product["brand"] not in brands:
            continue
        if qualifying and (
            item["item_status"] is None
            or order["order_status"] is None
            or item["item_status"] in {"Cancelled", "Returned"}
            or order["order_status"] in {"Cancelled", "Returned"}
        ):
            continue
        selected.append(
            {
                **item,
                **product,
                "order_status": order["order_status"],
                "price": None if item["sale_price"] is None else Decimal(item["sale_price"]),
                "at": instant(item["purchased_at"]),
            }
        )
    return selected


def period_rows(rows: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    start, end = map(instant, PERIODS[period])
    return [row for row in rows if start <= row["at"] < end]


def sql_sum(values: list[Decimal | None]) -> Decimal | None:
    """Match SUM: ignore individual NULLs; all-NULL and empty inputs stay NULL."""
    known = [value for value in values if value is not None]
    return sum(known, Decimal(0)) if known else None


def totals(rows: list[dict[str, Any]]) -> dict[str, Decimal | int | None]:
    summed = sql_sum([row["price"] for row in rows])
    # Business empty-period controls report zero activity; missing observed prices
    # are different and remain unknown. sql_revenue always preserves SQL SUM.
    revenue = Decimal(0) if not rows else summed
    order_count = len({row["order_id"] for row in rows})
    return {
        "revenue": revenue,
        "sql_revenue": summed,
        "priced_items": sum(row["price"] is not None for row in rows),
        "null_price_items": sum(row["price"] is None for row in rows),
        "items": len(rows),
        "orders": order_count,
        "customers": len({row["user_id"] for row in rows}),
        "aov": revenue / order_count if order_count and revenue is not None else None,
    }


def metric_value(rows: list[dict[str, Any]], metric: str) -> Decimal:
    value = totals(rows)[metric]
    if value is None:
        raise ValueError(f"Undefined metric: {metric}")
    return Decimal(value)


def snapshot(name: str, reference_scope: str = "Calvin Klein") -> dict[str, str | None]:
    """Flat, keyed references used by persisted facts and independent validation."""
    raw = load_fixture(name)
    rows = transactions(raw, reference_scope)
    q1, q4 = period_rows(rows, "q1"), period_rows(rows, "q4")
    result: dict[str, Any] = {}
    result["q1.null_price_revenue"] = sql_sum([row["price"] for row in q1 if row["price"] is None])
    for period in PERIODS:
        result.update(
            {f"{period}.{key}": value for key, value in totals(period_rows(rows, period)).items()}
        )
    result.update(
        {
            f"q1_all_status.{key}": value
            for key, value in totals(
                period_rows(transactions(raw, reference_scope, qualifying=False), "q1")
            ).items()
        }
    )
    for metric in ("revenue", "orders", "customers", "aov"):
        before, after = totals(q4)[metric], totals(q1)[metric]
        before = None if before is None else Decimal(before)
        after = None if after is None else Decimal(after)
        result[f"change.{metric}.absolute"] = (
            None if before is None or after is None else after - before
        )
        result[f"change.{metric}.percent"] = (
            None if not before or after is None else (after - before) / before * 100
        )
    by_product: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in q1:
        by_product[row["product_id"]].append(row)
    ranking_ids: dict[str, list[int]] = {}
    for metric in ("revenue", "customers"):
        ordered = sorted(by_product, key=lambda key: (-metric_value(by_product[key], metric), key))
        ranking_ids[metric] = ordered[:5]
        result[f"rank.{metric}.count"] = len(ordered[:5])
        result[f"ranking.{metric}.count"] = len(ordered)
        for rank, key in enumerate(ordered, 1):
            result[f"ranking.{metric}.{rank}.product_id"] = key
            result[f"ranking.{metric}.{rank}.product_name"] = by_product[key][0]["product_name"]
            result[f"ranking.{metric}.{rank}.{metric}"] = totals(by_product[key])[metric]
        for rank, key in enumerate(ordered[:5], 1):
            result[f"rank.{metric}.{rank}.product_id"] = key
            result[f"rank.{metric}.{rank}.product_name"] = by_product[key][0]["product_name"]
            result[f"rank.{metric}.{rank}.{metric}"] = totals(by_product[key])[metric]
    overlap = sorted(set(ranking_ids["revenue"]) & set(ranking_ids["customers"]))
    result["overlap.count"] = len(overlap)
    result["overlap.product_ids"] = ", ".join(map(str, overlap)) or "none"
    for index, product_id in enumerate(overlap, 1):
        result[f"overlap.{index}.product_id"] = product_id
    categories = {row["category"] for row in q1 + q4}
    before_cat = {
        category: metric_value([r for r in q4 if r["category"] == category], "revenue")
        for category in categories
    }
    after_cat = {
        category: metric_value([r for r in q1 if r["category"] == category], "revenue")
        for category in categories
    }
    changes = {category: after_cat[category] - before_cat[category] for category in categories}
    ordered_cats = sorted(categories, key=lambda category: (-abs(changes[category]), category))
    for rank, category in enumerate(ordered_cats, 1):
        result[f"category.{rank}.name"] = category
        result[f"category.{rank}.before"] = before_cat[category]
        result[f"category.{rank}.after"] = after_cat[category]
        result[f"category.{rank}.change"] = changes[category]
    result["category.other.change"] = sum((changes[c] for c in ordered_cats[3:]), Decimal(0))
    result["category.other_after_two.change"] = sum(
        (changes[c] for c in ordered_cats[2:]), Decimal(0)
    )
    result["category.total.change"] = sum(changes.values(), Decimal(0))
    brands = SCOPES[reference_scope]
    unsold = [
        p
        for p in raw["products"]
        if (brands is None or p["brand"] in brands) and p["product_id"] not in by_product
    ]
    result["q1.unsold.count"] = len(unsold)
    result["q1.unsold.names"] = ", ".join(
        p["product_name"] for p in sorted(unsold, key=lambda p: p["product_id"])
    )
    earlier = {r["user_id"] for r in rows if r["at"] < instant("2026-01-01")}
    q1_users = {r["user_id"] for r in q1}
    result["q1.new_customers"] = len(q1_users - earlier)
    result["q1.returning_customers"] = len(q1_users & earlier)
    for key, as_of in (("start", instant("2026-01-01")), ("end", instant("2026-04-01"))):
        history = [r for r in rows if r["at"] < as_of]
        last = {
            user: max(r["at"] for r in history if r["user_id"] == user)
            for user in {r["user_id"] for r in history}
        }
        inactive = sum(date < as_of - timedelta(days=90) for date in last.values())
        result[f"inactivity.{key}.eligible"] = len(last)
        result[f"inactivity.{key}.inactive"] = inactive
        result[f"inactivity.{key}.percent"] = Decimal(inactive) / len(last) * 100 if last else None
    return {key: None if value is None else str(value) for key, value in result.items()}
