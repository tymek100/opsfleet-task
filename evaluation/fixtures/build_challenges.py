"""Derive new challenge fixtures without rewriting frozen base variants."""

from __future__ import annotations

import json
from copy import deepcopy

from evaluation.oracles.retail import fixture_file, load_fixture, render_sql


def build_variants() -> dict[str, dict]:
    base = load_fixture("retail_v1")
    nullable = deepcopy(base)
    next_item = max(row["item_id"] for row in nullable["items"]) + 1
    for offset, (price, item_status, order_status) in enumerate(
        [(None, "Complete", "Complete"), ("10000", None, "Complete"), ("20000", "Complete", None)]
    ):
        order_id, user_id = 901 + offset, 50 + offset
        nullable["orders"].append(
            {"order_id": order_id, "user_id": user_id, "order_status": order_status}
        )
        nullable["items"].append(
            {
                "item_id": next_item + offset,
                "order_id": order_id,
                "user_id": user_id,
                "product_id": 1003,
                "sale_price": price,
                "purchased_at": "2026-03-15T12:00:00Z",
                "item_status": item_status,
            }
        )

    balanced = deepcopy(base)
    target = next(
        row for row in balanced["items"] if row["order_id"] == 101 and row["product_id"] == 1001
    )
    target["sale_price"] = "22"  # Reduce Q1 revenue by 228, leaving offsetting category changes.

    paged = deepcopy(base)
    next_item = max(row["item_id"] for row in paged["items"]) + 1
    prices = [
        "101",
        "97",
        "89",
        "83",
        "79",
        "73",
        "67",
        "61",
        "59",
        "53",
        "47",
        "43",
        "37",
        "0.13",
        "0.29",
        "0.47",
        "0.73",
        "1.07",
    ]
    for offset, price in enumerate(prices):
        product_id, order_id, user_id = 3001 + offset, 1001 + offset, 101 + offset
        paged["products"].append(
            {
                "product_id": product_id,
                "brand": "Calvin Klein",
                "category": "Accessories",
                "product_name": f"Cobalt Sample {offset + 1:02d}",
            }
        )
        paged["orders"].append(
            {"order_id": order_id, "user_id": user_id, "order_status": "Complete"}
        )
        paged["items"].append(
            {
                "item_id": next_item + offset,
                "order_id": order_id,
                "user_id": user_id,
                "product_id": product_id,
                "sale_price": price,
                "purchased_at": "2026-02-15T12:00:00Z",
                "item_status": "Complete",
            }
        )
    return {"nullable_v1": nullable, "zero_net_v1": balanced, "paged_results_v1": paged}


def main() -> None:
    for name, raw in build_variants().items():
        fixture_file(name).write_text(json.dumps(raw, indent=2) + "\n")
        fixture_file(name, ".sql").write_text(render_sql(raw))


if __name__ == "__main__":
    main()
