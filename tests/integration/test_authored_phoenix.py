"""Reference revisions and a complete authored evaluation against disposable Phoenix."""

import json
from typing import ClassVar
from uuid import uuid4

import pytest

from evaluation.conversation_references import bundle
from evaluation.graders.trajectory import (
    CRITERIA,
    TrajectoryFinding,
    TrajectoryJudgment,
    event_catalog,
)
from evaluation.reporting.conversations import ensure_dataset
from evaluation.reporting.phoenix import client_for
from evaluation.results import Claim, CriterionFinding, ExtractedFact, Judgment
from evaluation.runners.artifacts import read_json
from evaluation.runners.authored import run_authored
from evaluation.settings import EvaluationSettings
from retail_agent.runtime import Analyst
from tests.evaluation.test_authored_grading import scenarios, snapshot  # noqa: F401
from tests.support.models import ScriptedModel, finish, verdict

pytestmark = [pytest.mark.phoenix, pytest.mark.enable_socket]


async def test_reference_versions_preserve_examples_and_e2e_scores(
    snapshot,  # noqa: F811
    scenarios,  # noqa: F811
    settings,
    tmp_path,
    phoenix_url,
    monkeypatch,
):
    monkeypatch.setattr(
        "evaluation.reporting.conversations.DATASET_NAME", "authored-test-" + uuid4().hex
    )
    config = EvaluationSettings(phoenix_url=phoenix_url)
    client = client_for(config)
    cases = list(scenarios.values())
    old = ensure_dataset(client, cases)
    old_outputs = {e["id"]: e["output"] for e in old.examples}
    references = bundle(cases, snapshot)
    revised = ensure_dataset(client, cases, references)
    assert revised.version_id != old.version_id
    assert {e["id"] for e in revised.examples} == set(old_outputs)
    historical = client.datasets.get_dataset(dataset=old.id, version_id=old.version_id)
    assert {e["id"]: e["output"] for e in historical.examples} == old_outputs
    assert ensure_dataset(client, cases, references).version_id == revised.version_id
    assert ensure_dataset(client, cases).version_id == revised.version_id  # No downgrade.

    models = []

    def factory(configured, identity, **kwargs):
        assert kwargs["gateway"].snapshot_at.isoformat() == snapshot.manifest["snapshot_at"]
        model = ScriptedModel(script=[finish("Revenue: 999."), finish("Hypothetical EUR: 469.20.")])
        models.append(model)
        return Analyst(
            configured,
            identity,
            model=model,
            reviewer_model=ScriptedModel(script=[verdict(), verdict()]),
            **kwargs,
        )

    class ControlledJudge:
        version: ClassVar = {"model": "controlled-boundary"}

        def __init__(self):
            self.accounted_usd = 0.0
            self.calls = []
            self.closed = False

        async def evaluate(self, turn, reference, prior):
            self.accounted_usd += 0.01
            self.calls.append({"kind": "answer"})
            return Judgment(
                response_kind="substantive",
                coverage_complete=True,
                facts=[
                    ExtractedFact(
                        id=reference.facts[0].id,
                        span=turn.markdown,
                        value="999" if turn.step_id == "turn-1" else "469.20",
                    )
                ],
                claims=[
                    Claim(
                        span=turn.markdown,
                        label="UNSUPPORTED",
                        evidence_ids=[],
                        reason="The model never queried the warehouse.",
                    )
                ],
                criteria=[
                    CriterionFinding(id=c.id, passed=True, finding="Controlled judgment")
                    for c in reference.criteria
                    if c.kind == "semantic"
                ],
            )

        async def evaluate_trajectory(self, trial):
            ids = list(event_catalog(trial))
            self.accounted_usd += 0.01
            self.calls.append({"kind": "trajectory"})
            return TrajectoryJudgment(
                coverage_complete=True,
                assessed_event_ids=ids,
                summary="Controlled diagnosis",
                findings=[
                    TrajectoryFinding(
                        criterion=c,
                        status="FAIL",
                        event_ids=ids,
                        explanation="Answered without checking current facts.",
                    )
                    for c in CRITERIA
                ],
            )

        async def close(self):
            self.closed = True

    judge = ControlledJudge()
    run, summary = await run_authored(
        [scenarios["scenario-15"]],
        settings,
        config,
        max_cost_usd=1,
        deadline_seconds=90,
        reference_directory=snapshot.directory,
        output_root=tmp_path / "runs",
        judge=judge,
        app_factory=factory,
        progress=lambda _: None,
    )
    assert judge.closed and len(judge.calls) == 3
    assert summary["exit_code"] == 1 and summary["publication_status"] == "published"
    assert summary["accounted_total_usd"] >= 0.03
    assert "510" not in json.dumps(models[0].requests)
    grade = read_json(run / "automatic/scenario-15.json")
    assert grade["turns"][0]["status"] == "FAIL"
    assert any(
        s["name"] == "numeric_fact" and s["status"] == "FAIL" for s in grade["turns"][0]["scores"]
    )
    state = read_json(run / "phoenix-auto.json")
    experiment = client.experiments.get_experiment(experiment_id=state["experiment_id"])
    assert len(experiment["task_runs"]) == 1
    output = experiment["task_runs"][0]["output"]
    assert output["initial"]["answer"] == "Revenue: 999."
    assert output["initial"]["runtime_status"] == "approved"
    assert output["evaluation"]["status"] == "FAIL"
    spans = client.spans.get_spans(
        project_identifier=state["project_id"],
        trace_ids=[read_json(run / "cases/scenario-15/turn-1.json")["trace_id"]],
        name="retail.prompt",
        limit=5,
    )
    assert len(spans) == 1
    attrs = spans[0].get("attributes", {})
    actual_input = attrs.get("input.value") or attrs.get("input", {}).get("value")
    actual_output = attrs.get("output.value") or attrs.get("output", {}).get("value")
    assert actual_input == scenarios["scenario-15"].prompt
    assert actual_output == "Revenue: 999."
    assert spans[0]["status_code"] == "OK"  # Execution status is independent of FAIL quality.
    assert attrs["retail.case_id"] == "scenario-15" and attrs["retail.step_id"] == "turn-1"
    assert len(experiment["evaluation_runs"]) == 11
    assert all(
        isinstance(e.result, dict) and e.result.get("label") != "PENDING"
        for e in experiment["evaluation_runs"]
    )
    assert len(client.datasets.get_dataset(dataset=old.id).examples) == 20
