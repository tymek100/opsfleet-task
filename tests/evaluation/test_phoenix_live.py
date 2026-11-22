"""Incremental publication, trace attribution, and bounded collector startup."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from evaluation.data import load_cases
from evaluation.reporting import phoenix_service
from evaluation.reporting.phoenix import PhoenixPublisher
from evaluation.reporting.phoenix_service import PhoenixUnavailable, ensure_phoenix
from evaluation.results import Score, Trial, TrialGrade, TurnGrade, TurnRecord
from evaluation.runners.artifacts import digest, prepare_run, read_json, write_json
from evaluation.settings import EvaluationSettings


def client():
    value = MagicMock()
    value.datasets.get_dataset.side_effect = ValueError("Dataset not found: control")

    def create(**kwargs):
        return SimpleNamespace(
            id="dataset",
            version_id="version",
            examples=[
                {
                    "id": "example",
                    "input": kwargs["inputs"][0],
                    "output": kwargs["outputs"][0],
                    "metadata": kwargs["metadata"][0],
                }
            ],
        )

    value.datasets.create_dataset.side_effect = create
    value.experiments.create.return_value = {"id": "experiment"}
    value.experiments.log_run.return_value = {"id": "remote-run"}
    value.experiments.get_experiment_url.return_value = "http://127.0.0.1:6006/experiment"
    value.projects.get.return_value = {"id": "project", "name": "evaluation-test"}
    return value


@pytest.fixture
def publication(settings, tmp_path):
    run, manifest = prepare_run(
        tmp_path,
        load_cases("totals-q1"),
        settings,
        suite="control",
        repetitions=1,
        max_cost_usd=1,
        deadline_seconds=30,
    )
    remote = client()
    publisher = PhoenixPublisher(
        run,
        EvaluationSettings(),
        deadline=time.monotonic() + 30,
        client=remote,
        project="evaluation-test",
    )
    return publisher, remote, manifest


def save_trial(publisher, manifest):
    trial = Trial(
        id="totals-q1-r1",
        case_id="totals-q1",
        repetition=1,
        status="completed",
        started_at="2026-11-22T00:00:00+00:00",
        ended_at="2026-11-22T00:00:01+00:00",
        trace_id="0" * 32,
        span_id="a" * 16,
        turns=[TurnRecord(step_id="turn-1", status="approved", span_id="b" * 16)],
    )
    path = publisher.run / "trials" / f"{trial.id}.json"
    write_json(path, trial)
    manifest.trials_sha256[path.name] = digest(path)
    write_json(publisher.run / "manifest.json", manifest)
    return trial


def save_grade(publisher, trial, manifest):
    grade = TrialGrade(
        trial_id=trial.id,
        case_id=trial.case_id,
        repetition=1,
        status="FAIL",
        scores=[
            Score(
                name="trajectory_tool_selection",
                status="FAIL",
                value=0,
                finding="Unsupported selection /confirm HIDDEN_TOKEN",
            )
        ],
        turns=[
            TurnGrade(
                step_id="turn-1",
                status="PASS",
                scores=[Score(name="claim_support", status="PASS", value=1, finding="Supported")],
            )
        ],
    )
    directory = publisher.run / "grades" / "grade-test"
    write_json(
        directory / "manifest.json",
        {
            "run_id": publisher.run.name,
            "dataset_sha256": manifest.dataset_sha256,
            "trials_sha256": manifest.trials_sha256,
        },
    )
    write_json(directory / "trials" / f"{trial.id}.json", grade)
    return directory, grade


def test_experiment_and_project_links_exist_before_first_trial(publication):
    publisher, remote, _ = publication
    result = publisher.start()
    assert result["url"] == "http://127.0.0.1:6006/experiment"
    assert result["traces_url"] == "http://127.0.0.1:6006/projects/project"
    assert not (publisher.run / "trials").exists()
    remote.experiments.create.assert_called_once()
    remote.experiments.log_run.assert_not_called()
    assert read_json(publisher.path)["status"] == "ready"


def test_completed_trial_and_grade_publish_incrementally_and_idempotently(publication):
    publisher, remote, manifest = publication
    publisher.start()
    trial = save_trial(publisher, manifest)
    assert publisher.publish_trial(trial)["status"] == "published"
    assert read_json(publisher.run / "manifest.json")["status"] == "running"
    publisher.publish_trial(trial)
    remote.experiments.log_run.assert_called_once()
    directory, grade = save_grade(publisher, trial, manifest)
    assert publisher.publish_grade(directory, grade)["status"] == "published"
    sent = remote.spans.log_span_annotations.call_args.kwargs["span_annotations"]
    assert {annotation["span_id"] for annotation in sent} == {"a" * 16, "b" * 16}
    trajectory = next(item for item in sent if "trajectory" in item["name"])
    assert trajectory["annotator_kind"] == "LLM"
    assert "HIDDEN_TOKEN" not in str(sent)
    count = remote.experiments.log_evaluation.call_count
    publisher.publish_grade(directory, grade)
    assert remote.experiments.log_evaluation.call_count == count
    remote.spans.log_span_annotations.assert_called_once()


def test_publication_failure_is_retryable_without_losing_local_output(publication):
    publisher, remote, manifest = publication
    publisher.start()
    trial = save_trial(publisher, manifest)
    remote.experiments.log_run.side_effect = httpx.ConnectError("offline")
    assert publisher.publish_trial(trial)["status"] == "publication_failed"
    assert read_json(publisher.run / "trials" / f"{trial.id}.json")["id"] == trial.id
    assert not publisher.state["runs"]
    remote.experiments.log_run.side_effect = None
    assert publisher.publish_trial(trial)["status"] == "published"


def test_duplicate_remote_trial_is_adopted_only_when_output_matches(publication):
    publisher, remote, manifest = publication
    publisher.start()
    trial = save_trial(publisher, manifest)
    remote.experiments.log_run.side_effect = httpx.HTTPStatusError(
        "Already stored",
        request=httpx.Request("POST", "http://localhost"),
        response=httpx.Response(409),
    )
    saved = read_json(publisher.run / "trials" / f"{trial.id}.json")
    remote.experiments.get_experiment.return_value = {
        "task_runs": [
            {
                "id": "stored",
                "dataset_example_id": "example",
                "repetition_number": 1,
                "output": saved,
            }
        ]
    }
    assert publisher.publish_trial(trial)["status"] == "published"
    assert publisher.state["runs"][trial.id] == "stored"


def test_start_failure_is_explicit_before_any_trial_upload(publication):
    publisher, remote, _ = publication
    remote.datasets.get_dataset.side_effect = httpx.ConnectError("offline")
    with pytest.raises(PhoenixUnavailable, match="no agent run started"):
        publisher.start()
    remote.experiments.log_run.assert_not_called()
    assert read_json(publisher.path)["status"] == "publication_failed"


def test_successful_trial_upload_does_not_hide_earlier_missing_annotations(publication):
    publisher, remote, manifest = publication
    publisher.start()
    trial = save_trial(publisher, manifest)
    publisher.publish_trial(trial)
    directory, grade = save_grade(publisher, trial, manifest)
    remote.spans.log_span_annotations.side_effect = httpx.ConnectError("offline")
    assert publisher.publish_grade(directory, grade)["status"] == "publication_failed"
    assert publisher.publish_trial(trial)["status"] == "publication_failed"
    assert publisher.state["failures"] == {f"grade/{directory.name}/{trial.id}": "ConnectError"}
    remote.spans.log_span_annotations.side_effect = None
    assert publisher.publish_grade(directory, grade)["status"] == "published"
    assert publisher.state["failures"] == {}


def test_artifact_publication_cannot_claim_to_repair_missing_exported_spans(publication):
    publisher, _, manifest = publication
    publisher.start()
    trial = save_trial(publisher, manifest)
    publisher.state["trace_status"] = "incomplete"
    state = publisher.publish_trial(trial)
    assert state["status"] == "publication_failed"
    assert state["trace_status"] == "incomplete"
    assert state["error"] == "IncompleteTraceExport"


def test_missing_trial_and_grade_remain_independently_pending(publication):
    publisher, remote, manifest = publication
    publisher.start()
    trial = save_trial(publisher, manifest)
    directory, grade = save_grade(publisher, trial, manifest)
    remote.experiments.log_run.side_effect = httpx.ConnectError("offline")
    assert publisher.publish_grade(directory, grade)["status"] == "publication_failed"
    assert len(publisher.state["failures"]) == 2
    remote.experiments.log_run.side_effect = None
    assert publisher.publish_trial(trial)["status"] == "publication_failed"
    assert len(publisher.state["failures"]) == 1
    assert publisher.publish_grade(directory, grade)["status"] == "published"


def test_existing_collector_is_reused_without_starting_docker(monkeypatch):
    monkeypatch.setattr(phoenix_service, "_ready", lambda *_: True)
    launch = MagicMock()
    monkeypatch.setattr(phoenix_service.subprocess, "run", launch)
    ensure_phoenix(EvaluationSettings(), deadline=time.monotonic() + 5, progress=lambda _: None)
    launch.assert_not_called()


def test_default_collector_starts_compose_and_waits_for_readiness(monkeypatch):
    ready = iter([False, True])
    monkeypatch.setattr(phoenix_service, "_ready", lambda *_: next(ready))
    launch = MagicMock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(phoenix_service.subprocess, "run", launch)
    ensure_phoenix(EvaluationSettings(), deadline=time.monotonic() + 5, progress=lambda _: None)
    command = launch.call_args.args[0]
    assert command[:3] == ["docker", "compose", "-f"]
    assert command[-2:] == ["up", "-d"]
    assert 0 < launch.call_args.kwargs["timeout"] <= 5


def test_unavailable_custom_endpoint_does_not_start_unrelated_compose(monkeypatch):
    monkeypatch.setattr(phoenix_service, "_ready", lambda *_: False)
    launch = MagicMock()
    monkeypatch.setattr(phoenix_service.subprocess, "run", launch)
    with pytest.raises(PhoenixUnavailable, match="custom collector"):
        ensure_phoenix(
            EvaluationSettings(phoenix_url="http://localhost:7000"),
            deadline=time.monotonic() + 5,
            progress=lambda _: None,
        )
    launch.assert_not_called()


def test_startup_deadline_prevents_network_and_docker(monkeypatch):
    probe = MagicMock()
    monkeypatch.setattr(phoenix_service, "_ready", probe)
    with pytest.raises(PhoenixUnavailable, match="deadline"):
        ensure_phoenix(EvaluationSettings(), deadline=time.monotonic() - 1)
    probe.assert_not_called()
