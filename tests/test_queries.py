from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, Analysis, AppError, Dimension
from retail_agent.observability import Trace
from retail_agent.queries import compile_query
from tests.fixture_data import FixtureExecutor


def request(**overrides: object) -> Analysis:
    return Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01", **overrides})


def test_mixed_brand_orders_returns_and_shared_customers(settings: Settings) -> None:
    executor = FixtureExecutor()
    result = executor.execute(
        compile_query(request(), DEMO_USERS["alice"]), Budget(settings), Trace()
    )
    row = result.rows[0]
    assert row["revenue"] == 350
    assert row["customers"] == 5
    assert row["orders"] == 6
    ceo = executor.execute(compile_query(request(), DEMO_USERS["ceo"]), Budget(settings), Trace())
    assert ceo.rows[0]["revenue"] == 1250
    assert ceo.rows[0]["orders"] == 6  # mixed-brand order counted once
    bob = executor.execute(compile_query(request(), DEMO_USERS["bob"]), Budget(settings), Trace())
    assert bob.rows[0]["revenue"] == 900


def test_rankings_use_distinct_customers_and_separate_order(settings: Settings) -> None:
    executor = FixtureExecutor()
    q = compile_query(request(dimension="product", rank_by="customers"), DEMO_USERS["alice"])
    rows = executor.execute(q, Budget(settings), Trace()).rows
    assert [(r["product_id"], r["customers"]) for r in rows] == [(3, 4), (1, 1)]
    assert [r["revenue"] for r in rows] == [200, 150]


def test_geography_only_aggregate_and_small_groups_suppressed(settings: Settings) -> None:
    q = compile_query(request(dimension="state"), DEMO_USERS["alice"])
    rows = FixtureExecutor().execute(q, Budget(settings), Trace()).rows
    assert len(rows) == 1 and rows[0]["state"] == "CA" and rows[0]["customers"] == 5
    assert "user_id" not in rows[0]
    assert "CANARY" not in str(rows) and "@example" not in str(rows)


@pytest.mark.parametrize("extra", [{"customer_id": 1}, {"product_ids": [1]}])
def test_geography_rejects_individual_filters(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        request(dimension="state", **extra)


def test_brand_scoped_churn_ignores_other_brand_and_future_purchase(settings: Settings) -> None:
    q = compile_query(
        request(kind="churn", start="2026-05-01", end="2026-06-01"), DEMO_USERS["alice"]
    )
    rows = FixtureExecutor().execute(q, Budget(settings), Trace()).rows
    assert [(r["eligible_customers"], r["inactive_customers"]) for r in rows] == [(1, 0), (5, 5)]
    assert [r["inactivity_share"] for r in rows] == [0, 1]
    # May purchase on Bob's brand and July purchase on Alice's brand cannot rescue June snapshot.


def test_empty_period_has_no_fabricated_revenue(settings: Settings) -> None:
    q = compile_query(request(start="2020-01-01", end="2020-02-01"), DEMO_USERS["alice"])
    row = FixtureExecutor().execute(q, Budget(settings), Trace()).rows[0]
    assert row["revenue"] is None and row["customers"] == 0


@pytest.mark.parametrize("dimension", list(Dimension))
def test_personal_columns_absent_from_all_generated_queries(dimension: Dimension) -> None:
    q = compile_query(request(dimension=dimension), DEMO_USERS["ceo"])
    for forbidden in [
        "first_name",
        "last_name",
        "email",
        "street_address",
        "postal_code",
        "latitude",
        "longitude",
    ]:
        assert forbidden not in q.sql.lower()
    if dimension != Dimension.STATE:
        assert ".users`" not in q.sql


@given(st.text(min_size=1, max_size=60).filter(lambda s: s != "Calvin Klein"))
def test_untrusted_brand_never_changes_scope(brand: str) -> None:
    with pytest.raises(AppError):
        compile_query(request(brands=[brand]), DEMO_USERS["alice"])


def test_injection_is_bound_data_for_ceo() -> None:
    attack = "x'); DROP TABLE users; --"
    q = compile_query(request(brands=[attack]), DEMO_USERS["ceo"])
    assert attack not in q.sql
    assert q.parameters["filter_brands"] == [attack]


@pytest.mark.parametrize(
    "extra",
    [
        {"sql": "SELECT email FROM users"},
        {"role": "ceo"},
        {"limit": 1000},
        {"start": "2026-04-01"},
        {"kind": "shell"},
    ],
)
def test_unknown_fields_and_invalid_plans_fail_closed(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        request(**extra)


def test_utc_half_open_boundary(settings: Settings) -> None:
    q = compile_query(request(start=date(2026, 1, 1), end=date(2026, 2, 1)), DEMO_USERS["alice"])
    row = FixtureExecutor().execute(q, Budget(settings), Trace()).rows[0]
    assert row["revenue"] == 100  # Feb 1 excluded


def test_churn_false_spike_premise_is_checked_in_code() -> None:
    from retail_agent.metrics import churn_comparisons
    from retail_agent.models import Scalar

    r = request(kind="churn", start="2026-05-01", end="2026-06-01")
    rows: list[dict[str, Scalar]] = [
        {"period": "2026-05-01", "cohort": "all", "inactivity_share": 0.6},
        {"period": "2026-06-01", "cohort": "all", "inactivity_share": 0.4},
    ]
    assert churn_comparisons(r, rows) == [
        {"cohort": "all", "percentage_point_change": -20.0, "direction": "decreased"}
    ]
    assert churn_comparisons(r, rows[:1])[0]["direction"] == "undefined"
