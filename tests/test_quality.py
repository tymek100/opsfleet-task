"""Independent oracles for factual, semantic, period and fallback boundaries."""

from datetime import date

import pytest
from pydantic import ValidationError

from retail_agent.agent import check_draft
from retail_agent.models import Analysis, Answer, Evidence
from retail_agent.quality import (
    Hypothesis,
    Narrative,
    ProposedAction,
    action_window,
    metric_catalog,
    render_narrative,
    validate_narrative,
)

QUESTION = "Create a report for Q1 2026 with insights and action items for Q2 2026."


def sample(answer: Answer) -> list[Evidence]:
    return [
        answer.evidence[0].model_copy(
            update={
                "rows": [
                    {
                        "revenue": 600.0,
                        "units": 12,
                        "orders": 4,
                        "customers": 2,
                    }
                ]
            }
        )
    ]


def valid_report() -> Narrative:
    return Narrative(
        facts=["E1.r0.revenue", "E1.r0.units_per_order"],
        hypotheses=[Hypothesis(mechanism="seasonality", evidence_ids=["E1"])],
        actions=[
            ProposedAction(
                kind="cross_sell_test",
                metric_id="E1.r0.units_per_order",
                start=date(2026, 4, 1),
                end=date(2026, 7, 1),
                target=3.5,
            )
        ],
    )


def test_basket_is_units_over_orders_not_customers_over_orders(answer: Answer) -> None:
    evidence = sample(answer)
    catalog = metric_catalog(evidence)
    assert catalog["E1.r0.units_per_order"].value == 3
    assert catalog["E1.r0.revenue_per_unit"].value == 50
    assert catalog["E1.r0.revenue_per_order"].value == 150
    report = valid_report()
    assert validate_narrative(report, evidence, QUESTION) == []
    text = render_narrative(report, evidence)
    assert "units per order = 3" in text and "revenue = 600" in text
    assert "Unverified hypotheses" in text and "Seasonality could contribute" in text
    assert "Proposed target: 3.5" in text and "not forecasts" in text
    assert "2026-04-01 to 2026-07-01" in text


@pytest.mark.parametrize(
    "fake_metric",
    [
        "E1.r0.margin",
        "E9.r0.revenue",
        "E1.r0.revenue = 999999",
        "Seasonal spring purchases drove the March increase",
    ],
)
def test_unknown_facts_and_unsupported_margin_are_rejected(
    answer: Answer, fake_metric: str
) -> None:
    report = valid_report()
    report.facts = [fake_metric]
    assert "unknown_fact_metric" in validate_narrative(report, sample(answer), QUESTION)


def test_no_free_prose_can_escape_structured_fact_boundary(answer: Answer) -> None:
    from retail_agent.agent import Draft

    draft = Draft(
        kind="analysis",
        message="Expand high-margin products; seasonality drove growth.",
        narrative=valid_report(),
    )
    _, issues = check_draft(draft.model_dump_json(), sample(answer), QUESTION)
    assert "analysis_free_text_not_allowed" in issues
    with pytest.raises(ValidationError):
        Narrative.model_validate({"facts": ["E1.r0.revenue"], "explanation": "made up"})
    with pytest.raises(ValidationError):
        Hypothesis.model_validate(
            {"mechanism": "seasonality", "evidence_ids": ["E1"], "claim": "established cause"}
        )


def test_february_action_and_customer_based_basket_measure_rejected(answer: Answer) -> None:
    report = valid_report()
    report.actions[0].start = date(2026, 2, 1)
    report.actions[0].metric_id = "E1.r0.customers"
    assert set(validate_narrative(report, sample(answer), QUESTION)) == {
        "invalid_action_measure",
        "action_period_mismatch_or_ambiguous",
    }


def test_zero_denominators_and_null_revenue_are_not_zero(answer: Answer) -> None:
    evidence = sample(answer)
    evidence[0].rows = [{"revenue": None, "units": 0, "orders": 0, "customers": 0}]
    catalog = metric_catalog(evidence)
    assert catalog["E1.r0.units_per_order"].value is None
    assert catalog["E1.r0.revenue"].value is None
    assert "undefined" in catalog["E1.r0.units_per_order"].statement()
    assert "invalid_action_measure" in validate_narrative(valid_report(), evidence, QUESTION)


def test_change_uses_same_scope_filters_and_definition(answer: Answer) -> None:
    evidence = sample(answer)
    prior = evidence[0].model_copy(
        update={
            "id": "E2",
            "request": Analysis(start=date(2025, 10, 1), end=date(2026, 1, 1)),
            "rows": [{"revenue": 800, "units": 10, "orders": 5, "customers": 3}],
        }
    )
    catalog = metric_catalog([*evidence, prior])
    assert catalog["E1.vs.E2.revenue_change_pct"].value == -25
    assert catalog["E1.vs.E2.units_change_pct"].value == 20
    prior.scope = "all brands"
    assert "E1.vs.E2.revenue_change_pct" not in metric_catalog([*evidence, prior])
    prior.scope = evidence[0].scope
    prior.request = prior.request.model_copy(update={"completed_only": True})
    assert "E1.vs.E2.revenue_change_pct" not in metric_catalog([*evidence, prior])


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (QUESTION, (date(2026, 4, 1), date(2026, 7, 1))),
        ("Q1 2026 report with Q2 actions", (date(2026, 4, 1), date(2026, 7, 1))),
        ("Q4 2026 report with actions for Q1 2027", (date(2027, 1, 1), date(2027, 4, 1))),
        ("Q1 report with Q2 actions", None),
        ("Compare Q1 2026 and Q4 2025 and recommend actions", None),
        ("Q4 2026 report with Q1 actions", None),
        ("Create a report with actions for May", None),
    ],
)
def test_action_window_is_resolved_independently(
    question: str, expected: tuple[date, date] | None
) -> None:
    assert action_window(question, []) == expected


def test_target_domain_and_evidence_reference_validation(answer: Answer) -> None:
    e = answer.evidence[0].model_copy(
        update={
            "request": Analysis(kind="churn", start=date(2026, 1, 1), end=date(2026, 4, 1)),
            "rows": [{"inactivity_share": 0.4}],
        }
    )
    report = Narrative(
        facts=["E1.r0.inactivity_share"],
        hypotheses=[Hypothesis(mechanism="promotion", evidence_ids=["E8"])],
        actions=[
            ProposedAction(
                kind="retention_test",
                metric_id="E1.r0.inactivity_share",
                start=date(2026, 4, 1),
                end=date(2026, 7, 1),
                target=30,
            )
        ],
    )
    assert set(validate_narrative(report, [e], QUESTION)) == {
        "fraction_target_out_of_range",
        "unknown_hypothesis_evidence",
    }
    with pytest.raises(ValidationError):
        ProposedAction(
            kind="retention_test",
            metric_id="E1.r0.inactivity_share",
            start=date(2026, 4, 1),
            end=date(2026, 7, 1),
            target=float("nan"),
        )
