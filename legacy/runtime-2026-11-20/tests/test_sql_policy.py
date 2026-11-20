"""Numerical oracles and fail-closed admission for model-composed SQL."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.evidence import normalize_rows
from retail_agent.models import DEMO_USERS, AppError, Identity
from retail_agent.observability import Trace
from retail_agent.sql_policy import compile_analysis
from tests.fixture_data import FixtureExecutor


def execute(sql: str, settings: Settings, user: str = "alice") -> list[dict[str, object]]:
    compiled = compile_analysis(sql, DEMO_USERS[user])
    result = FixtureExecutor().execute(compiled, Budget(settings), Trace())
    return [dict(r) for r in result.rows]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT email FROM sales",
        "SELECT user_id, state FROM sales",
        "SELECT * FROM users",
        "SELECT * FROM `bigquery-public-data.thelook_ecommerce.users`",
        "SELECT * FROM sales UNION ALL SELECT * FROM users",
        "SELECT * FROM sales WHERE user_id IN (SELECT id FROM users)",
        "WITH nested AS (SELECT * FROM users) SELECT * FROM nested",
        "WITH sales AS (SELECT * FROM products) SELECT * FROM sales",
        "WITH safe AS (SELECT * FROM sales), nested AS (SELECT * FROM users) SELECT * FROM safe",
        "SELECT SUM(sale_price) FROM sales WHERE email IS NOT NULL",
        "SELECT LOWER(email) AS value FROM sales",
        "SELECT s.email FROM sales s",
        "SELECT * FROM EXTERNAL_QUERY('connection', 'select * from users')",
        "SELECT remote_fn(sale_price) AS value FROM sales",
        "SELECT @@project_id AS value FROM sales",
        "SELECT @all_brands AS value FROM sales",
        "SELECT * FROM sales; SELECT * FROM users",
        "DELETE FROM sales WHERE TRUE",
        "CREATE TABLE x AS SELECT * FROM sales",
        "EXPORT DATA OPTIONS(uri='gs://some-bucket/data') AS SELECT * FROM sales",
        "SELECT 999999 AS revenue",
        "SELECT * FROM sales FOR SYSTEM_TIME AS OF CURRENT_TIMESTAMP()",
        "SELECT sales FROM sales",
        "SELECT s FROM sales AS s",
        "WITH RECURSIVE x AS (SELECT product_id FROM products UNION ALL SELECT product_id FROM x) SELECT * FROM x",
    ],
)
def test_untrusted_query_cannot_escape_virtual_surface(sql: str) -> None:
    with pytest.raises(AppError):
        compile_analysis(sql, DEMO_USERS["alice"])


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(sale_price) AS revenue FROM sales",
        "WITH x AS (SELECT * FROM sales) SELECT SUM(sale_price) AS revenue FROM x",
        "SELECT SUM(x.revenue) AS revenue FROM (SELECT SUM(sale_price) AS revenue FROM sales UNION ALL SELECT 0 AS revenue FROM products LIMIT 100) x",
    ],
)
def test_nested_scope_preserved(sql: str, settings: Settings) -> None:
    assert execute(sql, settings) == [{"revenue": 430}]


def test_shared_customer_history_is_scoped_before_window(settings: Settings) -> None:
    sql = """WITH history AS (
      SELECT user_id, MAX(DATE(purchased_at)) AS last_purchase
      FROM sales WHERE purchased_at < '2026-06-01' GROUP BY user_id)
      SELECT CAST(last_purchase AS STRING) AS last_purchase FROM history WHERE user_id=1"""
    assert execute(sql, settings) == [{"last_purchase": "2026-02-01"}]
    assert execute(sql, settings, "ceo") == [{"last_purchase": "2026-05-20"}]


def test_composed_repeat_purchase_metric_without_new_intent(settings: Settings) -> None:
    sql = """WITH ordered AS (
      SELECT category, user_id, purchased_at,
        ROW_NUMBER() OVER (PARTITION BY category, user_id ORDER BY purchased_at, item_id) AS n
      FROM sales WHERE purchased_at < '2026-04-01'),
      customer_purchases AS (
        SELECT category, user_id, MAX(n) AS purchases FROM ordered GROUP BY category, user_id)
      SELECT category, COUNT(*) AS customers, COUNTIF(purchases > 1) AS repeat_customers,
        SAFE_DIVIDE(COUNTIF(purchases > 1), COUNT(*)) AS repeat_share
      FROM customer_purchases GROUP BY category ORDER BY category"""
    assert execute(sql, settings) == [
        {"category": "Jeans", "customers": 1, "repeat_customers": 1, "repeat_share": 1.0},
        {"category": "Tops", "customers": 4, "repeat_customers": 0, "repeat_share": 0.0},
    ]


def test_model_can_compose_inactivity_snapshots(settings: Settings) -> None:
    sql = """WITH history AS (
        SELECT user_id, MIN(DATE(purchased_at)) AS first_purchase,
          MAX(DATE(purchased_at)) AS last_purchase
        FROM sales WHERE purchased_at < '2026-06-01' GROUP BY user_id)
        SELECT COUNT(*) AS eligible,
          COUNTIF(last_purchase < DATE_SUB(DATE '2026-06-01', INTERVAL 90 DAY)) AS inactive,
          SAFE_DIVIDE(COUNTIF(last_purchase < DATE_SUB(DATE '2026-06-01', INTERVAL 90 DAY)), COUNT(*)) AS share
        FROM history WHERE first_purchase < DATE_SUB(DATE '2026-06-01', INTERVAL 90 DAY)"""
    assert execute(sql, settings) == [{"eligible": 5, "inactive": 5, "share": 1.0}]
    assert execute(sql, settings, "ceo") == [{"eligible": 5, "inactive": 4, "share": 0.8}]


def test_status_override_is_explicit_and_scoped(settings: Settings) -> None:
    sql = (
        "SELECT SUM(sale_price) AS returned_revenue FROM transactions WHERE item_status='Returned'"
    )
    assert execute(sql, settings) == [{"returned_revenue": 1300}]
    assert execute(sql, settings, "bob") == [{"returned_revenue": None}]


def test_no_entitlements_denied_even_for_nested_query() -> None:
    with pytest.raises(AppError):
        compile_analysis(
            "WITH x AS (SELECT * FROM sales) SELECT * FROM x", Identity(user_id="none", brands=())
        )


def test_dates_decimals_and_nonfinite_boundary() -> None:
    assert normalize_rows(
        [{"amount": Decimal("12.50"), "day": date(2026, 1, 1), "timestamp": datetime(2026, 1, 1)}],
        ("amount", "day", "timestamp"),
    ) == [{"amount": 12.5, "day": "2026-01-01", "timestamp": "2026-01-01T00:00:00"}]
    for value in [float("nan"), float("inf"), {"email": "canary@example.test"}, [1, 2]]:
        with pytest.raises(AppError):
            normalize_rows([{"value": value}], ("value",))
    with pytest.raises(AppError):
        normalize_rows([{"value": 1}] * 101, ("value",))
