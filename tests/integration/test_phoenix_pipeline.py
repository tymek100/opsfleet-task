"""Opt-in real Phoenix pipeline checks; every model response is a local control."""

import pytest

from evaluation.data import load_cases
from evaluation.graders.trajectory import CRITERIA, TrajectoryJudgment, event_catalog
from evaluation.reporting.phoenix import PhoenixPublisher, client_for
from evaluation.results import Claim, CriterionFinding, ExtractedFact, Judgment
from evaluation.runners.artifacts import read_json
from evaluation.runners.pipeline import run_pipeline
from evaluation.settings import EvaluationSettings
from retail_insight.agents.retail.agent import RetailAnalyst as Analyst
from tests.support.models import ScriptedModel, calls, finish, verdict

pytestmark = [pytest.mark.phoenix, pytest.mark.enable_socket]

ANSWER = "Calvin Klein Q1 2026 revenue: 798; customers: 12; orders: 20; AOV: 39.9 [E1]."


class ControlledJudge:
    """Check plumbing and attribution, without claiming model quality or calibration."""

    accounted_usd = 0.0

    def __init__(self):
        self.version = {"model": "controlled-local-judge", "human_calibrated": False}
        self.calls = []
        self.closed = False

    async def evaluate(self, turn, reference, prior):
        self.calls.append({"kind": "answer", "step_id": turn.step_id})
        return Judgment(
            facts=[
                ExtractedFact(id=key, value=value, span=ANSWER)
                for key, value in {
                    "q1_revenue": "798",
                    "q1_customers": "12",
                    "q1_orders": "20",
                    "q1_aov": "39.9",
                }.items()
            ],
            claims=[
                Claim(
                    span=ANSWER,
                    label="SUPPORTED",
                    evidence_ids=["E1"],
                    reason="Controlled integration assertion, not an independent quality judgment.",
                )
            ],
            criteria=[
                CriterionFinding(id=item.id, passed=True, finding="Controlled integration check")
                for item in reference.criteria
                if item.kind == "semantic"
            ],
            response_kind="substantive",
            coverage_complete=True,
        )

    async def evaluate_trajectory(self, trial):
        self.calls.append({"kind": "trajectory", "trial_id": trial.id})
        events = event_catalog(trial)
        selected = next(key for key, event in events.items() if event["event"] == "tool_call")
        return TrajectoryJudgment.model_validate(
            {
                "findings": [
                    {
                        "criterion": criterion,
                        "status": "PASS",
                        "explanation": "Controlled integration check of annotation attribution.",
                        "event_ids": [selected],
                    }
                    for criterion in CRITERIA
                ],
                "assessed_event_ids": list(events),
                "coverage_complete": True,
                "summary": "Controlled output, not a model quality assessment.",
            }
        )

    async def close(self):
        self.closed = True


async def test_pipeline_publishes_before_inference_and_annotations_during_execution(
    settings, tmp_path, phoenix_url
):
    config = EvaluationSettings(artifact_root=tmp_path, phoenix_url=phoenix_url)
    checkpoints = []
    progress = []

    class ObservedPublisher(PhoenixPublisher):
        def start(self):
            state = super().start()
            assert state["url"] and state["traces_url"]
            assert not list((self.run / "trials").glob("*.json"))
            assert self.client.projects.get(project_name=self.project)["id"] == state["project_id"]
            checkpoints.append("ready")
            return state

        def publish_trial(self, trial):
            assert read_json(self.run / "manifest.json")["status"] == "running"
            state = super().publish_trial(trial)
            assert state["status"] == "published", state
            experiment = self.client.experiments.get(experiment_id=state["experiment_id"])
            assert experiment["successful_run_count"] == trial.repetition
            checkpoints.append(f"trial-{trial.repetition}")
            return state

        def publish_grade(self, grade_dir, grade):
            assert read_json(self.run / "manifest.json")["status"] == "running"
            state = super().publish_grade(grade_dir, grade)
            assert state["status"] == "published", state
            checkpoints.append(f"grade-{grade.repetition}")
            return state

    def factory(config, identity, **kwargs):
        # The first model cannot start until an inspectable remote experiment exists.
        assert checkpoints[0] == "ready"
        assert any(message.startswith("Phoenix experiment:") for message in progress)
        assert any(message.startswith("Phoenix traces:") for message in progress)
        return Analyst(
            config,
            identity,
            model=ScriptedModel(
                script=[
                    calls(
                        (
                            "query_data",
                            {
                                "sql": "SELECT SUM(sale_price) AS revenue, COUNT(DISTINCT user_id) AS customers, COUNT(DISTINCT order_id) AS orders, SUM(sale_price) / COUNT(DISTINCT order_id) AS aov FROM sales WHERE purchased_at >= TIMESTAMP '2026-01-01' AND purchased_at < TIMESTAMP '2026-04-01'",
                                "purpose": "Calculate Q1 metrics",
                            },
                        )
                    ),
                    finish(ANSWER, ["E1"]),
                ]
            ),
            reviewer_model=ScriptedModel(script=[verdict()]),
            **kwargs,
        )

    judge = ControlledJudge()
    result = await run_pipeline(
        load_cases("totals-q1"),
        settings,
        config,
        suite="phoenix-pipeline-integration",
        repetitions=2,
        max_cost_usd=1,
        deadline_seconds=60,
        judge=judge,
        grade_candidates=False,
        app_factory=factory,
        publisher_factory=ObservedPublisher,
        progress=progress.append,
    )
    assert checkpoints == ["ready", "trial-1", "grade-1", "trial-2", "grade-2"]
    assert result.exit_code == 0, result.summary
    assert judge.closed
    assert result.publication["status"] == "published"
    assert result.summary["statuses"] == {"PASS": 2}
    client = client_for(config)
    for path in sorted((result.run / "trials").glob("*.json")):
        trial = read_json(path)
        turn = trial["turns"][0]
        assert turn["trace_id"] == trial["trace_id"]
        assert turn["span_id"] != trial["span_id"]
        annotations = client.spans.get_span_annotations(
            project_identifier=result.run.name,
            span_ids=[trial["span_id"], turn["span_id"]],
            timeout=3,
        )
        assert any(
            item["span_id"] == trial["span_id"]
            and item["name"] == "trial/trajectory/tool_selection/overall"
            and item["annotator_kind"] == "LLM"
            for item in annotations
        )
        assert any(
            item["span_id"] == turn["span_id"]
            and item["name"] == "turn-1/claim_support/overall"
            and item["annotator_kind"] == "LLM"
            for item in annotations
        )
        assert all(item.get("identifier") == result.grade.name for item in annotations)
