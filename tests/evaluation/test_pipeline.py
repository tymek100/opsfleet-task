"""One-command lifecycle and shared limits around the real agent and local tools."""

import time
from functools import partial

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from evaluation.data import load_cases
from evaluation.graders.judge import JudgeUnavailable
from evaluation.graders.trajectory import CRITERIA, TrajectoryJudgment, event_catalog
from evaluation.reporting.phoenix_service import PhoenixUnavailable
from evaluation.results import Claim, CriterionFinding, Judgment
from evaluation.runners.artifacts import read_json, write_json
from evaluation.runners.pipeline import outcome_code, run_pipeline
from evaluation.settings import EvaluationSettings
from retail_agent.observability import configure_tracing
from retail_agent.runtime import Analyst
from tests.support.models import ScriptedModel, finish, verdict


class ControlledJudge:
    """Fixed protocol responses verify orchestration, not semantic judge quality."""

    def __init__(self, events, *, trajectory_fails=False):
        self.events = events
        self.accounted_usd = 0
        self.ceiling = 0
        self.deadline = 0
        self.calls = []
        self.closed = False
        self.trajectory_fails = trajectory_fails
        self.version = {"mode": "controlled-test-double"}

    def charge(self, kind):
        if time.monotonic() >= self.deadline or self.accounted_usd + 0.2 > self.ceiling:
            raise JudgeUnavailable("Shared test allowance exhausted")
        self.accounted_usd += 0.2
        self.calls.append({"kind": kind, "accounted_usd": 0.2})
        self.events.append(kind)

    async def evaluate(self, turn, reference, prior):
        self.charge("answer")
        return Judgment(
            facts=[],
            claims=[Claim(span=turn.markdown, label="NOT_FACTUAL", reason="Clarification")],
            criteria=[
                CriterionFinding(
                    id=criterion.id,
                    passed=True,
                    finding="Controlled test response",
                    spans=[turn.markdown],
                )
                for criterion in reference.criteria
            ],
            response_kind="clarification",
            coverage_complete=True,
        )

    async def evaluate_trajectory(self, trial):
        self.charge("trajectory")
        ids = list(event_catalog(trial))
        return TrajectoryJudgment.model_validate(
            {
                "findings": [
                    {
                        "criterion": criterion,
                        "status": "FAIL"
                        if self.trajectory_fails and criterion == "progress"
                        else "PASS",
                        "explanation": "Controlled test response",
                        "event_ids": ids[:1],
                    }
                    for criterion in CRITERIA
                ],
                "assessed_event_ids": ids,
                "coverage_complete": True,
                "summary": "Controlled test response",
            }
        )

    async def close(self):
        self.closed = True


def harness(settings, tmp_path, *, fail_upload=False, trajectory_fails=False):
    events = []
    allowances = []
    case = load_cases("period-clarification")[0]
    # One authentic clarification step is enough to exercise the complete lifecycle.
    case = case.model_copy(
        update={"steps": case.steps[:1], "references": {"turn-1": case.references["turn-1"]}}
    )

    class Publisher:
        def __init__(self, run, config, *, deadline, project):
            self.run = run

        def save(self, status):
            state = {
                "status": status,
                "url": "http://localhost:6006/experiment",
                "traces_url": "http://localhost:6006/traces",
            }
            write_json(self.run / "phoenix.json", state)
            return state

        def start(self):
            events.append("experiment")
            return self.save("ready")

        def publish_trial(self, trial):
            assert (self.run / "trials" / f"{trial.id}.json").exists()
            events.append("publish-trial")
            return self.save("publication_failed" if fail_upload else "published")

        def publish_grade(self, grade_dir, grade):
            assert (grade_dir / "trials" / f"{grade.trial_id}.json").exists()
            events.append("publish-grade")
            return self.save("publication_failed" if fail_upload else "published")

    def factory(config, identity, **kwargs):
        def respond(_):
            events.append("agent")
            allowances.append(analyst.settings.question_budget_usd)
            return finish("Which reporting period should I use?", outcome="clarification")

        analyst = Analyst(
            config,
            identity,
            model=ScriptedModel(script=[respond]),
            reviewer_model=ScriptedModel(script=[verdict()]),
            **kwargs,
        )
        return analyst

    judge = ControlledJudge(events, trajectory_fails=trajectory_fails)
    arguments = {
        "cases": [case],
        "settings": settings,
        "config": EvaluationSettings(artifact_root=tmp_path / "runs"),
        "suite": "controlled",
        "repetitions": 2,
        "max_cost_usd": 2,
        "deadline_seconds": 30,
        "judge": judge,
        "app_factory": factory,
        "publisher_factory": Publisher,
        "service": lambda *args, **kwargs: events.append("service"),
        "tracing_factory": partial(configure_tracing, exporter=InMemorySpanExporter()),
        "prompts_sync": lambda *args, **kwargs: [],
        "progress": lambda text: events.append("link") if "Phoenix " in text else None,
    }
    return arguments, events, allowances, judge


async def test_links_precede_inference_and_each_trial_is_published_and_graded(settings, tmp_path):
    arguments, events, allowances, judge = harness(settings, tmp_path)
    result = await run_pipeline(**arguments)
    assert result.exit_code == 0
    assert events == [
        "service",
        "experiment",
        "link",
        "link",
        "agent",
        "publish-trial",
        "answer",
        "answer",
        "trajectory",
        "publish-grade",
        "agent",
        "publish-trial",
        "answer",
        "answer",
        "trajectory",
        "publish-grade",
    ]
    assert judge.closed
    trials = [read_json(path) for path in sorted((result.run / "trials").glob("*.json"))]
    assert allowances[1] == pytest.approx(2 - trials[0]["accounted_usd"] - 0.6)
    assert result.summary["accounted_total_usd"] == pytest.approx(
        sum(trial["accounted_usd"] for trial in trials) + judge.accounted_usd
    )
    assert result.summary["trajectory"]["statuses"] == {"PASS": 2}
    for trial in trials:
        turn = trial["turns"][0]
        assert trial["trace_id"] == turn["trace_id"] and trial["span_id"] != turn["span_id"]
        actions = [event for event in turn["timeline"] if event["event"] == "tool_call"]
        assert actions[0]["name"] == "finish_answer"
        assert actions[0]["args"]["outcome"] == "clarification"
        assert turn["context"]["available_tools"]
    assert read_json(result.grade / "manifest.json")["status"] == "completed"


async def test_judge_exhaustion_preserves_answers_and_does_not_reset_allowance(settings, tmp_path):
    arguments, _, allowances, judge = harness(settings, tmp_path)
    arguments.update(max_cost_usd=0.61)
    result = await run_pipeline(**arguments)
    assert result.exit_code == 2
    assert result.summary["trajectory"]["unresolved"] >= 1
    assert result.summary["accounted_total_usd"] <= 0.61
    assert judge.accounted_usd == pytest.approx(0.6)
    assert len(allowances) == 1  # insufficient admission allowance on the second prompt
    trials = sorted((result.run / "trials").glob("*.json"))
    assert len(trials) == 2 and read_json(trials[0])["turns"][0]["markdown"]


async def test_deadline_spent_on_setup_prevents_inference(settings, tmp_path, monkeypatch):
    arguments, events, _, judge = harness(settings, tmp_path)
    now = [time.monotonic()]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    arguments["service"] = lambda *args, **kwargs: now.__setitem__(0, now[0] + 31)
    result = await run_pipeline(**arguments)
    assert "agent" not in events and judge.calls == []
    assert result.exit_code == 2
    assert result.summary["not_executed"] == 2


async def test_unavailable_phoenix_stops_before_inference(settings, tmp_path):
    arguments, events, _, judge = harness(settings, tmp_path)

    def unavailable(*args, **kwargs):
        raise PhoenixUnavailable("Controlled startup failure")

    arguments["service"] = unavailable
    with pytest.raises(PhoenixUnavailable):
        await run_pipeline(**arguments)
    assert events == [] and judge.closed


async def test_prompt_sync_failure_stops_before_inference_and_preserves_run(settings, tmp_path):
    arguments, events, _, judge = harness(settings, tmp_path)

    def unavailable(*args, **kwargs):
        raise ConnectionError("Controlled prompt registry outage")

    arguments["prompts_sync"] = unavailable
    with pytest.raises(PhoenixUnavailable, match="Prompt synchronization failed"):
        await run_pipeline(**arguments)
    assert "agent" not in events and judge.calls == [] and judge.closed
    manifest = next((tmp_path / "runs").glob("*/manifest.json"))
    assert read_json(manifest)["pipeline"]["status"] == "interrupted"


async def test_publication_failure_keeps_local_grades_and_returns_incomplete(settings, tmp_path):
    arguments, _, _, _ = harness(settings, tmp_path, fail_upload=True)
    result = await run_pipeline(**arguments)
    assert result.exit_code == 2
    assert result.summary["statuses"] == {"PASS": 2}
    assert len(list((result.grade / "trials").glob("*.json"))) == 2
    assert read_json(result.run / "manifest.json")["pipeline"]["status"] == "incomplete"


async def test_trajectory_diagnostic_failure_is_reported_without_changing_answer_success(
    settings, tmp_path
):
    arguments, _, _, _ = harness(settings, tmp_path, trajectory_fails=True)
    result = await run_pipeline(**arguments)
    assert result.exit_code == 1
    assert result.summary["statuses"] == {"PASS": 2}
    assert result.summary["trajectory"]["statuses"] == {"FAIL": 2}


def test_unresolved_trajectory_takes_precedence_over_observed_failure():
    assert (
        outcome_code(
            {
                "statuses": {"FAIL": 1},
                "unresolved_or_missing": 0,
                "trajectory": {"statuses": {"FAIL": 1}, "unresolved": 1},
            },
            {"status": "published"},
        )
        == 2
    )


@pytest.mark.parametrize(
    "unresolved",
    [
        {"unresolved_required_checks": 1},
        {"candidate_grading": {"unresolved": 1}},
        {"candidate_grading": {"missing": 1}},
    ],
)
def test_unresolved_grading_takes_precedence_over_known_failure(unresolved):
    assert (
        outcome_code(
            {"statuses": {"FAIL": 1}, "unresolved_or_missing": 0, **unresolved},
            {"status": "published"},
        )
        == 2
    )
