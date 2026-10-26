"""Independent aggregate SQL for the documented quick-start data (opt-in live)."""

import argparse
import json
from pathlib import Path

from google.cloud import bigquery

from retail_agent.config import Settings

BASE = """
FROM `bigquery-public-data.thelook_ecommerce.order_items` AS i
WHERE i.created_at >= TIMESTAMP(@start) AND i.created_at < TIMESTAMP(@end)
AND i.status NOT IN ('Cancelled', 'Returned')
AND EXISTS (SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.orders` AS o
            WHERE o.order_id=i.order_id AND o.user_id=i.user_id
              AND o.status NOT IN ('Cancelled', 'Returned'))
AND EXISTS (SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.products` AS p
            WHERE p.id=i.product_id AND p.brand='Calvin Klein')
"""
MEASURES = "ROUND(SUM(i.sale_price),2) revenue, COUNT(*) units, COUNT(DISTINCT i.order_id) orders, COUNT(DISTINCT i.user_id) customers"


def run(root):
    client = bigquery.Client(project=Settings.load().google_cloud_project)
    checks = []
    reference_rows = {}
    for scenario, expression, key, start, end in [
        ("products", "i.product_id", "product_id", "2025-04-01", "2025-07-01"),
        ("customers", "i.user_id", "user_id", "2025-01-01", "2026-01-01"),
        ("months", "FORMAT_TIMESTAMP('%Y-%m',i.created_at)", "month", "2025-01-01", "2026-01-01"),
        ("report", "'all'", "total", "2025-04-01", "2025-07-01"),
    ]:
        sql = f"SELECT {expression} AS {key}, {MEASURES} {BASE} GROUP BY {key}"
        params = [
            bigquery.ScalarQueryParameter("start", "STRING", start),
            bigquery.ScalarQueryParameter("end", "STRING", end),
        ]
        config = bigquery.QueryJobConfig(query_parameters=params, maximum_bytes_billed=100_000_000)
        dry = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=params, dry_run=True, use_query_cache=False
            ),
        )
        assert dry.total_bytes_processed <= 100_000_000
        rows = [dict(r) for r in client.query(sql, job_config=config).result(timeout=60)]
        reference_rows[scenario] = rows
        answer = json.loads((root / f"{scenario}-1.json").read_text())["answer"]
        evidence = answer["evidence"]
        if scenario == "report":
            evidence = [e for e in evidence if e["request"]["dimension"] == "total"]
        for item in evidence:
            rank = item["request"]["rank_by"]
            expected = (
                sorted(rows, key=lambda r: (-r[rank], r[key]))[: item["request"]["limit"]]
                if scenario not in ("report", "months")
                else sorted(rows, key=lambda r: r[key])
            )
            actual = item["rows"]
            assert len(actual) == len(expected), (scenario, len(actual), len(expected))
            for a, b in zip(actual, expected, strict=True):
                for field in ["revenue", "units", "orders", "customers"] + (
                    [] if scenario == "report" else [key]
                ):
                    assert a[field] == b[field], (scenario, field, a[field], b[field])
            checks.append(
                {"scenario": scenario, "evidence": item["id"], "passed": True, "rows": len(actual)}
            )
    report = json.loads((root / "report-1.json").read_text())["answer"]
    for item in report["evidence"]:
        dimension = item["request"]["dimension"]
        if dimension == "total":
            continue
        if dimension == "month":
            key = "month"
            expected = sorted(
                (r for r in reference_rows["months"] if "2025-04" <= r[key] <= "2025-06"),
                key=lambda r: r[key],
            )
        elif dimension == "product":
            key = "product_id"
            expected = sorted(reference_rows["products"], key=lambda r: (-r["revenue"], r[key]))[:5]
        else:
            raise AssertionError(f"Unexpected report dimension: {dimension}")
        assert len(item["rows"]) == len(expected)
        for actual, wanted in zip(item["rows"], expected, strict=True):
            for field in (key, "revenue", "orders", "customers", "units"):
                assert actual[field] == wanted[field], (dimension, field)
        checks.append(
            {"scenario": "report", "evidence": item["id"], "passed": True, "rows": len(expected)}
        )
    (root / "oracle.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "method": "Independent EXISTS-based raw-table SQL; no production compiler",
            },
            indent=2,
        )
    )
    print(json.dumps(checks))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    run(args.results)
