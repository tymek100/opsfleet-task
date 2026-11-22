"""Publish saved synthetic outputs through public Phoenix APIs; never rerun tasks."""

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from evaluation.models import Case
from evaluation.reporting.phoenix_service import PhoenixUnavailable
from evaluation.results import Trial, TrialGrade
from evaluation.runners.artifacts import digest, frozen_cases, read_json, write_json
from evaluation.settings import EvaluationSettings
from retail_agent.observability import sanitize_capture


def client_for(settings: EvaluationSettings, *, deadline: float | None = None):
    from phoenix.client import Client

    def cap_timeout(request: httpx.Request) -> None:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Publication deadline exhausted")
            request.extensions["timeout"] = httpx.Timeout(min(5, remaining)).as_dict()

    return Client(
        base_url=settings.phoenix_url,
        http_client=httpx.Client(
            base_url=settings.phoenix_url,
            timeout=5,
            follow_redirects=False,
            trust_env=False,
            event_hooks={"request": [cap_timeout]},
        ),
    )


def sync_cases(cases: list[Case], settings: EvaluationSettings, *, client=None, deadline=None):
    client = client or client_for(settings)
    encoded = json.dumps([c.model_dump(mode="json") for c in cases], sort_keys=True)
    checksum = hashlib.sha256(encoded.encode()).hexdigest()
    name = "retail-evaluation-" + checksum[:20]
    inputs = [sanitize_capture(c.runtime_input()) for c in cases]
    outputs = [
        sanitize_capture(
            {"references": {key: r.model_dump(mode="json") for key, r in c.references.items()}}
        )
        for c in cases
    ]
    metadata = [
        sanitize_capture(
            {
                "case_id": c.id,
                "family": c.family,
                "split": c.split,
                "fixture_sha256": c.fixture_sha256,
                "dataset_sha256": checksum,
                "provenance": c.provenance.model_dump(mode="json"),
            }
        )
        for c in cases
    ]

    def remaining():
        value = 5 if deadline is None else min(5, deadline - time.monotonic())
        if value < 1:
            raise TimeoutError("Publication deadline exhausted")
        return int(value)

    try:
        dataset = client.datasets.get_dataset(dataset=name, timeout=remaining())
    except ValueError as exc:
        if not str(exc).startswith("Dataset not found:"):
            raise
        dataset = client.datasets.create_dataset(
            name=name,
            inputs=inputs,
            outputs=outputs,
            metadata=metadata,
            dataset_description="Independent synthetic evaluation references; human review pending.",
            timeout=remaining(),
        )
    expected = {
        item["case_id"]: (item, output, meta)
        for item, output, meta in zip(inputs, outputs, metadata, strict=True)
    }
    found = [example.get("input", {}).get("case_id") for example in dataset.examples]
    if (
        len(found) != len(expected)
        or set(found) != set(expected)
        or any(
            example.get("input") != expected[example["input"]["case_id"]][0]
            or example.get("output") != expected[example["input"]["case_id"]][1]
            or any(
                example.get("metadata", {}).get(key) != value
                for key, value in expected[example["input"]["case_id"]][2].items()
            )
            for example in dataset.examples
        )
    ):
        raise ValueError("Phoenix dataset differs from the canonical frozen dataset")
    return dataset


class PhoenixPublisher:
    """Publish each completed trial and grade while the experiment is still running."""

    def __init__(
        self,
        run: Path,
        settings: EvaluationSettings,
        *,
        deadline: float,
        client=None,
        project: str = "retail-evaluation",
    ):
        self.run = run
        self.settings = settings
        self.deadline = deadline
        self.client = client or client_for(settings, deadline=deadline)
        self.project = project
        self.path = run / "phoenix.json"
        self.state = (
            read_json(self.path) if self.path.exists() else {"runs": {}, "status": "pending"}
        )
        self.state.setdefault("grades", {})
        self.state.setdefault("failures", {})
        self.examples: dict[str, str] = {}

    def remaining(self) -> int:
        remaining = self.deadline - time.monotonic()
        if remaining < 1:
            raise TimeoutError("Publication deadline exhausted")
        return int(min(5, remaining))

    def _save(self, status: str, *, completed: str | None = None) -> dict:
        if completed:
            self.state["failures"].pop(completed, None)
        if self.state["failures"]:
            self.state["status"] = "publication_failed"
            self.state["error"] = next(iter(self.state["failures"].values()))
        elif self.state.get("trace_status") == "incomplete":
            self.state["status"] = "publication_failed"
            self.state["error"] = "IncompleteTraceExport"
        else:
            self.state["status"] = status
            self.state.pop("error", None)
        write_json(self.path, self.state)
        return dict(self.state)

    def _failed(self, exc: Exception, *, operation: str = "publication") -> dict:
        self.state["failures"][operation] = type(exc).__name__
        self.state.update(status="publication_failed", error=type(exc).__name__)
        write_json(self.path, self.state)
        return dict(self.state)

    def _manifest(self) -> tuple[dict, dict[str, str]]:
        manifest = read_json(self.run / "manifest.json")
        actual = {p.name: digest(p) for p in sorted((self.run / "trials").glob("*.json"))}
        if actual != manifest.get("trials_sha256", {}):
            raise ValueError("Execution artifacts are missing or were modified after capture")
        return manifest, actual

    def _validate_grade(self, grade_dir: Path) -> None:
        manifest, actual = self._manifest()
        grading = read_json(grade_dir / "manifest.json")
        if (
            grading.get("run_id") != manifest["id"]
            or grading.get("dataset_sha256") != manifest["dataset_sha256"]
            or grading.get("trials_sha256") != actual
        ):
            raise ValueError("Grade artifacts do not belong to this captured execution")

    def start(self) -> dict:
        """Create the experiment and links before any task is executed; fail fast."""
        try:
            manifest, _ = self._manifest()
            self.remaining()
            dataset = sync_cases(
                frozen_cases(self.run), self.settings, client=self.client, deadline=self.deadline
            )
            if self.state.get("dataset_id") not in {None, dataset.id}:
                raise ValueError("Publication dataset changed")
            self.state.update(dataset_id=dataset.id, dataset_version_id=dataset.version_id)
            self.examples = {e["input"]["case_id"]: e["id"] for e in dataset.examples}
            if "experiment_id" not in self.state:
                experiment = self.client.experiments.create(
                    dataset_id=dataset.id,
                    dataset_version_id=dataset.version_id,
                    experiment_name=manifest["id"],
                    experiment_description="Agent evaluation; results and scores publish after each completed trial.",
                    experiment_metadata=sanitize_capture(manifest),
                    repetitions=manifest["repetitions"],
                    timeout=self.remaining(),
                )
                self.state["experiment_id"] = experiment["id"]
                write_json(self.path, self.state)
            self.state["url"] = self.client.experiments.get_experiment_url(
                dataset_id=dataset.id, experiment_id=self.state["experiment_id"]
            )
            if "traces_url" not in self.state:
                self.remaining()
                try:
                    project = self.client.projects.get(project_name=self.project)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                    self.remaining()
                    project = self.client.projects.create(
                        name=self.project, description="Synthetic retail evaluation traces."
                    )
                # Public project URLs use the opaque project ID; never assume a fixed numeric ID.
                if isinstance(project, dict) and isinstance(project.get("id"), str):
                    self.state["project_id"] = project["id"]
                    self.state["traces_url"] = (
                        self.settings.phoenix_url + "/projects/" + quote(project["id"], safe="")
                    )
                else:
                    self.state["traces_url"] = self.settings.phoenix_url + "/projects"
            return self._save("ready", completed="startup")
        except Exception as exc:
            self._failed(exc, operation="startup")
            raise PhoenixUnavailable(
                f"Phoenix experiment could not be prepared ({type(exc).__name__}); no agent run started."
            ) from exc

    def _saved_trial(self, trial: Trial) -> dict:
        self._manifest()
        path = self.run / "trials" / f"{trial.id}.json"
        data = read_json(path)
        if Trial.model_validate(data) != trial:
            raise ValueError("Published trial differs from captured execution")
        return data

    def publish_trial(self, trial: Trial) -> dict:
        operation = f"trial/{trial.id}"
        try:
            data = self._saved_trial(trial)
            if data["status"] == "NOT_EXECUTED":
                return dict(self.state)
            if not self.examples:
                self.start()
            if trial.id not in self.state["runs"]:
                payload = sanitize_capture(data)
                try:
                    recorded = self.client.experiments.log_run(
                        experiment_id=self.state["experiment_id"],
                        dataset_example_id=self.examples[trial.case_id],
                        output=payload,
                        start_time=datetime.fromisoformat(data["started_at"]),
                        end_time=datetime.fromisoformat(data["ended_at"]),
                        repetition_number=trial.repetition,
                        trace_id=trial.trace_id,
                        error=sanitize_capture(trial.error),
                        timeout=self.remaining(),
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 409:
                        raise
                    # A prior response may have been lost after the server committed the run.
                    self.remaining()
                    experiment = self.client.experiments.get_experiment(
                        experiment_id=self.state["experiment_id"]
                    )
                    matches = [
                        item
                        for item in experiment["task_runs"]
                        if item["dataset_example_id"] == self.examples[trial.case_id]
                        and item["repetition_number"] == trial.repetition
                        and item["output"] == payload
                    ]
                    if len(matches) != 1:
                        raise ValueError(
                            "Existing Phoenix run differs from captured execution"
                        ) from exc
                    recorded = matches[0]
                self.state["runs"][trial.id] = recorded["id"]
            return self._save("published", completed=operation)
        except Exception as exc:
            return self._failed(exc, operation=operation)

    @staticmethod
    def _annotations(result: dict, trial: dict):
        root_span = trial.get("span_id")
        yield (
            "task_success",
            {
                "status": result["status"],
                "value": float(result["status"] == "PASS")
                if result["status"] in {"PASS", "FAIL"}
                else None,
                "finding": "All required answer and final-state checks; trajectory is diagnostic",
            },
            root_span,
        )
        for score in result.get("scores", []):
            yield (
                f"trial/{score['name']}/{score.get('criterion_id') or 'overall'}",
                score,
                root_span,
            )
        turns = {turn["step_id"]: turn for turn in trial["turns"]}
        for turn in result["turns"]:
            for score in turn["scores"]:
                name = f"{turn['step_id']}/{score['name']}/{score.get('criterion_id') or 'overall'}"
                yield name, score, turns.get(turn["step_id"], {}).get("span_id")

    def publish_grade(self, grade_dir: Path, grade: TrialGrade) -> dict:
        operation = f"grade/{grade_dir.name}/{grade.trial_id}"
        try:
            self._validate_grade(grade_dir)
            grade_path = grade_dir / "trials" / f"{grade.trial_id}.json"
            result = read_json(grade_path)
            if TrialGrade.model_validate(result) != grade:
                raise ValueError("Published grade differs from saved grade")
            grade_hash = digest(grade_path)
            acknowledged = self.state["grades"].setdefault(grade_dir.name, {})
            if grade.trial_id in acknowledged:
                if acknowledged[grade.trial_id] != grade_hash:
                    raise ValueError("Previously published grade was modified")
                return self._save("published", completed=operation)
            trial = read_json(self.run / "trials" / f"{grade.trial_id}.json")
            if trial["status"] == "NOT_EXECUTED":
                return dict(self.state)
            if grade.trial_id not in self.state["runs"]:
                self.publish_trial(Trial.model_validate(trial))
                if grade.trial_id not in self.state["runs"]:
                    return self._failed(
                        RuntimeError("The required experiment run has not been uploaded"),
                        operation=operation,
                    )
            remote = self.state["runs"][grade.trial_id]
            spans = []
            for name, score, span_id in self._annotations(result, trial):
                kind = (
                    "LLM"
                    if any(part in name for part in ("/semantic/", "/claim_", "/trajectory"))
                    else "CODE"
                )
                description = sanitize_capture(score["finding"])
                full_name = f"{grade_dir.name}/{name}"
                self.client.experiments.log_evaluation(
                    experiment_run_id=remote,
                    name=full_name,
                    annotator_kind=kind,
                    score=score.get("value"),
                    label=score["status"],
                    explanation=description,
                    metadata={"grade_id": grade_dir.name, "human_calibrated": False},
                    timeout=self.remaining(),
                )
                if isinstance(span_id, str) and re.fullmatch(r"[0-9a-f]{16}", span_id):
                    annotation_result = {"label": score["status"], "explanation": description}
                    if score.get("value") is not None:
                        annotation_result["score"] = score["value"]
                    spans.append(
                        {
                            "span_id": span_id,
                            "name": name,
                            "identifier": grade_dir.name,
                            "annotator_kind": kind,
                            "result": annotation_result,
                            "metadata": {"grade_id": grade_dir.name, "human_calibrated": False},
                        }
                    )
            if spans:
                self.remaining()
                self.client.spans.log_span_annotations(span_annotations=spans, sync=True)
            acknowledged[grade.trial_id] = grade_hash
            return self._save("published", completed=operation)
        except Exception as exc:
            return self._failed(exc, operation=operation)


def publish(
    run: Path,
    settings: EvaluationSettings,
    *,
    grade: Path | None = None,
    client=None,
    deadline_seconds: float = 120,
) -> dict:
    """Publish or retry saved artifacts without executing agents or evaluators."""
    publisher = PhoenixPublisher(
        run, settings, deadline=time.monotonic() + deadline_seconds, client=client
    )
    try:
        # Reject unrelated grade directories before any remote mutation.
        if grade:
            publisher._validate_grade(grade)
        publisher.start()
        for path in sorted((run / "trials").glob("*.json")):
            publisher.publish_trial(Trial.model_validate(read_json(path)))
        if grade:
            for path in sorted((grade / "trials").glob("*.json")):
                publisher.publish_grade(grade, TrialGrade.model_validate(read_json(path)))
        return publisher._save("published", completed="publication")
    except Exception as exc:
        # start() already records the underlying failure, rather than its public wrapper.
        if publisher.state.get("status") == "publication_failed":
            return dict(publisher.state)
        return publisher._failed(exc)
