"""Independent live-data reference arithmetic and bounded read-only admission."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evaluation.manual_reference import capture, queries, summarize, totals


def item(
    identifier,
    customer,
    order,
    price,
    date,
    *,
    product=1,
    category="Tops",
    item_status="Complete",
    order_status="Complete",
):
    return {
        "item_id": identifier,
        "user_id": customer,
        "order_id": order,
        "sale_price": price,
        "purchased_at": date,
        "product_id": product,
        "category": category,
        "product_name": f"Product {product}",
        "brand": "Calvin Klein",
        "item_status": item_status,
        "order_status": order_status,
    }


def test_independent_history_grain_status_and_period_references():
    rows = [
        item(1, 10, 10, "10.10", "2025-12-31T23:59:59+00:00"),
        item(2, 10, 20, "20.20", "2026-01-01T00:00:00+00:00"),
        item(3, 10, 20, "30.30", "2026-01-01T00:00:00+00:00"),
        item(4, 11, 21, "40.40", "2026-01-15T00:00:00+00:00", product=2),
        item(5, 11, 22, "50.50", "2026-02-01T00:00:00+00:00", product=2),
        item(6, 12, 23, "999", "2026-03-01T00:00:00+00:00", order_status="Returned"),
        item(7, 13, 24, "999", "2026-03-01T00:00:00+00:00", item_status="Cancelled"),
        item(8, 11, 30, "60.60", "2026-04-01T00:00:00+00:00"),
    ]
    products = [
        {
            "product_id": n,
            "product_name": f"Product {n}",
            "brand": "Calvin Klein",
            "category": "Tops",
        }
        for n in (1, 2, 3)
    ]
    result = summarize(rows, products, [], ("Calvin Klein",))["Calvin Klein"]
    q1 = result["qualifying"]["q1_2026"]
    assert q1["revenue"] == Decimal("141.40")
    assert (q1["customers"], q1["orders"], q1["units"]) == (2, 3, 4)
    assert q1["aov"] == Decimal("141.40") / 3
    assert result["q1_all_statuses"]["revenue"] == Decimal("2139.40")
    cohort = result["customer_cohorts"]
    assert cohort["q1_first_scoped_purchase_customers"] == [11]
    assert cohort["q1_preexisting_customers"] == [10]
    assert cohort["q1_repeat_order_customers"] == [11]
    assert cohort["q4_to_q1_retention_rate"] == 1
    assert cohort["q1_new_retained_q2_rate"] == 1
    assert result["top_five_by_customers"][0]["product_id"] == 1
    assert result["unsold_q1_catalog_products"] == [products[2]]
    assert result["category_contributions"]["total_change"] == Decimal("131.30")


def test_empty_and_missing_prices_do_not_create_false_zero_averages():
    assert totals([])["revenue"] is None
    assert totals([])["aov"] is None
    result = totals([item(1, 1, 1, None, "2026-01-01")])
    assert result["units"] == 1 and result["priced_units"] == 0
    assert result["revenue"] is None and result["average_realized_unit_price"] is None


def test_duplicate_join_rows_are_rejected():
    row = item(1, 1, 1, "10", "2026-01-01")
    with pytest.raises(ValueError, match="Duplicate"):
        summarize([row, row], [], [])


def test_reference_admission_rejects_expensive_dry_run_without_execution(tmp_path):
    client = Mock()
    client.query.return_value = SimpleNamespace(total_bytes_processed=101)
    config = SimpleNamespace(
        warehouse_source_dataset="public-project.retail", google_cloud_project="offline"
    )
    with pytest.raises(ValueError, match="exceeding"):
        capture(config, tmp_path / "reference", max_query_bytes=100, client=client)
    assert client.query.call_count == 1
    call = client.query.call_args.kwargs
    assert call["job_config"].dry_run and call["retry"] is None
    assert 0 < call["timeout"] <= 60


def test_reference_queries_never_select_raw_customer_geography():
    sql = queries("bigquery-public-data.thelook_ecommerce")
    assert "users" not in sql["transactions"]
    assert "state" not in sql["transactions"]
    assert "HAVING COUNT(DISTINCT i.user_id) >= 5" in sql["states"]
    assert all("@brands" in statement for statement in sql.values())
    with pytest.raises(ValueError, match="source"):
        queries("untrusted` UNION ALL SELECT 1")


def test_successful_capture_is_complete_and_never_silently_truncated(tmp_path):
    raw_item = item(1, 1, 1, 10.1, datetime(2026, 1, 2, tzinfo=UTC))
    product = {key: raw_item[key] for key in ("product_id", "product_name", "brand", "category")}

    class Rows(list):
        @property
        def total_rows(self):
            return len(self)

    client = Mock()
    jobs = []
    for records in ([raw_item], [product], []):
        job = Mock(job_id=f"job-{len(jobs)}", total_bytes_processed=20, total_bytes_billed=20)
        job.result.return_value = Rows(records)
        jobs.extend([SimpleNamespace(total_bytes_processed=20), job])
    client.query.side_effect = jobs
    config = SimpleNamespace(
        warehouse_source_dataset="public-project.retail", google_cloud_project="offline"
    )
    result = capture(config, tmp_path / "reference", brands=("Calvin Klein",), client=client)
    assert result["status"] == "completed"
    assert len(result["reference_implementation_sha256"]) == 64
    assert set(result["files_sha256"]) == {
        "transactions.json",
        "products.json",
        "states.json",
        "summary.json",
    }
    for call in client.query.call_args_list[1::2]:
        assert call.kwargs["job_config"].maximum_bytes_billed == 100_000_000
        assert call.kwargs["retry"] is None and call.kwargs["job_retry"] is None
