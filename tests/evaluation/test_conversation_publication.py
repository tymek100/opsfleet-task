"""Captured evidence, assistant review attribution and clean workspace boundaries."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from evaluation.cli import app
from evaluation.reporting.conversations import (
    MissingTraces,
    collect_roots,
    dataset_rows,
    prepare_phase,
    publish_phase,
    quality_annotations,
)
from evaluation.runners.artifacts import digest, write_json
from evaluation.runners.manual import Scenario
from evaluation.settings import EvaluationSettings
from retail_agent.config import Settings


@pytest.fixture
def captured(tmp_path):
    scenario = Scenario(
        id="scenario-01",
        prompt="Show Q1 revenue.",
        follow_up="Compare with Q4.",
        intent="Period comparison",
        checks=["Use qualifying revenue."],
    )
    run = tmp_path / "capture"
    write_json(run / "scenarios.json", [scenario.model_dump(mode="json")])
    write_json(
        run / "manifest.json",
        {
            "scenario_sha256": digest(run / "scenarios.json"),
            "model": "test-model",
            "clock_utc": "2026-11-22T00:00:00+00:00",
            "data_source": {"backend": "bigquery"},
            "source_sha256": {"prompt.md": "version"},
        },
    )
    hashes = {}
    for i, question in enumerate((scenario.prompt, scenario.follow_up), 1):
        path = run / f"cases/scenario-01/turn-{i}.json"
        write_json(
            path,
            {
                "step_id": f"turn-{i}",
                "prompt": question,
                "status": "approved",
                "markdown": "Unsupported claim." if i == 2 else "Revenue: 100.",
                "trace_id": str(i) * 32,
                "span_id": str(i) * 16,
                "elapsed_seconds": 1.0,
                "receipts": [],
            },
        )
        hashes[str(path.relative_to(run))] = digest(path)
    write_json(run / "progress.json", {"turn_hashes": hashes})
    write_json(
        tmp_path / "reviews/review.json",
        [
            {
                "id": scenario.id,
                "source_run": "capture",
                "turns": [
                    {"turn": "turn-1", "verdict": "PASS", "findings": ["Matches evidence."]},
                    {"turn": 2, "verdict": "FAIL", "findings": ["Unsupported causal claim."]},
                ],
            }
        ],
    )
    phase = {
        "name": "Controlled phase",
        "runs": ["capture"],
        "reviews": ["review.json"],
        "expected_turns": 2,
        "expected_verdicts": {"PASS": 1, "FAIL": 1},
    }
    return phase, tmp_path, [scenario]


def test_runtime_approval_does_not_override_independent_failed_review(captured):
    phase = prepare_phase(*captured)
    annotations = quality_annotations(phase["records"]["scenario-01"])
    assert [a["label"] for a in annotations] == ["PASS", "FAIL", "FAIL"]
    assert annotations[-1]["score"] == 0
    assert phase["reviewer_kind"] == "assistant_review_not_human_validation"


def test_pending_reviews_are_never_reported_as_passes(captured):
    spec, root, cases = captured
    spec.pop("expected_verdicts")
    spec["reviews"] = []
    phase = prepare_phase(spec, root, cases)
    annotation = quality_annotations(phase["records"]["scenario-01"])[0]
    assert annotation["label"] == "PENDING" and "score" not in annotation


def test_modified_capture_is_rejected_before_publication(captured):
    _, root, _ = captured
    (root / "capture/cases/scenario-01/turn-2.json").write_text("{}")
    with pytest.raises(ValueError, match="Changed or unregistered capture"):
        prepare_phase(*captured)


def test_review_of_different_execution_is_rejected(captured):
    from evaluation.runners.artifacts import read_json

    _, root, _ = captured
    path = root / "reviews/review.json"
    data = read_json(path)
    data[0]["source_run"] = "another-run"
    write_json(path, data)
    with pytest.raises(ValueError, match="another execution"):
        prepare_phase(*captured)


def test_duplicate_case_cannot_fill_a_missing_case(captured):
    spec, root, cases = captured
    spec["runs"] = ["capture", "capture"]
    with pytest.raises(ValueError, match="repeated scenario"):
        prepare_phase(spec, root, cases)


def test_missing_follow_up_trace_cannot_be_silently_published(captured):
    phase = prepare_phase(*captured)
    client = MagicMock()
    client.spans.get_spans.return_value = [{"context": {"trace_id": "1" * 32, "span_id": "1" * 16}}]
    with pytest.raises(MissingTraces, match="original trace is missing"):
        collect_roots(client, phase, "project")


def test_capture_without_trace_identifiers_cannot_pass_verification(captured):
    phase = prepare_phase(*captured)
    phase["records"]["scenario-01"]["turns"][1]["trace_id"] = None
    with pytest.raises(MissingTraces, match="no original trace"):
        collect_roots(MagicMock(), phase, "project")


def test_publication_preserves_both_turns_scores_and_reuses_the_same_experiment(captured):
    spec, root, cases = captured
    phase = prepare_phase(spec, root, cases)
    client = MagicMock()
    rows = [{**row, "id": "example"} for row in dataset_rows(cases)]
    client.datasets.get_dataset.return_value = SimpleNamespace(
        id="dataset", version_id="v1", examples=rows
    )
    client.projects.get.return_value = {"id": "project"}
    client.spans.get_spans.return_value = [
        {
            "context": {"trace_id": str(i) * 32, "span_id": str(i) * 16},
            "start_time": f"2026-11-22T00:00:0{i}+00:00",
            "end_time": f"2026-11-22T00:00:0{i + 1}+00:00",
        }
        for i in (1, 2)
    ]
    client.experiments.create.return_value = {"id": "experiment"}
    client.experiments.log_run.return_value = {"id": "run"}
    client.experiments.get_experiment_url.return_value = (
        "http://localhost:6006/datasets/dataset/experiments/experiment"
    )
    state = root / "publication.json"
    publish_phase(phase, cases, EvaluationSettings(), state, client=client)
    publish_phase(phase, cases, EvaluationSettings(), state, client=client)
    assert client.experiments.create.call_count == client.experiments.log_run.call_count == 1
    output = client.experiments.log_run.call_args.kwargs["output"]
    assert output["initial"]["answer"] == "Revenue: 100."
    assert output["follow_up"]["answer"] == "Unsupported claim."
    assert output["follow_up"]["assistant_review"]["verdict"] == "FAIL"
    assert client.experiments.log_evaluation.call_args.kwargs["annotator_kind"] == "LLM"


def test_fixture_cli_cannot_repopulate_the_primary_workspace(settings, monkeypatch):
    monkeypatch.setattr(Settings, "load", lambda: settings)
    result = CliRunner().invoke(
        app, ["run", "--max-cost-usd", "1", "--deadline-seconds", "30", "--allow-unreviewed"]
    )
    assert result.exit_code != 0 and "reserved" in result.output


def test_pytest_does_not_load_phoenix_autopublication_plugin(pytestconfig):
    assert not pytestconfig.pluginmanager.hasplugin("phoenix")
