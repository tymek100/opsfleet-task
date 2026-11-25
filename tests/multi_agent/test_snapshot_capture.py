"""Independent warehouse capture refuses unknown size and accounts unknown billing."""

from types import SimpleNamespace

import pytest

from evaluation.multi_agent.oracle import AS_OF
from evaluation.multi_agent.snapshot import MAX_REFERENCE_ROWS, capture


def fake_client(monkeypatch, *, total_rows: int | None = 0, billed=None):
    class Rows(list):
        total_rows: int | None

    rows = Rows()
    rows.total_rows = total_rows
    job = SimpleNamespace(total_bytes_billed=billed, result=lambda timeout: rows)
    queries = []

    def query(sql, job_config):
        queries.append(sql)
        return job

    client = SimpleNamespace(query=query)
    monkeypatch.setattr("evaluation.multi_agent.snapshot.bigquery.Client", lambda **kwargs: client)
    return SimpleNamespace(
        warehouse_source_dataset="bigquery-public-data.thelook_ecommerce",
        google_cloud_project="test-project",
        bigquery_usd_per_tib=6.25,
        captured_queries=queries,
    )


def test_unknown_row_count_aborts_instead_of_assuming_empty_or_truncating(monkeypatch):
    settings = fake_client(monkeypatch, total_rows=None)
    with pytest.raises(ValueError, match="unknown row count"):
        capture(settings, AS_OF)


def test_unknown_billing_uses_per_query_cap_and_records_the_assumption(monkeypatch):
    settings = fake_client(monkeypatch)
    snapshot = capture(settings, AS_OF)
    assert snapshot.capture_cost_usd == pytest.approx(5 * 500_000_000 * 6.25 / 2**40)
    assert len(snapshot.capture_billing) == 5
    assert all("unavailable" in item["basis"] for item in snapshot.capture_billing)


def test_reported_zero_billing_remains_zero_without_unknown_usage_assumption(monkeypatch):
    settings = fake_client(monkeypatch, billed=0)
    snapshot = capture(settings, AS_OF)
    assert snapshot.capture_cost_usd == 0
    assert all(item["basis"] == "reported billed bytes" for item in snapshot.capture_billing)


def test_capture_queries_include_every_brand(monkeypatch):
    settings = fake_client(monkeypatch, billed=0)
    capture(settings, AS_OF)
    assert len(settings.captured_queries) == 5
    assert all("WHERE" not in sql for sql in settings.captured_queries)
    assert all("FOR SYSTEM_TIME AS OF" in sql for sql in settings.captured_queries)


def test_full_dataset_capture_still_rejects_oversized_sources(monkeypatch):
    settings = fake_client(monkeypatch, total_rows=MAX_REFERENCE_ROWS + 1)
    with pytest.raises(ValueError, match="no truncation"):
        capture(settings, AS_OF)
