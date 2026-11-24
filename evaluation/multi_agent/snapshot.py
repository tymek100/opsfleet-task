"""Optional bounded, independently captured BigQuery raw rows at one table version."""

import re
from datetime import UTC, datetime

from google.cloud import bigquery

from .oracle import Snapshot


def capture(settings, as_of):
    source = settings.warehouse_source_dataset
    if not re.fullmatch(r"[a-zA-Z0-9_-]+\.[a-zA-Z0-9_]+", source):
        raise ValueError("Invalid warehouse dataset")
    version = datetime.now(UTC)
    client = bigquery.Client(project=settings.google_cloud_project or None)
    cfg = bigquery.QueryJobConfig(
        maximum_bytes_billed=500_000_000,
        query_parameters=[bigquery.ScalarQueryParameter("snapshot", "TIMESTAMP", version)],
    )

    def table(name, alias):
        return f"`{source}.{name}` AS {alias} FOR SYSTEM_TIME AS OF @snapshot"

    scope = "p.brand IN ('Calvin Klein', 'Levi\\'s')"
    queries = {
        "products": f"SELECT p.id,p.name,p.brand,p.category,p.distribution_center_id FROM {table('products', 'p')} WHERE {scope}",
        "inventory_items": f"SELECT i.id,i.product_id,i.created_at,i.sold_at,i.cost,i.product_distribution_center_id FROM {table('inventory_items', 'i')} JOIN {table('products', 'p')} ON p.id=i.product_id WHERE {scope}",
        "distribution_centers": f"SELECT d.id,d.name,d.latitude,d.longitude FROM {table('distribution_centers', 'd')}",
        "order_items": f"SELECT i.id,i.order_id,i.user_id,i.product_id,i.sale_price,i.created_at,i.status FROM {table('order_items', 'i')} JOIN {table('products', 'p')} ON p.id=i.product_id WHERE {scope}",
        "orders": f"SELECT DISTINCT o.order_id,o.user_id,o.status FROM {table('orders', 'o')} JOIN {table('order_items', 'i')} ON i.order_id=o.order_id JOIN {table('products', 'p')} ON p.id=i.product_id WHERE {scope}",
    }
    raw = {}
    billed_bytes = 0
    billing = []
    for name, sql in queries.items():
        job = client.query(sql, job_config=cfg)
        result = job.result(timeout=45)
        billed = job.total_bytes_billed
        if billed is None:
            billed = 500_000_000
            billing.append(
                {
                    "table": name,
                    "bytes": billed,
                    "basis": "configured cap; billed usage unavailable",
                }
            )
        else:
            billing.append({"table": name, "bytes": billed, "basis": "reported billed bytes"})
        billed_bytes += billed
        if result.total_rows is None:
            raise ValueError(f"Reference table {name} has unknown row count; capture refused")
        if result.total_rows > 100_000:
            raise ValueError(
                f"Reference table {name} exceeded 100000 rows; no truncation permitted"
            )
        raw[name] = [
            {
                k: v.isoformat()
                if isinstance(v, datetime)
                else str(v)
                if k in {"cost", "sale_price"} and v is not None
                else v
                for k, v in dict(row).items()
            }
            for row in result
        ]
        print(f"Reference {name}: {len(raw[name])} raw rows", flush=True)
    snapshot = Snapshot(raw, as_of=as_of, snapshot_at=version.isoformat())
    snapshot.capture_cost_usd = billed_bytes * settings.bigquery_usd_per_tib / 2**40
    snapshot.capture_billing = billing
    return snapshot
