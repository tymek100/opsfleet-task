"""Independent read-only reference capture for authored live-data conversations.

This module does not use the application's query compiler or synthetic oracles.
It captures authorized public/sample rows and computes references with Decimal/sets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

BRANDS = ("Calvin Klein", "Levi's")
PERIODS = {
    "q4_2025": ("2025-10-01", "2026-01-01"),
    "q1_2026": ("2026-01-01", "2026-04-01"),
    "q2_2026": ("2026-04-01", "2026-07-01"),
    "january_2026": ("2026-01-01", "2026-02-01"),
    "february_2026": ("2026-02-01", "2026-03-01"),
    "march_2026": ("2026-03-01", "2026-04-01"),
    "q4_2039": ("2039-10-01", "2040-01-01"),
    "q1_2040": ("2040-01-01", "2040-04-01"),
}
EXCLUDED = {"Cancelled", "Returned"}


def instant(value: str | datetime) -> datetime:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def number(value) -> Decimal | None:
    if value is None:
        return None
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite reference price")
    return result


def qualifying(row: dict) -> bool:
    return all(
        row.get(key) is not None and row[key] not in EXCLUDED
        for key in ("item_status", "order_status")
    )


def during(rows: list[dict], start: str, end: str) -> list[dict]:
    left, right = instant(start), instant(end)
    return [row for row in rows if left <= instant(row["purchased_at"]) < right]


def revenue(rows: list[dict]) -> Decimal | None:
    values = [value for row in rows if (value := number(row["sale_price"])) is not None]
    return sum(values, Decimal(0)) if values else None


def ratio(numerator, denominator) -> Decimal | None:
    if numerator is None or denominator in (None, 0):
        return None
    return Decimal(numerator) / Decimal(denominator)


def totals(rows: list[dict]) -> dict:
    amount = revenue(rows)
    customers = {row["user_id"] for row in rows if row["user_id"] is not None}
    orders = {row["order_id"] for row in rows if row["order_id"] is not None}
    priced = sum(row["sale_price"] is not None for row in rows)
    return {
        "revenue": amount,
        "customers": len(customers),
        "orders": len(orders),
        "units": len(rows),
        "priced_units": priced,
        "aov": ratio(amount, len(orders)),
        "revenue_per_customer": ratio(amount, len(customers)),
        "average_realized_unit_price": ratio(amount, priced),
        "orders_per_customer": ratio(len(orders), len(customers)),
    }


def changes(previous: dict, current: dict) -> dict:
    result = {}
    for metric in ("revenue", "customers", "orders", "units", "aov", "average_realized_unit_price"):
        left, right = previous[metric], current[metric]
        difference = None if left is None or right is None else Decimal(right) - Decimal(left)
        relative = ratio(difference, left)
        result[metric] = {
            "q4_2025": left,
            "q1_2026": right,
            "absolute_change": difference,
            "percent_change": None if relative is None else relative * 100,
        }
    return result


def grouped(rows: list[dict], key: str) -> dict:
    result = defaultdict(list)
    for row in rows:
        result[row[key]].append(row)
    return dict(result)


def ranked_products(rows: list[dict], metric: str) -> list[dict]:
    products = [
        {"product_id": product, "product_name": group[0]["product_name"], **totals(group)}
        for product, group in grouped(rows, "product_id").items()
    ]
    return sorted(
        products, key=lambda row: (row[metric] is None, -(row[metric] or 0), row["product_id"])
    )


def categories(previous: list[dict], current: list[dict]) -> dict:
    before, after = grouped(previous, "category"), grouped(current, "category")
    rows = []
    for category in before.keys() | after.keys():
        left, right = (
            revenue(before.get(category, [])) or Decimal(0),
            revenue(after.get(category, [])) or Decimal(0),
        )
        rows.append(
            {"category": category, "q4_revenue": left, "q1_revenue": right, "change": right - left}
        )
    ordered = sorted(rows, key=lambda row: (-abs(row["change"]), str(row["category"])))
    return {
        "all_by_absolute_change": ordered,
        "top_three_by_absolute_change": ordered[:3],
        "other_after_top_three": sum((row["change"] for row in ordered[3:]), Decimal(0)),
        "other_after_top_two": sum((row["change"] for row in ordered[2:]), Decimal(0)),
        "total_change": sum((row["change"] for row in rows), Decimal(0)),
    }


def customer_cohorts(history: list[dict], q4: list[dict], q1: list[dict], q2: list[dict]) -> dict:
    first = {
        customer: min(instant(row["purchased_at"]) for row in rows)
        for customer, rows in grouped(history, "user_id").items()
    }
    q4_ids, q1_ids, q2_ids = ({row["user_id"] for row in rows} for rows in (q4, q1, q2))
    new = {
        customer
        for customer in q1_ids
        if instant("2026-01-01") <= first[customer] < instant("2026-04-01")
    }
    returning = q1_ids - new
    repeated = {
        customer
        for customer, rows in grouped(q1, "user_id").items()
        if len({row["order_id"] for row in rows}) >= 2
    }
    return {
        "q1_first_scoped_purchase_customers": sorted(new),
        "q1_first_scoped_purchase_count": len(new),
        "q1_first_scoped_purchase_revenue": revenue([row for row in q1 if row["user_id"] in new]),
        "q1_preexisting_customers": sorted(returning),
        "q1_preexisting_count": len(returning),
        "q1_preexisting_revenue": revenue([row for row in q1 if row["user_id"] in returning]),
        "q1_repeat_order_customers": sorted(repeated),
        "q1_repeat_order_count": len(repeated),
        "q1_repeat_customer_share": ratio(len(repeated), len(q1_ids)),
        "q1_repeat_order_group": totals([row for row in q1 if row["user_id"] in repeated]),
        "q1_single_order_group": totals([row for row in q1 if row["user_id"] not in repeated]),
        "q4_customers_returning_q1": sorted(q4_ids & q1_ids),
        "q4_to_q1_retention_count": len(q4_ids & q1_ids),
        "q4_to_q1_retention_denominator": len(q4_ids),
        "q4_to_q1_retention_rate": ratio(len(q4_ids & q1_ids), len(q4_ids)),
        "q1_customers_not_in_q4": len(q1_ids - q4_ids),
        "q1_new_retained_q2_count": len(new & q2_ids),
        "q1_new_retained_q2_rate": ratio(len(new & q2_ids), len(new)),
    }


def category_customer_overlap(rows: list[dict]) -> dict:
    metrics = [
        {"category": category, **totals(items)}
        for category, items in grouped(rows, "category").items()
    ]
    leaders = sorted(metrics, key=lambda row: (-row["customers"], str(row["category"])))[:3]
    selected = {row["category"] for row in leaders}
    memberships = defaultdict(set)
    for row in rows:
        if row["category"] in selected:
            memberships[row["user_id"]].add(row["category"])
    return {
        "all_categories_by_revenue": sorted(
            metrics, key=lambda row: (-(row["revenue"] or 0), str(row["category"]))
        ),
        "top_three_by_customers": leaders,
        "selected_union_customers": len(memberships),
        "selected_multiple_category_customers": sum(
            len(value) > 1 for value in memberships.values()
        ),
    }


def concentration(products: list[dict], total: Decimal | None) -> dict:
    accumulated = Decimal(0)
    reached = None
    for index, product in enumerate(products, 1):
        accumulated += product["revenue"] or Decimal(0)
        if total is not None and total > 0 and accumulated >= total * Decimal("0.8"):
            reached = {"count": index, "revenue": accumulated, "share": accumulated / total}
            break
    return {"threshold": "0.8", "minimum_prefix": reached}


def summarize(
    transactions: list[dict], products: list[dict], states: list[dict], brands=BRANDS
) -> dict:
    if len({row["item_id"] for row in transactions}) != len(transactions):
        raise ValueError("Duplicate joined item IDs make the reference grain ambiguous")
    if any(row["brand"] not in brands for row in [*transactions, *products, *states]):
        raise ValueError("Reference capture contains an unauthorized brand")
    result = {}
    for brand in brands:
        history = [row for row in transactions if row["brand"] == brand and qualifying(row)]
        all_statuses = [row for row in transactions if row["brand"] == brand]
        periods = {key: during(history, *dates) for key, dates in PERIODS.items()}
        period_totals = {key: totals(rows) for key, rows in periods.items()}
        q4, q1, q2 = (periods[key] for key in ("q4_2025", "q1_2026", "q2_2026"))
        rankings = {metric: ranked_products(q1, metric) for metric in ("revenue", "customers")}
        top_revenue, top_customers = (rankings[metric][:5] for metric in ("revenue", "customers"))
        sold = {row["product_id"] for row in q1}
        catalog = [row for row in products if row["brand"] == brand]
        q1_all = during(all_statuses, *PERIODS["q1_2026"])
        geography = [row for row in states if row["brand"] == brand]
        q1_revenue = revenue(q1)
        result[brand] = {
            "qualifying": period_totals,
            "q4_to_q1_changes": changes(period_totals["q4_2025"], period_totals["q1_2026"]),
            "q1_all_statuses": totals(q1_all),
            "q1_complete_only": totals(
                [row for row in q1_all if row["item_status"] == row["order_status"] == "Complete"]
            ),
            "q1_excluded_statuses": totals([row for row in q1_all if not qualifying(row)]),
            "q1_item_order_status_breakdown": [
                {"item_status": item, "order_status": order, **totals(rows)}
                for (item, order), rows in sorted(
                    grouped(
                        [
                            {**row, "statuses": (row["item_status"], row["order_status"])}
                            for row in q1_all
                        ],
                        "statuses",
                    ).items(),
                    key=lambda pair: str(pair[0]),
                )
            ],
            "top_five_by_revenue": top_revenue,
            "top_five_by_customers": top_customers,
            "top_five_overlap_ids": sorted(
                {row["product_id"] for row in top_revenue}
                & {row["product_id"] for row in top_customers}
            ),
            "all_product_metrics_by_revenue": rankings["revenue"],
            "revenue_concentration_80_percent": concentration(rankings["revenue"], revenue(q1)),
            "category_metrics_and_overlap": category_customer_overlap(q1),
            "monthly_customer_sum": sum(
                period_totals[key]["customers"]
                for key in ("january_2026", "february_2026", "march_2026")
            ),
            "hypothetical_eur_at_0_92": None
            if q1_revenue is None
            else q1_revenue * Decimal("0.92"),
            "top_five_revenue_share": ratio(
                sum((row["revenue"] or Decimal(0) for row in top_revenue), Decimal(0)), revenue(q1)
            ),
            "category_contributions": categories(q4, q1),
            "customer_cohorts": customer_cohorts(history, q4, q1, q2),
            "unsold_q1_catalog_products": sorted(
                [row for row in catalog if row["product_id"] not in sold],
                key=lambda row: row["product_id"],
            ),
            "q1_visible_state_groups": geography,
            "q1_visible_state_revenue": sum(
                (number(row["revenue"]) or Decimal(0) for row in geography), Decimal(0)
            ),
        }
    return result


def queries(dataset: str) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_]+", dataset):
        raise ValueError("Invalid trusted source dataset")
    joins = f"""FROM `{dataset}.order_items` i
JOIN `{dataset}.orders` o ON o.order_id = i.order_id AND o.user_id = i.user_id
JOIN `{dataset}.products` p ON p.id = i.product_id"""
    return {
        "transactions": f"""SELECT i.id AS item_id, i.order_id, i.user_id, i.product_id,
i.sale_price, i.created_at AS purchased_at, p.brand, p.category,
p.name AS product_name, i.status AS item_status, o.status AS order_status
{joins}
WHERE p.brand IN UNNEST(@brands)
ORDER BY p.brand, i.id""",
        "products": f"""SELECT id AS product_id, name AS product_name, brand, category
FROM `{dataset}.products` WHERE brand IN UNNEST(@brands) ORDER BY brand, id""",
        "states": f"""SELECT p.brand, u.state, COUNT(DISTINCT i.user_id) AS customers,
COUNT(DISTINCT i.order_id) AS orders, SUM(i.sale_price) AS revenue
{joins}
JOIN `{dataset}.users` u ON u.id = i.user_id
WHERE p.brand IN UNNEST(@brands)
AND i.status NOT IN ('Cancelled', 'Returned') AND o.status NOT IN ('Cancelled', 'Returned')
AND i.created_at >= TIMESTAMP '2026-01-01' AND i.created_at < TIMESTAMP '2026-04-01'
GROUP BY p.brand, u.state HAVING COUNT(DISTINCT i.user_id) >= 5
ORDER BY p.brand, revenue DESC, u.state""",
    }


def serializable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    raise TypeError(f"Unsupported reference value: {type(value).__name__}")


def save(path: Path, value) -> str:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, default=serializable, allow_nan=False)
        + "\n"
    )
    path.write_text(payload)
    return hashlib.sha256(payload.encode()).hexdigest()


def capture(
    settings, directory: Path, *, brands=BRANDS, max_query_bytes=100_000_000, client: Any = None
) -> dict:
    from google.cloud import bigquery

    if not brands or len(set(brands)) != len(brands) or max_query_bytes <= 0:
        raise ValueError("Distinct brands and a positive query allowance are required")
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "source": "configured BigQuery sample data; not authored fixture rows",
        "source_dataset": settings.warehouse_source_dataset,
        "brands": list(brands),
        "query_byte_limit": max_query_bytes,
        "reference_implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "point_in_time_consistent": False,
        "limitation": "Sequential read-only queries observe the source at their execution times. Local captured files are immutable inputs, not a transactionally frozen warehouse.",
        "human_reviewed": False,
        "jobs": {},
        "files_sha256": {},
    }
    save(directory / "manifest.json", manifest)
    own_client = client is None
    client = client or bigquery.Client(project=settings.google_cloud_project or None)
    captured = {}
    try:
        for name, sql in queries(settings.warehouse_source_dataset).items():
            deadline = time.monotonic() + 60

            def remaining(deadline=deadline):
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("Reference query exceeded its 60-second deadline")
                return left

            parameters = [bigquery.ArrayQueryParameter("brands", "STRING", list(brands))]
            dry = client.query(
                sql,
                job_config=bigquery.QueryJobConfig(
                    dry_run=True, use_query_cache=False, query_parameters=parameters
                ),
                timeout=remaining(),
                retry=None,
            )
            estimated = int(dry.total_bytes_processed or 0)
            if estimated > max_query_bytes:
                raise ValueError(
                    f"Reference {name} requires {estimated} bytes, exceeding {max_query_bytes}"
                )
            job = client.query(
                sql,
                job_config=bigquery.QueryJobConfig(
                    maximum_bytes_billed=max_query_bytes,
                    query_parameters=parameters,
                    use_query_cache=True,
                ),
                job_id="retail_reference_" + uuid4().hex,
                timeout=remaining(),
                retry=None,
                job_retry=None,
            )
            try:
                result = job.result(timeout=remaining(), retry=None, job_retry=None, page_size=1000)
                rows = []
                for row in result:
                    remaining()
                    rows.append(dict(row))
            except BaseException:
                with suppress(Exception):
                    job.cancel(timeout=2, retry=None)
                raise
            if result.total_rows is not None and len(rows) != result.total_rows:
                raise ValueError("Incomplete reference query result")
            if name == "states" and any(row["customers"] < 5 for row in rows):
                raise ValueError("State reference violates aggregate privacy threshold")
            captured[name] = rows
            manifest["files_sha256"][name + ".json"] = save(directory / (name + ".json"), rows)
            manifest["jobs"][name] = {
                "job_id": job.job_id,
                "observed_at": datetime.now(UTC).isoformat(),
                "rows": len(rows),
                "estimated_bytes": estimated,
                "processed_bytes": int(job.total_bytes_processed or 0),
                "billed_bytes": int(job.total_bytes_billed or 0),
                "sql": sql,
            }
            save(directory / "manifest.json", manifest)
            print(f"Reference {name}: {len(rows)} rows captured", flush=True)
        summary = summarize(
            captured["transactions"], captured["products"], captured["states"], brands
        )
        manifest["files_sha256"]["summary.json"] = save(directory / "summary.json", summary)
        manifest["status"] = "completed"
        manifest["ended_at"] = datetime.now(UTC).isoformat()
        save(directory / "manifest.json", manifest)
        return manifest
    except BaseException as exc:
        manifest.update(status="incomplete", error_type=type(exc).__name__)
        save(directory / "manifest.json", manifest)
        raise
    finally:
        if own_client:
            client.close()


def main() -> None:
    from retail_agent.config import Settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path(".artifacts/manual-reference"))
    parser.add_argument("--max-query-bytes", type=int, default=100_000_000)
    parser.add_argument("--brands", nargs="+", default=list(BRANDS))
    args = parser.parse_args()
    directory = args.output_root / f"reference-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    try:
        capture(
            Settings.load(),
            directory,
            brands=tuple(args.brands),
            max_query_bytes=args.max_query_bytes,
        )
    except Exception as exc:
        print(
            f"Reference capture incomplete ({type(exc).__name__}); artifacts: {directory}",
            flush=True,
        )
        raise SystemExit(2) from None
    print(f"Reference snapshot: {directory}", flush=True)


if __name__ == "__main__":
    main()
