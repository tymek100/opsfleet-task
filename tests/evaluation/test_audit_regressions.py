"""Adversarial controls for false passes, missing capture, and publication boundaries."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from google.genai import types

from evaluation.data import fixture_path, load_cases
from evaluation.graders.judge import GeminiJudge, JudgeUnavailable
from evaluation.graders.runner import grade_run, grade_trial, grade_turn
from evaluation.models import Criterion, Fault, TurnReference
from evaluation.results import Claim, Judgment, Trial, TurnRecord
from evaluation.runners.artifacts import prepare_run
from evaluation.runners.conversation import run_trial
from evaluation.runners.faults import FaultModel, Schedule
from evaluation.settings import EvaluationSettings
from retail_insight.contracts import Answer, TurnResult
from retail_insight.runtime.budget import Budget
from retail_insight.runtime.provider import AccountedModel
from tests.support.models import ScriptedModel, text, usage


class PassingJudge:
    async def evaluate(self, turn, reference, prior):
        from evaluation.results import CriterionFinding

        return Judgment(
            facts=[],
            claims=[Claim(span=turn.markdown, label="NOT_FACTUAL", reason="Control")],
            criteria=[
                CriterionFinding(id=c.id, passed=True, finding="Control")
                for c in reference.criteria
                if c.kind == "semantic"
            ],
            response_kind="substantive",
            coverage_complete=True,
        )


async def test_wrong_report_deleted_cannot_pass_by_matching_only_remaining_count():
    case = load_cases("report-delete-confirm")[0]
    before = [
        {"id": "delete-me", "owner": "workspace", "title": seed.title, "markdown": seed.markdown}
        for seed in case.initial_reports[:1]
    ] + [
        {
            "id": "keep-me",
            "owner": "workspace",
            "title": case.initial_reports[1].title,
            "markdown": case.initial_reports[1].markdown,
        }
    ]
    trial = Trial(
        id="wrong-delete-r1",
        case_id=case.id,
        repetition=1,
        status="completed",
        turns=[
            TurnRecord(
                step_id=case.steps[0].id,
                prompt=case.steps[0].message,
                status="approved",
                markdown="Please confirm deletion.",
                outcome="answer",
                reports_before=before,
                reports_after=before,
            ),
            TurnRecord(
                step_id=case.steps[1].id,
                kind="confirm_delete",
                status="completed",
                receipts=[{"status": "ok", "deleted_ids": ["keep-me"]}],
                reports_before=before,
                reports_after=before[:1],
            ),
        ],
        reports_final=before[:1],
    )
    grade = await grade_trial(case, trial, PassingJudge())
    assert grade.status == "FAIL"
    assert any(score.status == "FAIL" for score in grade.scores)


@pytest.mark.parametrize(
    "kind,receipt",
    [
        ("confirm_delete", {"status": "invalid_confirmation", "deleted_ids": []}),
        ("confirm_delete", {"status": "ok", "deleted_ids": []}),
        ("cancel_delete", {"status": "ok", "cancelled": False, "deleted_ids": []}),
    ],
)
async def test_trusted_action_success_requires_successful_operation_receipt(kind, receipt):
    turn = TurnRecord(step_id="action", kind=kind, status="completed", receipts=[receipt])
    assert (await grade_turn(turn, None, None, [])).status == "FAIL"


@pytest.mark.parametrize("mutation", ["duplicate", "reordered"])
async def test_conversation_coverage_requires_exact_ordered_steps(mutation):
    case = load_cases("date-correction")[0]
    references = {step.id: TurnReference(reference_answer="Ready.") for step in case.steps}
    case = case.model_copy(update={"references": references})
    turns = [
        TurnRecord(
            step_id=step.id,
            prompt=step.message,
            status="approved",
            markdown="Ready.",
            outcome="answer",
        )
        for step in case.steps
    ]
    turns = [*turns, turns[0]] if mutation == "duplicate" else list(reversed(turns))
    trial = Trial(id="coverage-r1", case_id=case.id, repetition=1, status="completed", turns=turns)
    grade = await grade_trial(case, trial, PassingJudge())
    assert grade.status == "ERROR"
    assert any(s.name == "turn_coverage" and s.status == "ERROR" for s in grade.scores)


async def test_unexpected_runtime_failure_retains_unknown_prompt_cost(settings):
    case = load_cases("date-correction")[0]
    calls = []

    def factory(config, identity, **kwargs):
        async def ask(prompt):
            calls.append(prompt)
            raise RuntimeError("Synthetic local failure after unknown remote work")

        return SimpleNamespace(settings=config, ask=ask)

    trial = await run_trial(
        case,
        1,
        settings,
        fixture_path(case),
        remaining_usd=0.25,
        deadline=time.monotonic() + 30,
        app_factory=factory,
    )
    assert trial.accounted_usd == pytest.approx(0.25)
    assert len(calls) == 1
    assert [turn.status for turn in trial.turns] == ["ERROR", "NOT_EXECUTED"]


async def test_capture_errors_are_not_treated_as_complete_observed_evidence(settings):
    case = load_cases("totals-q1")[0]

    def factory(config, identity, **kwargs):
        async def ask(prompt):
            return TurnResult(
                Answer("A1", "Revenue: 798.", [], "answer", True),
                "approved",
                "",
                [],
                {"accounted_usd": 0},
                [],
                0,
            )

        return SimpleNamespace(settings=config, ask=ask, observer_errors=1)

    trial = await run_trial(
        case,
        1,
        settings,
        fixture_path(case),
        remaining_usd=1,
        deadline=time.monotonic() + 30,
        app_factory=factory,
    )
    assert trial.status == "incomplete"
    assert trial.turns[0].status == "ERROR"
    assert "capture" in (trial.turns[0].error or "")


async def test_regrade_rejects_unrecorded_or_modified_execution_output(settings, tmp_path):
    run, _ = prepare_run(
        tmp_path,
        load_cases("totals-q1"),
        settings,
        suite="audit",
        repetitions=1,
        max_cost_usd=1,
        deadline_seconds=30,
    )
    (run / "trials").mkdir()
    (run / "trials/injected.json").write_text("{}")
    with pytest.raises(ValueError, match="modified"):
        await grade_run(run, progress=lambda _: None)


def judge_client(text, *, metadata=None):
    response = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=[types.Part(text=text)]))],
        usage_metadata=metadata,
    )
    return SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=AsyncMock(return_value=response)),
            aclose=AsyncMock(),
        )
    )


async def test_invalid_judge_schema_retains_unknown_cost_and_never_returns_a_grade():
    client = judge_client('{"decision":"approve"}')
    judge = GeminiJudge(
        "offline", EvaluationSettings(), max_cost_usd=1, deadline_seconds=10, client=client
    )
    turn = TurnRecord(
        step_id="ask", status="approved", markdown="Which period?", outcome="clarification"
    )
    reference = TurnReference(reference_answer="Which period?", allowed_outcomes=["clarification"])
    with pytest.raises(JudgeUnavailable):
        await judge.evaluate(turn, reference, [])
    assert judge.accounted_usd > 0
    assert judge.calls[0]["status"] == "ERROR"
    assert judge.calls[0]["input_tokens"] is None


async def test_judge_timeout_retains_reservation_and_low_budget_does_not_call_provider():
    async def slow(**kwargs):
        await asyncio.sleep(60)

    client = judge_client("")
    client.aio.models.generate_content.side_effect = slow
    judge = GeminiJudge(
        "offline",
        EvaluationSettings(judge_timeout_seconds=0.001),
        max_cost_usd=1,
        deadline_seconds=10,
        client=client,
    )
    turn = TurnRecord(
        step_id="ask", status="approved", markdown="Which period?", outcome="clarification"
    )
    reference = TurnReference(reference_answer="Which period?", allowed_outcomes=["clarification"])
    with pytest.raises(JudgeUnavailable):
        await judge.evaluate(turn, reference, [])
    assert judge.accounted_usd > 0 and len(judge.calls) == 1
    judge.ceiling = judge.accounted_usd
    with pytest.raises(JudgeUnavailable, match="budget"):
        await judge.evaluate(turn, reference, [])
    assert client.aio.models.generate_content.await_count == 1


async def test_judge_settles_malformed_output_using_actual_known_usage():
    client = judge_client("malformed", metadata=usage())
    judge = GeminiJudge(
        "offline", EvaluationSettings(), max_cost_usd=1, deadline_seconds=10, client=client
    )
    with pytest.raises(JudgeUnavailable):
        await judge.evaluate(
            TurnRecord(step_id="ask", status="approved", markdown="Which period?"),
            TurnReference(reference_answer="Which period?"),
            [],
        )
    assert judge.accounted_usd == pytest.approx(0.0005)
    assert judge.calls[0]["input_tokens"] == 100


async def test_candidate_format_defect_counts_in_reviewer_diagnostics():
    reference = TurnReference(
        reference_answer="Two compact tables.",
        criteria=[
            Criterion(
                id="two_tables", kind="format", description="Use two tables.", options={"tables": 2}
            )
        ],
    )
    candidate = TurnRecord(
        step_id="ask", status="incomplete", markdown="One paragraph.", outcome="answer"
    )
    grade = await grade_turn(candidate, reference, PassingJudge(), [], candidate=True)
    assert grade.status == "FAIL"
    assert any(s.name == "format" and s.status == "FAIL" for s in grade.scores)
    assert not any(s.name == "acceptable_outcome" for s in grade.scores)


async def test_injected_provider_timeout_exercises_real_retry_and_keeps_unknown_cost(
    settings, monkeypatch
):
    from retail_insight.runtime.model import LlmRequest

    async def immediate(_seconds):
        return None

    monkeypatch.setattr("retail_insight.runtime.provider.asyncio.sleep", immediate)
    delegate = ScriptedModel(script=[text("Recovered.")])
    boundary = FaultModel(model=delegate.model, delegate=delegate).bind(
        Schedule([Fault(boundary="provider", occurrence=1)])
    )
    budget, events = Budget(settings), []
    model = AccountedModel(model=boundary.model, delegate=boundary).bind(
        budget,
        lambda event, **fields: events.append({"event": event, **fields}),
    )
    request = LlmRequest(
        contents=[types.Content(role="user", parts=[types.Part(text="Describe revenue.")])],
        config=types.GenerateContentConfig(max_output_tokens=128),
    )
    responses = [response async for response in model.generate_content_async(request)]
    assert len(responses) == 1 and len(delegate.requests) == 1
    assert budget.model_calls == 2
    assert budget.reserved_usd > 0 and budget.spent_usd == pytest.approx(0.0005)
    failures = [event for event in events if event["event"] == "provider_failure"]
    assert failures == [
        {"event": "provider_failure", "role": "analyst", "code": "ReadTimeout", "retryable": True}
    ]
