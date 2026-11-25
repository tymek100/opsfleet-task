"""Frozen evaluation time and trusted BigQuery source substitution contracts."""

from datetime import UTC, datetime

import pytest

from retail_insight.integrations.bigquery.retail import (
    DataError,
    QueryGateway,
    analyze_results,
    compile_query,
)

AS_OF = datetime(2026, 4, 1, 0, 30, 45, tzinfo=UTC)
SQL_CLOCK = "SELECT CURRENT_DATE() AS today, CURRENT_TIMESTAMP() AS now, CURRENT_DATE('America/Los_Angeles') AS local_date, CURRENT_DATETIME() AS local_datetime, CURRENT_TIME() AS local_time"


def test_compiled_bigquery_uses_frozen_clock_and_preserves_scoped_projection():
    compiled = compile_query(
        SQL_CLOCK + " FROM sales",
        ("Calvin Klein",),
        source_dataset="evaluation-project.snapshot_v1",
        as_of=AS_OF,
    )
    assert "CURRENT_" not in compiled
    assert "2026-04-01T00:30:45+00:00" in compiled and "2026-03-31" in compiled
    for table in ("products", "orders", "order_items"):
        assert f"evaluation-project.snapshot_v1.{table}" in compiled
    assert "p.brand IN UNNEST(@__scope_brands)" in compiled
    assert "Cancelled" in compiled and "Returned" in compiled
    assert "bigquery-public-data" not in compiled


async def test_fixture_clock_matches_bigquery_compilation_and_artifact_time(warehouse_fixture):
    gateway = QueryGateway(
        ("Calvin Klein",), backend="fixture", fixture_path=warehouse_fixture, clock=lambda: AS_OF
    )
    result = await gateway.query(SQL_CLOCK)
    row = result["rows"][0]
    assert row["today"] == "2026-04-01" and row["local_date"] == "2026-03-31"
    assert row["local_datetime"] == "2026-04-01T00:30:45" and row["local_time"] == "00:30:45"
    assert datetime.fromisoformat(row["now"]).replace(tzinfo=UTC) == AS_OF
    assert result["executed_at"] == AS_OF.isoformat()
    local = await analyze_results(
        {"E1": {"columns": ["revenue"], "rows": [{"revenue": 1}]}},
        "SELECT CURRENT_DATE() AS today FROM E1",
        as_of=AS_OF,
    )
    assert local["rows"] == [{"today": "2026-04-01"}]
    assert local["executed_at"] == AS_OF.isoformat()


def test_unconfigured_runtime_keeps_current_clock_and_public_source():
    compiled = compile_query("SELECT CURRENT_DATE() FROM sales", ("Calvin Klein",))
    assert "CURRENT_DATE" in compiled and "bigquery-public-data.thelook_ecommerce" in compiled


@pytest.mark.parametrize(
    "source", ["project.dataset` WHERE TRUE --", "project.dataset.other", "https://project.dataset"]
)
def test_source_configuration_rejects_non_identifiers(source):
    with pytest.raises(ValueError):
        QueryGateway(None, source_dataset=source)


def test_model_cannot_select_physical_snapshot_or_naive_clock():
    with pytest.raises(DataError):
        compile_query(
            "SELECT * FROM `evaluation-project.snapshot_v1.products`",
            None,
            source_dataset="evaluation-project.snapshot_v1",
        )
    with pytest.raises(ValueError):
        compile_query("SELECT CURRENT_DATE()", None, as_of=datetime(2026, 4, 1))
