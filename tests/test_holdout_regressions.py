# pyright: reportPrivateUsage=false
"""Regression boundaries exposed by live holdout; no remote model calls."""

from datetime import date

import pytest
from pydantic import ValidationError

from retail_agent.agent import Analyst
from retail_agent.config import Settings
from retail_agent.intent import completion_issues
from retail_agent.models import DEMO_USERS, Answer, AppError, Dimension, Intent, Period, Requirement
from retail_agent.planning import LibraryOperation, TurnPlan
from retail_agent.quality import Narrative, metric_catalog, render_narrative, required_facts
from retail_agent.reports import ReportStore
from tests.fixture_data import FixtureExecutor


@pytest.mark.parametrize(
    "baseline_year,current_year,baseline,current",
    [(2026, 2025, 100, 150), (2024, 2026, 200, 100), (2024, 2025, 0, 100)],
)
def test_comparison_respects_roles_gaps_and_zero(
    answer: Answer, baseline_year: int, current_year: int, baseline: int, current: int
) -> None:
    first = answer.evidence[0].model_copy(deep=True)
    first.request = first.request.model_copy(
        update={"start": date(current_year, 1, 1), "end": date(current_year, 4, 1)}
    )
    first.rows = [{"revenue": current}]
    second = first.model_copy(deep=True)
    second.id = "E2"
    second.request = second.request.model_copy(
        update={"start": date(baseline_year, 1, 1), "end": date(baseline_year, 4, 1)}
    )
    second.rows = [
        {
            "revenue": baseline if baseline else None,
            "units": 1 if baseline else 0,
            "orders": 1 if baseline else 0,
            "customers": 1 if baseline else 0,
        }
    ]
    intent = Intent(
        period=Period(start=first.request.start, end=first.request.end),
        comparison=Period(start=second.request.start, end=second.request.end),
        requirements=[Requirement(dimension=Dimension.TOTAL, metric="revenue")],
        comparison_requirements=[Requirement(dimension=Dimension.TOTAL, metric="revenue")],
        comparison_metrics=["revenue_change", "revenue_change_pct"],
    )
    evidence = [second, first]  # Arrival order must not choose the denominator.
    catalog = metric_catalog(evidence, intent)
    assert catalog["E1.vs.E2.revenue_change"].value == current - baseline
    assert catalog["E1.vs.E2.revenue_change_pct"].value == (
        round((current / baseline - 1) * 100, 4) if baseline else None
    )
    facts = required_facts(intent, evidence)
    assert "E2.vs.E1.revenue_change" not in facts
    assert completion_issues(intent, evidence, facts) == []
    rendered = render_narrative(Narrative(facts=facts), evidence, intent)
    assert ("percentage undefined" in rendered) == (baseline == 0)


def test_cancel_sequence_changes_only_own_conversation(
    settings: Settings, store: ReportStore, answer: Answer
) -> None:
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "active")
    rid = store.save("alice", "active", "Keep", answer)
    preview = store.preview("alice", "active", "")
    store.preview("alice", "other", "")
    result = analyst._plan_response(
        TurnPlan(
            route="library",
            operations=[
                LibraryOperation(operation="cancel"),
                LibraryOperation(operation="reports"),
            ],
        )
    )
    assert "cancelled" in result and rid in result
    assert len(store.list("alice")) == 1
    assert (
        store.db.execute("SELECT count(*) FROM pending WHERE conversation='active'").fetchone()[0]
        == 0
    )
    assert (
        store.db.execute("SELECT count(*) FROM pending WHERE conversation='other'").fetchone()[0]
        == 1
    )
    with pytest.raises(AppError):
        store.confirm("alice", "active", preview.token)


def test_library_preflight_does_not_mutate_before_invalid_read(
    settings: Settings, store: ReportStore, answer: Answer
) -> None:
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "active")
    analyst.last_answer = answer
    with pytest.raises(AppError):
        analyst._plan_response(
            TurnPlan(
                route="library",
                operations=[
                    LibraryOperation(operation="save"),
                    LibraryOperation(operation="read", report_id="unknown"),
                ],
            )
        )
    assert store.list("alice") == []


def test_help_cannot_carry_mutations(settings: Settings, store: ReportStore) -> None:
    with pytest.raises(ValidationError):
        TurnPlan(route="help", help_topic="save", operations=[LibraryOperation(operation="save")])
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "active")
    assert "does not authorize" in analyst._plan_response(TurnPlan(route="help", help_topic="save"))
    assert store.list("alice") == []
