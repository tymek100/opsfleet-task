"""Business display regressions using independent expected values, without providers."""

from datetime import date
from io import StringIO

from rich.console import Console

from retail_agent.models import Answer, Dimension
from retail_agent.quality import Narrative, render_narrative
from retail_agent.render import display_answer, render_answer
from tests.contracts import contract_for


def ranking_answer(answer: Answer) -> Answer:
    total = answer.evidence[0]
    total.rows = [{"revenue": 10200.38}]
    customers = total.model_copy(deep=True)
    customers.id = "E2"
    customers.request = customers.request.model_copy(update={"dimension": Dimension.CUSTOMER})
    customers.rows = [
        {"user_id": 57867, "revenue": 259.99, "orders": 1},
        {"user_id": 29166, "revenue": 199, "orders": 1},
        {"user_id": 89352, "revenue": 199, "orders": 1},
    ]
    answer.intent = contract_for(
        "Top 10 customers by total spend for Q1 2026", today=date(2026, 10, 25)
    )
    answer.evidence = [total, customers]
    answer.quality_status = "validated"
    answer.text = render_narrative(
        Narrative(
            facts=[
                "E1.r0.revenue",
                *[f"E2.r{i}.{metric}" for i in range(3) for metric in ("revenue", "orders")],
            ]
        ),
        answer.evidence,
        answer.intent,
    )
    return answer


def test_customer_ranking_has_one_context_a_table_and_no_auxiliary_total(answer: Answer) -> None:
    answer = ranking_answer(answer)
    assert answer.intent and len(answer.intent.requirements) == 1
    text = render_answer(answer)
    assert "| Rank | Customer ID | Total spend | Orders |" in text
    assert "| 1 | 57867 | 259.99 | 1 |" in text
    assert "| 2 | 29166 | 199.00 | 1 |" in text
    assert "| 3 | 89352 | 199.00 | 1 |" in text
    assert text.count("Calvin Klein") == 1
    assert "31 Mar 2026" in text and "end exclusive" not in text
    assert "10,200.38" not in text and "SQL" not in text and "user_id" not in text
    assert text.count("/details") == 1 and "Source: [E2]" in text
    assert "Each customer in this ranking placed one qualifying order" in text
    assert "Cancelled and returned" in text and "$" not in text
    details = render_answer(answer, details=True)
    assert "10200.38" in details and "SQL hash" in details
    stream = StringIO()
    display_answer(Console(file=stream, width=100, color_system=None), answer)
    terminal = stream.getvalue()
    assert "57867" in terminal and "259.99" in terminal and "Total spend" in terminal
    assert "| Rank |" not in terminal  # Rich renders a table, not Markdown syntax.


def test_monthly_rows_keep_chronological_order_and_null_is_not_zero(answer: Answer) -> None:
    item = answer.evidence[0]
    item.request = item.request.model_copy(update={"dimension": Dimension.MONTH})
    item.rows = [{"month": "2026-01", "revenue": 100}, {"month": "2026-02", "revenue": None}]
    text = render_narrative(Narrative(facts=["E1.r0.revenue", "E1.r1.revenue"]), [item])
    assert "Monthly performance" in text and "100.00" in text and "Not available" in text
    assert text.index("2026\\-01") < text.index("2026\\-02")


def test_catalog_text_cannot_inject_table_rows_or_links(answer: Answer) -> None:
    item = answer.evidence[0]
    item.request = item.request.model_copy(update={"dimension": Dimension.PRODUCT})
    item.rows = [
        {"product_id": 1, "product_name": "[click](https://evil.test)\n| fake |", "revenue": 100}
    ]
    text = render_narrative(Narrative(facts=["E1.r0.revenue"]), [item])
    assert "\\[click\\]" in text and "\\| fake \\|" in text
    assert "\n| fake" not in text and "[click](https://evil.test)" not in text


def test_failed_validation_remains_visibly_a_fallback(answer: Answer) -> None:
    answer.quality_status = "fallback"
    answer.text = "Report narrative could not be validated."
    text = render_answer(answer)
    assert "could not be validated" in text


def test_available_optional_cells_are_not_misrepresented_as_missing(answer: Answer) -> None:
    result = ranking_answer(answer)
    item = result.evidence[1]
    text = render_narrative(
        Narrative(facts=["E2.r0.revenue", "E2.r0.orders", "E2.r1.revenue", "E2.r2.revenue"]),
        [item],
        result.intent,
    )
    assert "| 2 | 29166 | 199.00 | 1 |" in text
    assert "Not available" not in text


def test_clarification_does_not_display_an_empty_scope(answer: Answer) -> None:
    answer.evidence = []
    answer.text = "Please clarify the analysis."
    answer.intent = contract_for("Compare Q4 2025 and Q1 2026", today=date(2026, 10, 25))
    assert render_answer(answer) == "Please clarify the analysis."


def comparison_answer(answer: Answer) -> Answer:
    from tests.test_intent import QUARTER_COMPARISON

    old = answer.evidence[0].model_copy(deep=True)
    old.request = old.request.model_copy(
        update={"start": date(2025, 10, 1), "end": date(2026, 1, 1), "brands": ["Calvin Klein"]}
    )
    old.rows = [{"revenue": 10374.19, "units": 157, "orders": 157, "customers": 157}]
    new = old.model_copy(deep=True)
    new.id = "E2"
    new.request = new.request.model_copy(
        update={"start": date(2026, 1, 1), "end": date(2026, 4, 1)}
    )
    new.rows = [{"revenue": 10200.38, "units": 163, "orders": 162, "customers": 162}]
    answer.evidence = [old, new]
    answer.intent = contract_for(QUARTER_COMPARISON, today=date(2026, 10, 25))
    # This fixture asserts Q1 relative to Q4, so Q4 must be the baseline.
    answer.intent = answer.intent.model_copy(
        update={"period": answer.intent.comparison, "comparison": answer.intent.period}
    )
    answer.quality_status = "validated"
    names = ("revenue", "units", "orders", "customers", "days", "revenue_per_day")
    facts = [f"{e.id}.r0.{name}" for e in answer.evidence for name in names]
    facts += [
        f"E2.vs.E1.{name}"
        for name in (
            "revenue_change",
            "revenue_change_pct",
            "revenue_per_day_change_pct",
            "volume_contribution",
        )
    ]
    answer.text = render_narrative(Narrative(facts=facts), answer.evidence, answer.intent)
    return answer


def test_quarter_comparison_leads_with_explanation_and_one_table(answer: Answer) -> None:
    result = comparison_answer(answer)
    text = render_answer(result)
    assert "Revenue fell 1.68%, while average daily revenue rose 0.51%." in text
    assert "| Metric | Q4 2025 | Q1 2026 | Change |" in text
    assert "| Revenue | 10,374.19 | 10,200.38 | -173.81 (-1.68%) |" in text
    assert "| Average daily revenue | 112.76 | 113.34 | +0.57 (+0.51%) |" in text
    assert "| Calendar days | 92 | 90 | -2 |" in text
    assert "| Units sold | 157 | 163 | +6 (+3.82%) |" in text
    assert "Q1 2026 had 90 days versus 92 in Q4 2025" in text
    assert "Despite lower total revenue, average daily revenue increased." in text
    assert "| Distinct customers | 157 | 162 | +5 (+3.18%) |" in text
    assert text.count("Calvin Klein") == 1
    assert "Selected brands" not in text and "Overall performance" not in text
    assert "Sources: [E1], [E2]" in text
    assert "volume contribution" not in text and "arithmetic" not in text
    assert "Cancelled and returned" in text and text.count("/details") == 1
    details = render_answer(result, details=True)
    assert "volume contribution = 396.47" in details
    assert "unit value contribution = -570.28" in details
    assert "not causal" in details
    stream = StringIO()
    display_answer(Console(file=stream, width=100, color_system=None), result, details=True)
    assert "396.47" in stream.getvalue() and "-570.28" in stream.getvalue()


def test_undefined_baseline_does_not_produce_growth_claim(answer: Answer) -> None:
    from retail_agent.presentation import comparison_findings
    from retail_agent.quality import metric_catalog

    result = comparison_answer(answer)
    old, new = result.evidence
    old.rows[0]["revenue"] = 0
    values = {key: metric.value for key, metric in metric_catalog(result.evidence).items()}
    text = comparison_findings(old, new, values, ["revenue", "days", "revenue_per_day"])
    assert "percentage change is undefined" in text
    assert "percentage undefined" in text and "rose" not in text and "fell" not in text
    assert "| Revenue | 0.00 | 10,200.38 | +10,200.38" in text


def test_incompatible_scopes_are_not_combined_into_comparison_table(answer: Answer) -> None:
    result = comparison_answer(answer)
    result.evidence[1].scope = "all brands"
    text = render_narrative(
        Narrative(facts=["E1.r0.revenue", "E2.r0.revenue"]), result.evidence, result.intent
    )
    assert "| Metric | Q4 2025 | Q1 2026 | Change |" not in text
    assert "Revenue fell" not in text


def test_small_churn_change_shows_counts_and_does_not_claim_a_spike(answer: Answer) -> None:
    from retail_agent.presentation import churn_findings

    item = answer.evidence[0]
    item.request = item.request.model_copy(update={"kind": "churn"})
    item.rows = [
        {
            "period": "2026-09-01",
            "cohort": "all",
            "eligible_customers": 1778,
            "inactive_customers": 1776,
            "inactivity_share": 1776 / 1778,
        },
        {
            "period": "2026-10-01",
            "cohort": "all",
            "eligible_customers": 1861,
            "inactive_customers": 1859,
            "inactivity_share": 1859 / 1861,
        },
    ]
    text = churn_findings(item)
    assert "99.8875%" in text and "99.8925%" in text
    assert "+0.0050 percentage points" in text
    assert "Eligible customers: 1,778 → 1,861" in text
    assert "Eligible active customers stayed at 2" in text
    assert "does not establish a spike" in text


def test_empty_sales_explains_no_qualifying_sales(answer: Answer) -> None:
    answer.evidence[0].rows = [{"revenue": None, "units": 0, "orders": 0, "customers": 0}]
    text = render_narrative(Narrative(facts=["E1.r0.revenue"]), answer.evidence)
    assert "No qualifying sales were found" in text
    assert "undefined" not in text and "revenue = 0" not in text


def test_unchanged_full_inactivity_share_does_not_claim_denominator_changed_share(
    answer: Answer,
) -> None:
    from retail_agent.presentation import churn_findings

    item = answer.evidence[0]
    item.request = item.request.model_copy(update={"kind": "churn"})
    item.rows = [
        {
            "cohort": "all",
            "period": "2026-01-01",
            "eligible_customers": 10,
            "inactive_customers": 10,
            "inactivity_share": 1.0,
        },
        {
            "cohort": "all",
            "period": "2026-04-01",
            "eligible_customers": 20,
            "inactive_customers": 20,
            "inactivity_share": 1.0,
        },
    ]
    text = churn_findings(item)
    assert "was unchanged" in text and "The share changed" not in text
