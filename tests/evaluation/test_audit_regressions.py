"""Adversarial controls for false passes, missing capture, and publication boundaries."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from google.genai import types

from evaluation.data import fixture_path, load_cases
from evaluation.graders.judge import GeminiJudge, JudgeUnavailable
from evaluation.graders.runner import grade_run, grade_trial, grade_turn
from evaluation.models import Criterion, Fault, TurnReference
from evaluation.reporting.phoenix import publish, sync_cases
from evaluation.results import Claim, Judgment, Trial, TurnRecord
from evaluation.runners.artifacts import digest, prepare_run, read_json, write_json
from evaluation.runners.conversation import run_trial
from evaluation.runners.faults import FaultModel, Schedule
from evaluation.settings import EvaluationSettings
from retail_agent.budget import Budget
from retail_agent.contracts import Answer, TurnResult
from retail_agent.provider import AccountedModel
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
        {"id": "delete-me", "owner": "alice", "title": seed.title, "markdown": seed.markdown}
        for seed in case.initial_reports[:1]
    ] + [
        {
            "id": "keep-me",
            "owner": "alice",
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


def phoenix_client():
    client = MagicMock()
    client.datasets.get_dataset.side_effect = ValueError("Dataset not found: synthetic")

    def create(**kwargs):
        examples = [
            {"id": f"example-{index}", "input": source, "output": output, "metadata": metadata}
            for index, (source, output, metadata) in enumerate(
                zip(kwargs["inputs"], kwargs["outputs"], kwargs["metadata"], strict=True)
            )
        ]
        return SimpleNamespace(id="dataset", version_id="version", examples=examples)

    client.datasets.create_dataset.side_effect = create
    return client


def test_phoenix_redacts_inputs_metadata_and_outputs_before_upload():
    case = load_cases("totals-q1")[0].model_copy(deep=True)
    case.steps[0].message += " /confirm INPUT_CANARY"
    case.provenance.notes = "Bearer METADATA_CANARY"
    case.references[case.steps[0].id].reference_answer += " /confirm OUTPUT_CANARY"
    client = phoenix_client()
    sync_cases([case], EvaluationSettings(), client=client)
    payload = json.dumps(client.datasets.create_dataset.call_args.kwargs)
    for canary in ("INPUT_CANARY", "METADATA_CANARY", "OUTPUT_CANARY"):
        assert canary not in payload
    assert "[REDACTED]" in payload


def test_remote_dataset_edits_cannot_reuse_an_unchanged_checksum():
    case = load_cases("totals-q1")[0]
    client = phoenix_client()
    dataset = sync_cases([case], EvaluationSettings(), client=client)
    dataset.examples[0]["output"] = {"references": "Silently edited ground truth"}
    client.datasets.get_dataset.side_effect = None
    client.datasets.get_dataset.return_value = dataset
    with pytest.raises(ValueError, match="differs"):
        sync_cases([case], EvaluationSettings(), client=client)


def test_phoenix_outage_records_failure_without_destroying_local_artifacts(settings, tmp_path):
    run, _ = prepare_run(
        tmp_path,
        load_cases("totals-q1"),
        settings,
        suite="audit",
        repetitions=1,
        max_cost_usd=1,
        deadline_seconds=30,
    )
    before = (run / "manifest.json").read_bytes()
    client = phoenix_client()
    client.datasets.get_dataset.side_effect = httpx.ConnectError("Synthetic Phoenix outage")
    result = publish(run, EvaluationSettings(), client=client)
    assert result["status"] == "publication_failed"
    assert result["error"] == "ConnectError"
    assert read_json(run / "phoenix.json") == result
    assert (run / "manifest.json").read_bytes() == before


def test_expired_publication_deadline_does_not_send_network_requests(settings, tmp_path):
    run, _ = prepare_run(
        tmp_path,
        load_cases("totals-q1"),
        settings,
        suite="audit",
        repetitions=1,
        max_cost_usd=1,
        deadline_seconds=30,
    )
    client = phoenix_client()
    result = publish(run, EvaluationSettings(), client=client, deadline_seconds=0)
    assert result["status"] == "publication_failed"
    client.datasets.get_dataset.assert_not_called()


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


def test_phoenix_run_error_and_full_output_are_sanitized(settings, tmp_path):
    case = load_cases("totals-q1")[0]
    run, manifest = prepare_run(
        tmp_path,
        [case],
        settings,
        suite="audit",
        repetitions=1,
        max_cost_usd=1,
        deadline_seconds=30,
    )
    trial = Trial(
        id=f"{case.id}-r1",
        case_id=case.id,
        repetition=1,
        status="ERROR",
        started_at="2026-11-22T00:00:00+00:00",
        ended_at="2026-11-22T00:00:01+00:00",
        error="Bearer ERROR_CANARY",
        turns=[TurnRecord(step_id="turn-1", status="ERROR", prompt="/confirm PROMPT_CANARY")],
    )
    path = run / "trials" / f"{trial.id}.json"
    write_json(path, trial)
    manifest.trials_sha256[path.name] = digest(path)
    write_json(run / "manifest.json", manifest)
    client = phoenix_client()
    client.experiments.create.return_value = {"id": "experiment"}
    client.experiments.log_run.return_value = {"id": "remote-run"}
    client.experiments.get_experiment_url.return_value = "http://127.0.0.1:6006/experiment"
    assert publish(run, EvaluationSettings(), client=client)["status"] == "published"
    sent = json.dumps(client.experiments.log_run.call_args.kwargs, default=str)
    assert "ERROR_CANARY" not in sent and "PROMPT_CANARY" not in sent
    assert read_json(path)["error"] == "Bearer ERROR_CANARY"


def test_phoenix_rejects_grading_from_another_execution_before_upload(settings, tmp_path):
    run, _ = prepare_run(
        tmp_path,
        load_cases("totals-q1"),
        settings,
        suite="audit",
        repetitions=1,
        max_cost_usd=1,
        deadline_seconds=30,
    )
    grade = run / "grades" / "wrong-run"
    write_json(grade / "manifest.json", {"run_id": "another-execution"})
    client = phoenix_client()
    result = publish(run, EvaluationSettings(), grade=grade, client=client)
    assert result["status"] == "publication_failed"
    client.datasets.get_dataset.assert_not_called()


async def test_injected_provider_timeout_exercises_real_retry_and_keeps_unknown_cost(
    settings, monkeypatch
):
    from google.adk.models.llm_request import LlmRequest

    async def immediate(_seconds):
        return None

    monkeypatch.setattr("retail_agent.provider.asyncio.sleep", immediate)
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
