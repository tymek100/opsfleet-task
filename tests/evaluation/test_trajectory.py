"""Trajectory attribution, capture boundaries, and shared judge accounting."""

import json
from types import SimpleNamespace

import pytest
from google.genai import types

from evaluation.graders.judge import GeminiJudge, JudgeUnavailable
from evaluation.graders.runner import grade_trial, prepare_grade, record_grade
from evaluation.graders.trajectory import (
    CRITERIA,
    TrajectoryJudgment,
    capture_problem,
    event_catalog,
    trajectory_input,
    validate_judgment,
)
from evaluation.models import Case, Step, TurnReference
from evaluation.results import Claim, Judgment, Trial, TurnRecord
from evaluation.runners.artifacts import digest, prepare_run, read_json, write_json
from evaluation.settings import EvaluationSettings


def captured_trial() -> Trial:
    context = {"trusted_scope": "Calvin Klein", "user_question": "Which period?"}
    timeline = [
        {"event": "initial_context", "context": context},
        {
            "event": "available_tools",
            "available_tools": [{"name": "finish_answer", "description": "Submit reviewed output"}],
        },
        {
            "event": "tool_call",
            "name": "finish_answer",
            "args": {"markdown": "Which period?", "outcome": "clarification", "evidence_ids": []},
        },
        {
            "event": "answer_candidate",
            "candidate": {"markdown": "Which period?"},
            "evidence": [{"rows": [{"unobserved": "HIDDEN_REVIEWER_EVIDENCE_CANARY"}]}],
        },
        {"event": "review_result", "review": {"decision": "approve"}},
        {
            "event": "turn_result",
            "capture_errors": 0,
            "result": {
                "status": "approved",
                "evidence": [{"rows": [{"unobserved": "HIDDEN_FULL_RESULT_CANARY"}]}],
            },
        },
    ]
    return Trial(
        id="clarify-r1",
        case_id="clarify",
        repetition=1,
        status="completed",
        turns=[
            TurnRecord(
                step_id="ask",
                prompt="Which period should I use?",
                status="approved",
                markdown="Which period?",
                outcome="clarification",
                context=context,
                timeline=timeline,
                trace_id="1" * 32,
                span_id="2" * 16,
            )
        ],
    )


def assessment(trial, *, fail=False) -> TrajectoryJudgment:
    return TrajectoryJudgment.model_validate(
        {
            "findings": [
                {
                    "criterion": criterion,
                    "status": "FAIL" if fail and criterion == "progress" else "PASS",
                    "explanation": "Controlled evaluator output; not a real quality judgment.",
                    "event_ids": ["ask:e3"],
                }
                for criterion in CRITERIA
            ],
            "assessed_event_ids": list(event_catalog(trial)),
            "coverage_complete": True,
            "summary": "Controlled assessment.",
        }
    )


class Client:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self.generate))

    async def generate(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def response(payload):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(parts=[types.Part(text=json.dumps(payload))]))
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100,
            candidates_token_count=50,
            thoughts_token_count=20,
            total_token_count=170,
        ),
    )


def test_payload_uses_observed_events_without_hidden_result_bundle_or_references():
    trial = captured_trial()
    assert capture_problem(trial) is None
    payload = trajectory_input(trial)
    encoded = json.dumps(payload)
    assert "HIDDEN_FULL_RESULT_CANARY" not in encoded
    assert "HIDDEN_REVIEWER_EVIDENCE_CANARY" not in encoded
    assert "reference_answer" not in encoded and "source_key" not in encoded
    events = payload["untrusted_execution"]["events"]
    assert list(events) == [f"ask:e{index}" for index in range(1, 7)]
    assert events["ask:e3"]["args"]["outcome"] == "clarification"
    assert events["ask:e2"]["available_tools"][0]["name"] == "finish_answer"


@pytest.mark.parametrize("mutation", ["unknown", "duplicate", "missing", "unassessed"])
def test_invalid_event_attribution_cannot_be_a_valid_judgment(mutation):
    trial = captured_trial()
    result = assessment(trial)
    if mutation == "unknown":
        result.findings[0].event_ids = ["ask:e999"]
    elif mutation == "duplicate":
        result.findings.append(result.findings[0])
    elif mutation == "missing":
        result.findings[0].event_ids = []
    else:
        result.assessed_event_ids.remove("ask:e3")
    with pytest.raises(ValueError):
        validate_judgment(result, trial)


def test_incomplete_judge_coverage_is_not_claimed_complete():
    trial = captured_trial()
    result = assessment(trial)
    result.coverage_complete = False
    result.assessed_event_ids = ["ask:e3"]
    validate_judgment(result, trial)
    from evaluation.graders.trajectory import scores

    coverage = next(score for score in scores(result) if score.name == "trajectory/coverage")
    assert coverage.status == "UNJUDGEABLE" and not coverage.blocks_success


@pytest.mark.parametrize("missing", ["timeline", "tools", "end"])
async def test_missing_capture_never_calls_the_trajectory_judge(missing):
    trial = captured_trial()
    if missing == "timeline":
        trial.turns[0].timeline = []
    elif missing == "tools":
        trial.turns[0].timeline.pop(1)
    else:
        trial.turns[0].timeline.pop()
    client = Client(AssertionError("No provider call is permitted"))
    judge = GeminiJudge(
        "test-key", EvaluationSettings(), max_cost_usd=1, deadline_seconds=10, client=client
    )
    with pytest.raises(JudgeUnavailable):
        await judge.evaluate_trajectory(trial)
    assert client.requests == [] and judge.accounted_usd == 0


async def test_trajectory_and_answer_judging_share_one_budget_ledger():
    trial = captured_trial()
    client = Client(response(assessment(trial).model_dump(mode="json")))
    judge = GeminiJudge(
        "test-key", EvaluationSettings(), max_cost_usd=1, deadline_seconds=10, client=client
    )
    await judge.evaluate_trajectory(trial)
    assert judge.accounted_usd == pytest.approx((100 * 2 + 70 * 12) / 1e6)
    assert judge.calls[0]["kind"] == "trajectory"
    judge.ceiling = judge.accounted_usd + 0.000001
    with pytest.raises(JudgeUnavailable, match="budget"):
        await judge.evaluate(trial.turns[0], TurnReference(reference_answer="Which period?"), [])
    assert len(client.requests) == 1


async def test_fabricated_trajectory_reference_is_error_with_settled_usage():
    trial = captured_trial()
    payload = assessment(trial).model_dump(mode="json")
    payload["findings"][0]["event_ids"] = ["ask:e999"]
    client = Client(response(payload))
    judge = GeminiJudge(
        "test-key", EvaluationSettings(), max_cost_usd=1, deadline_seconds=10, client=client
    )
    with pytest.raises(JudgeUnavailable, match="unobserved"):
        await judge.evaluate_trajectory(trial)
    assert judge.calls[0]["error_stage"] == "attribution"
    assert judge.accounted_usd == pytest.approx((100 * 2 + 70 * 12) / 1e6)


async def test_diagnostic_trajectory_failure_preserves_answer_grade_and_event_links():
    trial = captured_trial()

    class Judge:
        async def evaluate(self, turn, reference, prior):
            return Judgment(
                facts=[],
                claims=[Claim(span="Which period?", label="NOT_FACTUAL", reason="Clarification")],
                criteria=[],
                response_kind="clarification",
                coverage_complete=True,
            )

        async def evaluate_trajectory(self, trial):
            return assessment(trial, fail=True)

    case = Case.model_construct(
        id=trial.case_id,
        identity="alice",
        steps=[Step(id="ask", message=trial.turns[0].prompt)],
        references={
            "ask": TurnReference(
                reference_answer="Which period?", allowed_outcomes=["clarification"]
            )
        },
        expected_report_count=0,
    )
    grade = await grade_trial(case, trial, Judge(), grade_trajectory=True)
    assert grade.status == "PASS"
    assert next(s for s in grade.scores if s.name == "trajectory/progress").status == "FAIL"
    assert grade.trajectory is not None
    assert grade.trajectory["event_sources"]["ask:e3"]["span_id"] == "2" * 16
    trial.turns[0].timeline = []
    incomplete = await grade_trial(case, trial, Judge(), grade_trajectory=True)
    assert incomplete.trajectory is None
    assert (
        next(s for s in incomplete.scores if s.name == "trajectory/assessment").status
        == "UNJUDGEABLE"
    )


def test_incremental_grade_pins_appended_trials_and_rejects_modified_prior_capture(
    settings, tmp_path
):
    from evaluation.data import load_cases
    from evaluation.results import TrialGrade

    directory, manifest = prepare_run(
        tmp_path,
        load_cases("totals-q1"),
        settings,
        suite="control",
        repetitions=1,
        max_cost_usd=1,
        deadline_seconds=30,
    )
    grade_dir = prepare_grade(directory)
    trial = Trial(id="totals-q1-r1", case_id="totals-q1", repetition=1, status="NOT_EXECUTED")
    path = directory / "trials" / f"{trial.id}.json"
    write_json(path, trial)
    manifest.trials_sha256[path.name] = digest(path)
    write_json(directory / "manifest.json", manifest)
    grade = TrialGrade(
        trial_id=trial.id, case_id=trial.case_id, repetition=1, status="UNJUDGEABLE", turns=[]
    )
    record_grade(directory, grade_dir, grade)
    assert read_json(grade_dir / "manifest.json")["trials_sha256"] == manifest.trials_sha256
    trial.error = "tampered"
    write_json(path, trial)
    manifest.trials_sha256[path.name] = digest(path)
    write_json(directory / "manifest.json", manifest)
    with pytest.raises(ValueError, match="changed"):
        record_grade(directory, grade_dir, None, complete=True)
