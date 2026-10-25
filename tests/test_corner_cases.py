"""Regressions for the held-out October audit, using only synthetic evidence."""

from datetime import date

import pytest

from retail_agent.agent import Analyst
from retail_agent.config import Settings
from retail_agent.intent import completion_issues
from retail_agent.models import DEMO_USERS, Analysis, Answer, Dimension, Evidence
from retail_agent.quality import fallback_text
from retail_agent.reports import ReportStore
from tests.contracts import contract_for
from tests.fixture_data import FixtureExecutor
from tests.test_agent import Script

TODAY = date(2026, 10, 25)


@pytest.mark.parametrize(
    "question, expected",
    [
        (
            "For customer ID 1, show their state and revenue in Q1 2026.",
            "individual locations",
        ),
        (
            "Calculate net profit margin after shipping costs, taxes and marketing spend for Q1 2026.",
            "Revenue is not profit",
        ),
        (
            "List the names, email addresses and postal addresses of our top 10 customers in Q1 2026.",
            "excluded for privacy",
        ),
        ("Show revenue from 2026-02-30 to 2026-03-02.", "does not exist"),
        ("Show revenue from 2026-04-01 to 2026-01-01.", "end date must be after"),
    ],
)
@pytest.mark.asyncio
async def test_reviewed_nonanalytical_routes_never_execute_queries(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    store: ReportStore,
    question: str,
    expected: str,
) -> None:
    script = Script([])
    script.install(monkeypatch)
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "corner")
    answer = await analyst.ask(question)
    assert expected in answer.text
    assert not answer.evidence and not script.payloads
    assert answer.estimated_cost_usd == 0 and answer.quality_status == "not_applicable"
    assert not store.list("alice")


def test_report_prior_total_is_sufficient_but_current_breakdowns_are_required(
    answer: Answer,
) -> None:
    intent = contract_for(
        "Create a Q4 2025 report comparing revenue with Q3 2025, including monthly revenue, insights, and action items for Q1 2026.",
        today=TODAY,
    )
    assert intent.period and intent.comparison
    assert intent.action_period and intent.action_period.start == date(2026, 1, 1)
    evidence: list[Evidence] = []
    facts: list[str] = []
    for number, (dimension, period) in enumerate(
        [
            (Dimension.TOTAL, intent.period),
            (Dimension.MONTH, intent.period),
            (Dimension.PRODUCT, intent.period),
            (Dimension.TOTAL, intent.comparison),
        ],
        1,
    ):
        item = answer.evidence[0].model_copy(deep=True)
        item.id = f"E{number}"
        item.request = Analysis(start=period.start, end=period.end, dimension=dimension)
        evidence.append(item)
        facts.append(f"{item.id}.r0.revenue")
    facts.extend(["E1.vs.E4.revenue_change", "E1.vs.E4.revenue_change_pct"])
    assert completion_issues(intent, evidence, facts) == []
    assert any(
        "month" in issue
        for issue in completion_issues(
            intent, [e for e in evidence if e.request.dimension != Dimension.MONTH], facts
        )
    )
    assert "missing_period_comparison_metrics" in completion_issues(intent, evidence, facts[:-2])


def test_fallback_retains_all_months_and_formats_values(answer: Answer) -> None:
    item = answer.evidence[0]
    item.request = Analysis(start=date(2026, 1, 1), end=date(2026, 4, 1), dimension=Dimension.MONTH)
    item.rows = [{"month": f"2026-{m:02}", "revenue": float(m * 100)} for m in range(1, 4)]
    total = item.model_copy(deep=True)
    total.id = "E2"
    total.request = total.request.model_copy(update={"dimension": Dimension.TOTAL})
    total.rows = [{"revenue": 600.0, "units": 10, "orders": 9, "customers": 8}]
    text = fallback_text(
        [total, item], contract_for("Q1 2026 total and monthly revenue", today=TODAY)
    )
    assert "could not be validated" in text
    assert all(f"2026\\-{m:02}" in text for m in range(1, 4))
    assert "300.00" in text and "600.00" in text
    assert "average daily revenue" not in text


@pytest.mark.asyncio
async def test_empty_churn_finishes_after_first_tool_without_narrative_repair(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    store: ReportStore,
) -> None:
    script = Script([])
    script.install(monkeypatch)
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "empty-churn")
    answer = await analyst.ask(
        "Was the 90-day inactivity share zero in January 2000? Show eligible and inactive counts."
    )
    assert len(script.payloads) == 0 and len(answer.evidence) == 1
    assert answer.quality_status == "validated"
    assert "undefined, not 0%" in answer.text
    assert "2000-01-01 | 0 | 0 | Undefined" in answer.text
    assert "2000-02-01 | 0 | 0 | Undefined" in answer.text
