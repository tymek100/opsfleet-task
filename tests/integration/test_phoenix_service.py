"""Opt-in local collector integration using the real runtime and a scripted provider."""

import asyncio
from uuid import uuid4

import pytest

from evaluation.data import load_cases
from evaluation.graders.runner import grade_run
from evaluation.reporting.phoenix import client_for, publish
from evaluation.runners.artifacts import read_json
from evaluation.runners.conversation import run_cases
from evaluation.settings import EvaluationSettings
from retail_agent.observability import configure_tracing
from retail_agent.runtime import Analyst
from tests.support.models import ScriptedModel, calls, finish, verdict

pytestmark = [pytest.mark.phoenix, pytest.mark.enable_socket]


async def test_local_dataset_experiment_annotations_and_trace(settings, tmp_path):
    project = "retail-integration-" + uuid4().hex[:8]
    tracing = configure_tracing(
        "http://127.0.0.1:6006/v1/traces", project=project, mode="synthetic"
    )

    def factory(config, identity, **kwargs):
        return Analyst(
            config,
            identity,
            model=ScriptedModel(
                script=[
                    calls(
                        (
                            "query_data",
                            {
                                "sql": "SELECT COUNT(DISTINCT user_id) AS customers FROM sales WHERE purchased_at >= TIMESTAMP '2026-01-01' AND purchased_at < TIMESTAMP '2026-04-01'",
                                "purpose": "Count customers",
                            },
                        )
                    ),
                    finish("There were 12 distinct customers [E1].", ["E1"]),
                ]
            ),
            reviewer_model=ScriptedModel(script=[verdict()]),
            **kwargs,
        )

    try:
        run = await run_cases(
            load_cases("totals-q1"),
            settings,
            artifact_root=tmp_path,
            suite="phoenix-integration",
            repetitions=1,
            max_cost_usd=1,
            deadline_seconds=30,
            app_factory=factory,
            progress=lambda _: None,
        )
    finally:
        assert tracing.close()
    grade = await grade_run(run, grade_candidates=False, progress=lambda _: None)
    config = EvaluationSettings()
    state = publish(run, config, grade=grade)
    assert state["status"] == "published", state
    client = client_for(config)
    experiment = client.experiments.get(experiment_id=state["experiment_id"])
    assert experiment["successful_run_count"] == 1
    trial = read_json(next((run / "trials").glob("*.json")))
    # Collector processing is asynchronous; bound the readiness wait.
    spans = []
    for _ in range(20):
        try:
            spans = list(client.spans.get_spans(project_identifier=project, timeout=2))
        except Exception:
            spans = []
        if any(
            span["context"]["trace_id"] == trial["trace_id"]
            and span["name"] == "retail.evaluation_trial"
            for span in spans
        ):
            break
        await asyncio.sleep(0.1)
    assert any(span["context"]["trace_id"] == trial["trace_id"] for span in spans)
    roots = [s for s in spans if s["name"] == "retail.evaluation_trial"]
    assert len(roots) == 1
    attributes = roots[0].get("attributes", {})
    assert attributes["retail.case_id"] == "totals-q1"
    assert attributes["retail.repetition"] == 1
    assert attributes["retail.run_id"] == run.name
    # Independent missing facts/semantics remain unresolved even though runtime approved.
    summary = read_json(grade / "summary.json")
    assert summary["statuses"] == {"UNJUDGEABLE": 1}
