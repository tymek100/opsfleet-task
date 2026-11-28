"""Exercise immutable references, exact saved outputs and Foundry API payloads."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError

from evaluation.data import load_cases
from evaluation.graders.runner import grade_run
from evaluation.reporting.foundry import Experiment, FoundryPublisher, ensure_rows
from evaluation.results import Trial, TrialGrade
from evaluation.runners.artifacts import read_json, write_json
from evaluation.runners.conversation import run_cases
from evaluation.settings import EvaluationSettings
from retail_insight.agents.retail.agent import RetailAnalyst
from tests.support.models import ScriptedModel, finish, verdict


class Client:
    def __init__(self):
        self.versions = {}
        self.evaluations_created = []
        self.runs = []
        self.settings = SimpleNamespace(foundry_portal_url="https://ai.azure.com")
        self.datasets = SimpleNamespace(get=self.get, upload_file=self.upload_file)
        self.evals = SimpleNamespace(
            create=self.create_eval, runs=SimpleNamespace(create=self.create_run)
        )

    def project(self):
        return self

    def evaluations(self):
        return self

    def get(self, *, name, version):
        if (name, version) not in self.versions:
            raise ResourceNotFoundError("absent")
        return self.versions[(name, version)]

    def upload_file(self, *, name, version, file_path):
        row = SimpleNamespace(
            id=name + "/" + version,
            rows=[json.loads(line) for line in Path(file_path).read_text().splitlines()],
        )
        self.versions[(name, version)] = row
        return row

    def create_eval(self, **kwargs):
        self.evaluations_created.append(kwargs)
        return SimpleNamespace(id="eval_1")

    def create_run(self, eval_id, **kwargs):
        self.runs.append(kwargs)
        return SimpleNamespace(
            id="run_1", status="completed", report_url="https://ai.azure.com/report"
        )


def test_reference_versions_answers_and_unresolved_checks_stay_separate():
    client = Client()
    rows = [{"input": {"case_id": "scenario-01", "question": "Sales?"}, "output": {"revenue": 100}}]
    experiment = Experiment(client, "Retail conversations", rows, "test-run")
    experiment.record(
        "scenario-01",
        {"answer": "Revenue is 100", "api_key": "secret"},
        [{"name": "grounding", "status": "PASS"}, {"name": "trajectory", "status": "ERROR"}],
    )
    assert experiment.dataset.rows[0]["output"] == {"revenue": 100}
    assert experiment.records["scenario-01"]["actual_output"] == {"answer": "Revenue is 100"}
    state = experiment.finalize()
    assert state["unresolved_checks"] == 1
    assert state["resolved_checks"] == 1
    assert client.runs[0]["data_source"]["source"]["content"][0]["item"]["status"] == "PASS"
    assert client.evaluations_created[0]["testing_criteria"][0]["type"] == "string_check"
    assert "model" not in json.dumps(client.evaluations_created)
    assert experiment.finalize() == state and len(client.runs) == 1
    rows[0]["output"]["revenue"] = 101
    changed = ensure_rows(client, "Retail conversations", rows)
    assert changed.id != experiment.dataset.id
    assert experiment.dataset.rows[0]["output"] == {"revenue": 100}
    with pytest.raises(ValueError, match="unique"):
        ensure_rows(client, "Retail conversations", rows * 2)


def test_unresolved_only_is_not_a_passing_evaluation():
    client = Client()
    experiment = Experiment(
        client, "test", [{"input": {"case_id": "one"}, "output": {}}], "test-run"
    )
    experiment.record("one", {}, [{"name": "grounding", "status": "UNJUDGEABLE"}])
    state = experiment.finalize()
    assert state["unresolved_checks"] == 1 and state["resolved_checks"] == 0
    assert not client.evaluations_created


async def test_saved_execution_and_grade_provenance_and_upload_failure(settings, tmp_path):
    case = load_cases("period-clarification")[0]

    def factory(config, identity, **kwargs):
        return RetailAnalyst(
            config,
            identity,
            model=ScriptedModel(script=[finish("Which period?", outcome="clarification")]),
            reviewer_model=ScriptedModel(script=[verdict()]),
            **kwargs,
        )

    run = await run_cases(
        [case],
        settings,
        artifact_root=tmp_path,
        suite="control",
        repetitions=1,
        max_cost_usd=1,
        deadline_seconds=30,
        app_factory=factory,
        progress=lambda _: None,
    )
    trial_path = next((run / "trials").glob("*.json"))
    trial = Trial.model_validate(read_json(trial_path))
    client = Client()
    publisher = FoundryPublisher(run, EvaluationSettings(), client=client)
    publisher.start()
    assert publisher.publish_trial(trial)["status"] == "published"
    grades = await grade_run(run, grade_candidates=False, progress=lambda _: None)
    grade = TrialGrade.model_validate(read_json(grades / "trials" / (trial.id + ".json")))
    assert publisher.publish_grade(grades, grade)["status"] == "published"
    before = len(publisher.experiment.records[trial.id]["checks"])
    manifest = read_json(grades / "manifest.json")
    manifest["run_id"] = "different-run"
    write_json(grades / "manifest.json", manifest)
    assert publisher.publish_grade(grades, grade)["status"] == "publication_failed"
    assert len(publisher.experiment.records[trial.id]["checks"]) == before
    publisher.state = {"runs": {}}
    publisher.experiment.record = lambda *a, **kw: (_ for _ in ()).throw(
        ConnectionError("secret-provider-detail")
    )
    assert publisher.publish_trial(trial)["status"] == "publication_failed"
    assert "secret-provider-detail" not in json.dumps(publisher.state)
    assert read_json(trial_path) == trial.model_dump(mode="json")
    publisher.deadline = 0
    assert publisher.publish_trial(trial)["status"] == "publication_failed"
