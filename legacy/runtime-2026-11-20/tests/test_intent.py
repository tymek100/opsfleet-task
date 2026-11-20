"""Contract/execution checks over typed plans, not natural-language parsing."""

from datetime import date

import pytest
from pydantic import ValidationError

from retail_agent.intent import completion_issues, validate_contract, validate_request
from retail_agent.models import (
    DEMO_USERS,
    Analysis,
    Answer,
    AppError,
    Dimension,
    Intent,
    Period,
    Requirement,
)
from tests.contracts import contract_for

QUARTER_COMPARISON = (
    "Compare total revenue in Q4 2025 and Q1 2026. Show revenue, units sold, orders, "
    "and distinct customers for each quarter. Calculate the absolute revenue difference "
    "and percentage change from Q4 to Q1. Explain whether the quarters contain the same "
    "number of days and distinguish total growth from daily performance."
)


@pytest.mark.parametrize(
    "changes",
    [
        {"start": date(2026, 7, 1), "end": date(2026, 10, 1)},
        {"completed_only": True},
        {"inactivity_days": 30},
        {"customer_id": 1},
        {"product_ids": [1]},
        {"brands": ["Calvin Klein"]},
        {"dimension": Dimension.STATE},
    ],
)
def test_executor_rejects_drift_from_reviewed_contract(changes: dict[str, object]) -> None:
    contract = contract_for("Q1 2026 revenue")
    request = Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01", **changes})
    with pytest.raises(AppError):
        validate_request(request, contract, DEMO_USERS["alice"])


def test_contract_authorization_and_geography_cannot_be_changed_by_model() -> None:
    contract = contract_for("Q1 2026 revenue")
    contract.brands = ["Levi's"]
    with pytest.raises(AppError):
        validate_contract(contract, DEMO_USERS["alice"])
    contract.brands = []
    contract.customer_id = 1
    contract.requirements = [Requirement(dimension=Dimension.STATE)]
    with pytest.raises(ValidationError):
        validate_contract(contract, DEMO_USERS["alice"])


def test_invalid_contract_and_missing_comparison_outputs_fail_closed() -> None:
    with pytest.raises(AppError):
        validate_contract(Intent(), DEMO_USERS["alice"])
    contract = contract_for("Q1 2026 revenue")
    contract.comparison = Period(start=date(2025, 10, 1), end=date(2026, 1, 1))
    with pytest.raises(AppError):
        validate_contract(contract, DEMO_USERS["alice"])
    with pytest.raises(ValidationError):
        Period(start=date(2026, 4, 1), end=date(2026, 1, 1))


def test_monthly_truncation_and_incomplete_report_rejected(answer: Answer) -> None:
    contract = contract_for("Q1 2026 report without actions")
    with pytest.raises(AppError, match="truncate"):
        validate_request(
            Analysis(
                start=date(2026, 1, 1), end=date(2026, 4, 1), dimension=Dimension.MONTH, limit=1
            ),
            contract,
            DEMO_USERS["alice"],
        )
    issues = completion_issues(contract, answer.evidence, ["E1.r0.revenue"])
    assert any("month" in issue for issue in issues)
    assert any("product" in issue for issue in issues)


def test_all_ranking_rows_and_metrics_are_required(answer: Answer) -> None:
    contract = Intent(
        period=Period(start=date(2026, 1, 1), end=date(2026, 4, 1)),
        requirements=[
            Requirement(dimension=Dimension.PRODUCT, minimum_rows=10),
            Requirement(dimension=Dimension.PRODUCT, metric="customers", minimum_rows=10),
        ],
    )
    item = answer.evidence[0]
    item.request = item.request.model_copy(update={"dimension": Dimension.PRODUCT})
    item.rows = [{"revenue": 100}, {"revenue": 50}]
    issues = completion_issues(contract, [item], ["E1.r0.revenue"])
    assert any("missing_facts" in issue for issue in issues)
    assert any("customers" in issue for issue in issues)


def test_comparison_metrics_require_both_total_queries() -> None:
    contract = contract_for("Q1 2026 revenue")
    contract.comparison = Period(start=date(2025, 10, 1), end=date(2026, 1, 1))
    contract.comparison_requirements = [Requirement(dimension=Dimension.MONTH)]
    contract.comparison_metrics = ["revenue_change_pct"]
    with pytest.raises(AppError, match="totals in both periods"):
        validate_contract(contract, DEMO_USERS["alice"])


def test_direct_requests_deduplicate_totals_but_keep_distinct_rankings() -> None:
    from retail_agent.intent import execution_requests

    contract = contract_for("Q1 2026 revenue")
    contract.requirements = [
        Requirement(dimension=Dimension.TOTAL, metric=m) for m in ("revenue", "orders", "units")
    ] + [
        Requirement(dimension=Dimension.PRODUCT, metric=m, minimum_rows=4)
        for m in ("revenue", "customers")
    ]
    requests = execution_requests(contract)
    assert len(requests) == 3
    assert [(r.dimension, r.rank_by) for r in requests] == [
        (Dimension.TOTAL, "revenue"),
        (Dimension.PRODUCT, "revenue"),
        (Dimension.PRODUCT, "customers"),
    ]
    assert requests[1].limit == 4 and requests[2].limit == 4


def test_direct_month_requests_cover_partial_months_and_keep_all_filters() -> None:
    from retail_agent.intent import execution_requests

    contract = contract_for("Q1 2026 revenue")
    contract.period = Period(start=date(2026, 1, 31), end=date(2026, 3, 2))
    contract.requirements = [
        Requirement(dimension=Dimension.MONTH, metric=m) for m in ("revenue", "units")
    ]
    contract.product_ids = [1, 2]
    contract.completed_only = True
    (request,) = execution_requests(contract)
    assert request.limit == 3 and request.product_ids == [1, 2] and request.completed_only
    assert request.start == date(2026, 1, 31) and request.end == date(2026, 3, 2)
    validate_request(request, contract, DEMO_USERS["alice"])
