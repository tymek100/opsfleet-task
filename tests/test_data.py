"""Distinguishing query/scoping cases, without credentials or live warehouse calls."""

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sqlglot
from sqlglot import exp

from retail_agent.services.warehouse import DataError, QueryGateway, analyze_results, compile_query

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "knowledge/fixtures/retail_seed_v1.sql"


def gateway(brands=("Calvin Klein",), **kwargs):
    return QueryGateway(brands, backend="fixture", fixture_path=FIXTURE, **kwargs)


@pytest.mark.asyncio
async def test_scope_precedes_mixed_orders_and_history():
    manager = gateway()
    result = await manager.query("""SELECT SUM(sale_price) AS revenue,
        COUNT(*) AS items, COUNT(DISTINCT order_id) AS orders,
        COUNT(DISTINCT user_id) AS customers FROM sales
        WHERE purchased_at >= TIMESTAMP '2026-01-01'
          AND purchased_at < TIMESTAMP '2026-04-01'""")
    assert result["rows"] == [{"revenue": 375.0, "items": 7, "orders": 6, "customers": 5}]
    assert result["scope"] == ["Calvin Klein"]
    history = await manager.query(
        "SELECT MAX(purchased_at) AS last_purchase FROM sales WHERE user_id=1 AND purchased_at < TIMESTAMP '2026-06-01'"
    )
    assert history["rows"] == [{"last_purchase": "2026-02-01T00:00:00"}]
    chief = await gateway(None).query("SELECT SUM(sale_price) AS revenue FROM sales")
    assert chief["rows"] == [{"revenue": 2355.0}]
    denied = await gateway(()).query("SELECT COUNT(*) AS items FROM sales")
    assert denied["rows"] == [{"items": 0}]


@pytest.mark.asyncio
async def test_flexible_composition_and_bound_parameters():
    result = await gateway().query(
        """WITH eligible AS (
        SELECT category, DATE(purchased_at) AS day, sale_price FROM sales
        WHERE purchased_at >= TIMESTAMP(@start) AND purchased_at < TIMESTAMP(@end)
    ) SELECT category, SUM(sale_price) AS revenue,
        COUNT(DISTINCT day) AS active_days,
        SAFE_DIVIDE(SUM(sale_price), COUNT(DISTINCT day)) AS revenue_per_active_day
    FROM eligible GROUP BY category ORDER BY revenue_per_active_day DESC, category""",
        {"start": "2026-01-01", "end": "2026-04-01"},
    )
    assert result["rows"] == [
        {"category": "Tops", "revenue": 200.0, "active_days": 2, "revenue_per_active_day": 100.0},
        {"category": "Jeans", "revenue": 175.0, "active_days": 2, "revenue_per_active_day": 87.5},
    ]


@pytest.mark.asyncio
async def test_outer_join_preserves_unsold_catalog_and_zero_denominator():
    result = await gateway().query("""SELECT p.product_id, COUNT(s.item_id) AS items
        FROM products p LEFT JOIN sales s ON s.product_id=p.product_id
        GROUP BY p.product_id HAVING COUNT(s.item_id)=0""")
    assert result["rows"] == [{"product_id": 4, "items": 0}]
    empty = await gateway().query("""SELECT COUNT(*) AS items,
        SAFE_DIVIDE(SUM(sale_price), COUNT(DISTINCT order_id)) AS average
        FROM sales WHERE purchased_at >= TIMESTAMP '2030-01-01'""")
    assert empty["rows"] == [{"items": 0, "average": None}]


@pytest.mark.asyncio
async def test_date_difference_is_available_for_new_inactivity_metrics():
    result = await gateway().query("""SELECT DATE_DIFF(DATE '2026-04-01',
        DATE(MIN(purchased_at)), DAY) AS observed_days FROM sales""")
    assert result["rows"] == [{"observed_days": 90}]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM `bigquery-public-data.thelook_ecommerce.users`",
        "SELECT * FROM sales UNION ALL SELECT * FROM fixture_items",
        "WITH x AS (SELECT * FROM secret) SELECT * FROM x",
        "SELECT * FROM sales WHERE EXISTS(SELECT 1 FROM users)",
        "SELECT (SELECT COUNT(*) FROM private.sales) FROM products",
        "WITH sales AS (SELECT * FROM products) SELECT * FROM sales",
        "SELECT * FROM sales; DELETE FROM sales",
        "DELETE FROM sales",
        "CREATE TEMP FUNCTION f(x INT64) AS (x); SELECT f(1)",
        "EXPORT DATA OPTIONS(uri='gs://x/y',format='CSV') AS SELECT * FROM sales",
        "SELECT remote.fn(user_id) FROM sales",
        "SELECT EXTERNAL_QUERY('x','SELECT * FROM users')",
        "SELECT * FROM read_csv('/tmp/private.csv')",
        "SELECT * FROM read_parquet('https://host/file')",
        "SELECT SESSION_USER()",
        "SELECT CURRENT_USER()",
        "SELECT SECRET('token')",
        "SELECT email FROM sales",
        "SELECT COUNT(*) FROM sales WHERE latitude > 0",
        "SELECT COUNT(*) FROM sales GROUP BY state",
        "SELECT * FROM sales ORDER BY first_name",
        "SELECT * FROM sales TABLESAMPLE SYSTEM(50 PERCENT)",
        "WITH RECURSIVE x AS (SELECT 1 UNION ALL SELECT 1 FROM x) SELECT * FROM x",
        "SELECT @__scope_brands",
        "SELECT * FROM sales FOR SYSTEM_TIME AS OF TIMESTAMP '2026-01-01'",
    ],
)
def test_unsafe_query_rejected_before_execution(sql):
    with pytest.raises(DataError):
        compile_query(sql, ("Calvin Klein",))


def test_all_nested_sources_replaced_before_user_history():
    sql = """WITH earlier AS (SELECT user_id, MIN(purchased_at) AS first_purchase FROM sales GROUP BY user_id)
        SELECT x.user_id FROM transactions x JOIN earlier e ON x.user_id=e.user_id
        WHERE EXISTS(SELECT 1 FROM products p WHERE p.product_id=x.product_id)"""
    compiled = compile_query(sql, ("Calvin Klein",))
    assert compiled.count("@__scope_brands") == 3
    tree = sqlglot.parse_one(compiled, read="bigquery")
    assert {table.name for table in tree.find_all(exp.Table)} <= {
        "orders",
        "order_items",
        "products",
        "earlier",
    }
    assert "p.brand IN UNNEST(@__scope_brands)" in compiled


@pytest.mark.parametrize("parameters", [{}, {"brand": "Calvin Klein", "extra": 1}, {"brand": []}])
def test_parameter_contract_rejects_missing_unused_or_nested(parameters):
    with pytest.raises(DataError):
        compile_query("SELECT * FROM sales WHERE brand=@brand", ("Calvin Klein",), parameters)


@pytest.mark.asyncio
async def test_parameter_values_cannot_change_sql():
    result = await gateway().query(
        "SELECT COUNT(*) AS items FROM sales WHERE brand=@brand",
        {"brand": "Calvin Klein' OR 1=1 --"},
    )
    assert result["rows"] == [{"items": 0}]


@pytest.mark.asyncio
async def test_truncation_is_explicit_and_local_transform_refuses_it():
    partial = await gateway(row_limit=2).query("SELECT item_id FROM sales ORDER BY item_id")
    assert partial["truncated"] is True
    assert len(partial["rows"]) == 2
    assert partial["total_rows"] is None
    with pytest.raises(DataError, match="truncated"):
        await analyze_results({"R1": partial}, "SELECT COUNT(*) AS n FROM R1")


@pytest.mark.asyncio
async def test_local_transform_preserves_population_and_lineage():
    result = await gateway().query(
        "SELECT product_id, SUM(sale_price) AS revenue FROM sales GROUP BY product_id ORDER BY product_id"
    )
    derived = await analyze_results(
        {"R1": result}, "SELECT product_id, revenue FROM R1 ORDER BY revenue DESC LIMIT 1"
    )
    assert derived["rows"] == [{"product_id": 1, "revenue": 255.0}]
    assert derived["parents"] == ["R1"]
    with pytest.raises(DataError):
        await analyze_results({"R1": result}, "SELECT * FROM sales")


@pytest.mark.asyncio
async def test_local_timeout_terminates_worker_and_next_query_works():
    with pytest.raises(DataError, match="timed out"):
        await gateway().query("SELECT COUNT(*) AS n FROM sales", timeout=0.001)
    result = await gateway().query("SELECT COUNT(*) AS n FROM sales")
    assert result["rows"] == [{"n": 8}]


@pytest.mark.asyncio
async def test_geo_fixture_never_returns_individual_geography():
    with pytest.raises(DataError, match="no customer geography"):
        await gateway().state_summary("2026-01-01", "2026-04-01")
    with pytest.raises(DataError):
        await gateway().state_summary("2026-01-01' OR TRUE--", "2026-04-01")


@pytest.mark.asyncio
async def test_byte_cap_prevents_real_submission():
    service = QueryGateway(("Calvin Klein",), project="unused", max_bytes=10)
    service._client = MagicMock()
    service._client.query.return_value.total_bytes_processed = 11
    with pytest.raises(DataError, match="byte allowance"):
        await service.query("SELECT COUNT(*) AS n FROM sales")
    assert service._client.query.call_count == 1
    assert service._client.query.call_args.kwargs["job_config"].dry_run is True


@pytest.mark.asyncio
async def test_warehouse_job_and_result_limits_and_scope_parameters():
    service = QueryGateway(("Calvin Klein",), project="unused", row_limit=2)
    client = MagicMock()
    service._client = client
    dry = MagicMock(total_bytes_processed=100)
    job = MagicMock(total_bytes_processed=80, job_id="job-1")
    rows = MagicMock(total_rows=3)
    field = MagicMock()
    field.name = "revenue"
    rows.schema = [field]
    row = MagicMock()
    row.values.return_value = (375.0,)
    rows.__iter__.return_value = iter([row])
    job.result.return_value = rows
    client.query.side_effect = [dry, job]
    result = await service.query("SELECT SUM(sale_price) AS revenue FROM sales")
    assert result["rows"] == [{"revenue": 375.0}]
    assert result["truncated"] is True
    assert result["bytes_processed"] == 80
    assert result["job_id"] == "job-1"
    execution = client.query.call_args_list[1]
    assert execution.kwargs["job_config"].maximum_bytes_billed == service.max_bytes
    assert execution.kwargs["job_config"].query_parameters[0].values == ["Calvin Klein"]
    assert execution.kwargs["job_id"].startswith("retail_")
    assert job.result.call_args.kwargs["max_results"] == 2


@pytest.mark.asyncio
async def test_cancelled_warehouse_attempt_requests_job_cancellation(monkeypatch):
    service = QueryGateway(("Calvin Klein",), project="unused")
    service._client = MagicMock()

    def slow(compiled, logical, timeout, job_id):
        service._submitted.add(job_id)
        time.sleep(0.05)
        raise TimeoutError

    monkeypatch.setattr(service, "_execute_bigquery", slow)
    with pytest.raises(DataError, match="timed out"):
        await service.query("SELECT COUNT(*) AS n FROM sales", timeout=0.01)
    assert service._client.cancel_job.call_count == 1
    assert service._client.cancel_job.call_args.args[0] in service._submitted


@pytest.mark.asyncio
async def test_repeated_query_recovers_identical_job_id():
    from google.api_core.exceptions import Conflict

    service = QueryGateway(("Calvin Klein",), project="unused")
    client = MagicMock()
    service._client = client
    dry = MagicMock(total_bytes_processed=100)
    job = MagicMock(total_bytes_processed=80, job_id="job-1")
    rows = MagicMock(total_rows=0)
    field = MagicMock()
    field.name = "revenue"
    rows.schema = [field]
    rows.__iter__.side_effect = lambda: iter([])
    job.result.return_value = rows
    client.query.side_effect = [dry, job, dry, Conflict("already exists")]
    client.get_job.return_value = job
    sql = "SELECT SUM(sale_price) AS revenue FROM sales"
    await service.query(sql)
    await service.query(sql)
    assert (
        client.query.call_args_list[1].kwargs["job_id"]
        == client.query.call_args_list[3].kwargs["job_id"]
    )
    client.get_job.assert_called_once()
