"""Independent BigQuery oracle for reviewer scenarios, including independently calculated inactivity."""

import argparse
import json
import math
from pathlib import Path

from google.cloud import bigquery

from retail_agent.config import Settings
from retail_agent.models import Analysis


def same_rows(actual, expected):
    def equal(left, right):
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return math.isclose(left, right, abs_tol=0.011, rel_tol=1e-8)
        return left == right

    actual = [{k: v for k, v in row.items() if k != "latest_purchase"} for row in actual]
    return len(actual) == len(expected) and all(
        a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
        for a, b in zip(actual, expected, strict=True)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args()
    if (args.directory / "oracle-results.json").exists():
        raise SystemExit(
            "Oracle results already exist; retain this attempt and use a new run directory."
        )
    settings = Settings.load()
    client = bigquery.Client(project=settings.google_cloud_project, location="US")
    results = []
    try:
        for path in sorted(args.directory.glob("[0-9][0-9]-*.json")):
            case = json.loads(path.read_text())
            brand = {"alice": "Calvin Klein", "bob": "Levi's"}[case["user"]]
            for evidence in case.get("answer", {}).get("evidence", []):
                request = Analysis.model_validate(evidence["request"])
                if request.dimension not in (
                    "total",
                    "month",
                    "product",
                ):
                    raise SystemExit("Unexpected analytical surface for this oracle.")
                if request.brands and request.brands != [brand]:
                    raise SystemExit("Unexpected scope; never broaden the independent oracle.")
                if request.customer_id or request.product_ids:
                    raise SystemExit("Unexpected filters for the published ten-case suite.")
                grouping = {
                    "total": ("'all' AS label", "", request.rank_by + " DESC, label"),
                    "month": (
                        "FORMAT_TIMESTAMP('%Y-%m', i.created_at, 'UTC') AS month",
                        " GROUP BY month",
                        "month",
                    ),
                    "product": (
                        "i.product_id, p.name AS product_name",
                        " GROUP BY i.product_id,p.name",
                        request.rank_by + " DESC, product_id, product_name",
                    ),
                }
                select, group, order = grouping[request.dimension]
                status = (
                    "= 'Complete'" if request.completed_only else "NOT IN ('Returned', 'Cancelled')"
                )
                # Independently authored SQL; does not call compile_query or execution_requests.
                sql = f"""SELECT {select}, ROUND(SUM(i.sale_price),2) revenue,
COUNT(i.id) units, COUNT(DISTINCT i.order_id) orders, COUNT(DISTINCT i.user_id) customers
FROM `bigquery-public-data.thelook_ecommerce.order_items` i
JOIN `bigquery-public-data.thelook_ecommerce.products` p ON p.id=i.product_id
WHERE p.brand=@brand AND i.status {status}
AND EXISTS (SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.orders` o
WHERE o.order_id=i.order_id AND o.user_id=i.user_id AND o.status {status})
AND i.created_at>=TIMESTAMP(@start) AND i.created_at<TIMESTAMP(@end)
{group} ORDER BY {order} LIMIT @row_limit"""
                if request.kind == "churn":
                    if request.dimension != "total":
                        raise SystemExit("This independent oracle supports total inactivity only")
                    sql = f"""WITH purchases AS (
SELECT i.user_id, DATE(i.created_at) AS day
FROM `bigquery-public-data.thelook_ecommerce.order_items` i
JOIN `bigquery-public-data.thelook_ecommerce.products` p ON p.id=i.product_id
WHERE p.brand=@brand AND i.status {status}
AND EXISTS (SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.orders` o
WHERE o.order_id=i.order_id AND o.user_id=i.user_id AND o.status {status})
), snapshots AS (SELECT @start AS boundary UNION ALL SELECT @end),
seasoned AS (
SELECT DISTINCT s.boundary, p.user_id FROM snapshots s JOIN purchases p
ON p.day < DATE_SUB(s.boundary, INTERVAL @inactivity_days DAY)
), classified AS (
SELECT boundary, user_id, NOT EXISTS (
SELECT 1 FROM purchases p WHERE p.user_id=s.user_id
AND p.day >= DATE_SUB(s.boundary, INTERVAL @inactivity_days DAY)
AND p.day < s.boundary) AS inactive FROM seasoned s
)
SELECT CAST(boundary AS STRING) AS period, 'all' AS cohort,
COUNT(*) AS eligible_customers, COUNTIF(inactive) AS inactive_customers,
COUNTIF(inactive)/COUNT(*) AS inactivity_share
FROM classified GROUP BY boundary ORDER BY boundary"""
                config = bigquery.QueryJobConfig(
                    maximum_bytes_billed=100_000_000,
                    query_parameters=[
                        bigquery.ScalarQueryParameter("brand", "STRING", brand),
                        bigquery.ScalarQueryParameter("start", "DATE", request.start),
                        bigquery.ScalarQueryParameter("end", "DATE", request.end),
                        bigquery.ScalarQueryParameter("row_limit", "INT64", request.limit),
                        bigquery.ScalarQueryParameter(
                            "inactivity_days", "INT64", request.inactivity_days
                        ),
                    ],
                )
                job = client.query(sql, job_config=config)
                rows = [dict(row) for row in job.result(timeout=60)]
                ok = same_rows(evidence["rows"], rows)
                if request.kind == "churn" and ok:
                    ok = all(
                        math.isclose(a["inactivity_share"], b["inactivity_share"], abs_tol=1e-10)
                        for a, b in zip(evidence["rows"], rows, strict=True)
                    )
                results.append(
                    {
                        "case": case["id"],
                        "evidence": evidence["id"],
                        "pass_": ok,
                        "oracle_rows": rows,
                        "job_id": job.job_id,
                        "bytes": job.total_bytes_processed,
                        "sql": sql,
                    }
                )
                results[-1]["pass"] = results[-1].pop("pass_")
                (args.directory / "oracle-results.json").write_text(
                    json.dumps(results, indent=2) + "\n"
                )
                print(case["id"], evidence["id"], ok, flush=True)
    finally:
        client.close()
    raise SystemExit(not results or not all(r["pass"] for r in results))


if __name__ == "__main__":
    main()
