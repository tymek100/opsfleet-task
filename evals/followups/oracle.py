"""Independent raw-table revenue check for the changed-period follow-up (opt-in)."""

import argparse
import json
from pathlib import Path

from google.cloud import bigquery

from retail_agent.config import Settings

SQL = """
SELECT i.product_id, ROUND(SUM(i.sale_price), 2) AS revenue
FROM `bigquery-public-data.thelook_ecommerce.order_items` AS i
WHERE i.product_id IN UNNEST(@products)
  AND i.created_at >= TIMESTAMP('2025-07-01')
  AND i.created_at < TIMESTAMP('2025-10-01')
  AND i.status NOT IN ('Cancelled', 'Returned')
  AND EXISTS (
    SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.products` AS p
    WHERE p.id = i.product_id AND p.brand = 'Calvin Klein'
  )
  AND EXISTS (
    SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.orders` AS o
    WHERE o.order_id = i.order_id AND o.user_id = i.user_id
      AND o.status NOT IN ('Cancelled', 'Returned')
  )
GROUP BY i.product_id
"""


def verify(root):
    previous = json.loads((root / "09.json").read_text())["answer"]
    answer = json.loads((root / "10.json").read_text())["answer"]
    ids = [r["product_id"] for r in previous["view"]["rows"]]
    settings = Settings.load()
    client = bigquery.Client(project=settings.google_cloud_project)
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("products", "INT64", ids)],
        maximum_bytes_billed=100_000_000,
    )
    dry = bigquery.QueryJobConfig(
        query_parameters=config.query_parameters, dry_run=True, use_query_cache=False
    )
    dry_job = client.query(SQL, job_config=dry)
    assert dry_job.total_bytes_processed <= 100_000_000
    job = client.query(SQL, job_config=config)
    expected = {r["product_id"]: r["revenue"] for r in job.result(timeout=60)}
    actual = {r["product_id"]: r["revenue"] for e in answer["evidence"] for r in e["rows"]}
    result = {
        "passed": actual == expected,
        "product_ids": ids,
        "expected": expected,
        "actual": actual,
        "bytes_processed": job.total_bytes_processed,
        "method": "Independent EXISTS-based raw-table SQL; no production compiler",
    }
    (root / "oracle.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    assert result["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    verify(args.results)
