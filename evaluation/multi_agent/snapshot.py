"""Optional bounded, independently captured BigQuery raw rows at one table version."""

import re
import time
from contextlib import suppress
from datetime import UTC, datetime

from google.api_core.retry import Retry
from google.cloud import bigquery

from evaluation.settings import MAX_EVALUATION_COST_USD, validate_run_budget

from .oracle import Snapshot

MAX_REFERENCE_ROWS = 1_000_000


def capture(settings, as_of, *, max_cost_usd=MAX_EVALUATION_COST_USD, deadline=None):
    validate_run_budget(max_cost_usd)
    # Five queries share the allowance; each has a server-enforced bytes cap.
    query_byte_cap = min(500_000_000, int(max_cost_usd * 2**40 / settings.bigquery_usd_per_tib / 5))
    if query_byte_cap < 1:
        raise ValueError("Insufficient budget for reference capture")
    deadline = deadline if deadline is not None else time.monotonic() + 225

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("Reference capture deadline exhausted")
        return min(45, seconds)

    remaining()
    source = settings.warehouse_source_dataset
    if not re.fullmatch(r"[a-zA-Z0-9_-]+\.[a-zA-Z0-9_]+", source):
        raise ValueError("Invalid warehouse dataset")
    version = datetime.now(UTC)
    client = bigquery.Client(project=settings.google_cloud_project or None)
    cfg = bigquery.QueryJobConfig(
        maximum_bytes_billed=query_byte_cap,
        query_parameters=[bigquery.ScalarQueryParameter("snapshot", "TIMESTAMP", version)],
    )

    def table(name, alias):
        return f"`{source}.{name}` AS {alias} FOR SYSTEM_TIME AS OF @snapshot"

    queries = {
        "products": f"SELECT p.id,p.name,p.brand,p.category,p.distribution_center_id FROM {table('products', 'p')}",
        "inventory_items": f"SELECT i.id,i.product_id,i.created_at,i.sold_at,i.cost,i.product_distribution_center_id FROM {table('inventory_items', 'i')} JOIN {table('products', 'p')} ON p.id=i.product_id",
        "distribution_centers": f"SELECT d.id,d.name,d.latitude,d.longitude FROM {table('distribution_centers', 'd')}",
        "order_items": f"SELECT i.id,i.order_id,i.user_id,i.product_id,i.sale_price,i.created_at,i.status FROM {table('order_items', 'i')} JOIN {table('products', 'p')} ON p.id=i.product_id",
        "orders": f"SELECT o.order_id,o.user_id,o.status FROM {table('orders', 'o')}",
    }
    raw = {}
    billed_bytes = 0
    billing = []
    try:
        for name, sql in queries.items():
            job = client.query(
                sql,
                job_config=cfg,
                timeout=remaining(),
                retry=Retry(predicate=lambda error: False),
                job_retry=None,
            )
            try:
                result = job.result(timeout=remaining(), retry=None, job_retry=None)
            except BaseException:
                with suppress(Exception):
                    job.cancel(timeout=2, retry=None)
                raise
            billed = job.total_bytes_billed
            if billed is None:
                billed = query_byte_cap
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
            if result.total_rows > MAX_REFERENCE_ROWS:
                raise ValueError(
                    f"Reference table {name} exceeded {MAX_REFERENCE_ROWS} rows; no truncation permitted"
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
    finally:
        client.close()
    snapshot = Snapshot(raw, as_of=as_of, snapshot_at=version.isoformat())
    snapshot.capture_cost_usd = billed_bytes * settings.bigquery_usd_per_tib / 2**40
    snapshot.capture_billing = billing
    return snapshot
