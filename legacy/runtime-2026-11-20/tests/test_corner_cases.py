"""Regressions for the held-out October audit, using only synthetic evidence."""

from datetime import date

from retail_agent.intent import completion_issues
from retail_agent.models import Analysis, Answer, Dimension, Evidence
from retail_agent.quality import fallback_text
from tests.contracts import contract_for

TODAY = date(2026, 10, 25)


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
