"""Publish versioned references and precomputed independent checks to Foundry.

Gemini judges and numerical checks run under the existing local budget. Foundry's
string-check grader mirrors resolved statuses; it does not make new LLM calls.
Unresolved checks stay visible in the result dataset and are excluded from quality
scores. This is explicitly an imported assessment, not an Azure LLM judgment.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError

from retail_insight.integrations.azure.connector import AzureConnector
from retail_insight.observability.tracing import sanitize_capture


class PublicationUnavailable(RuntimeError):
    pass


def check_deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("Evaluation publication deadline reached")


def client_for(settings=None, *, deadline=None):
    check_deadline(deadline)
    return AzureConnector()


def ensure_service(config=None, *, deadline=None, progress=print):
    check_deadline(deadline)
    client = client_for(config, deadline=deadline)
    try:
        # Validate project permission before any paid agent/judge calls.
        next(iter(client.project().datasets.list()), None)
        client.monitoring_connection()
    except Exception as exc:
        raise PublicationUnavailable(
            f"Foundry access failed ({type(exc).__name__}). Check the project's tenant with az login and connect Application Insights."
        ) from None
    finally:
        client.close()
    progress("Foundry ready: https://ai.azure.com")


def dataset_name(rows):
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]
    return "retail-diagnostic-" + digest


def ensure_rows(client, name, rows):
    rows = sanitize_capture(rows)
    ids = [row["input"]["case_id"] for row in rows]
    if not rows or len(set(ids)) != len(ids):
        raise ValueError("Dataset must contain unique case IDs")
    payload = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    version = hashlib.sha256(payload.encode()).hexdigest()[:24]
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:100]
    datasets = client.project().datasets
    try:
        return datasets.get(name=slug, version=version)
    except ResourceNotFoundError:
        # No replacement or deletion: each reference snapshot is immutable.
        with tempfile.TemporaryDirectory(prefix="retail-evaluation-") as directory:
            path = Path(directory) / "dataset.jsonl"
            path.write_text(payload)
            path.chmod(0o600)
            return datasets.upload_file(name=slug, version=version, file_path=str(path))


class Experiment:
    def __init__(self, client, name, rows, run_id, *, deadline=None):
        self.client, self.name, self.run_id = client, name, run_id
        self.deadline = deadline
        check_deadline(deadline)
        self.dataset = ensure_rows(client, name, rows)
        self.examples = {r["input"]["case_id"]: r for r in rows}
        self.url = client.settings.foundry_portal_url
        self.records = {}
        self.finalized = None

    def record(self, case_id, output, scores, started_at=None, ended_at=None, *, record_id=None):
        if self.finalized is not None:
            raise ValueError("An already published experiment cannot be changed")
        if case_id not in self.examples:
            raise ValueError("Unknown evaluation case")
        identifier = record_id or case_id
        self.records[identifier] = sanitize_capture(
            {
                "record_id": identifier,
                "case_id": case_id,
                "input": self.examples[case_id]["input"],
                "reference": self.examples[case_id]["output"],
                "actual_output": output,
                "checks": scores,
                "started_at": str(started_at or ""),
                "ended_at": str(ended_at or ""),
            }
        )
        return identifier

    def update_scores(self, record_id, scores):
        self.records[record_id]["checks"] = sanitize_capture(scores)

    def finalize(self):
        if self.finalized is not None:
            return self.finalized
        check_deadline(self.deadline)
        if not self.records:
            return {"status": "no_results", "url": self.url}
        # Full answers, references, errors and non-applicable checks remain accessible.
        full_rows = [{"input": {"case_id": k}, "output": v} for k, v in self.records.items()]
        results = ensure_rows(self.client, self.run_id + "-results", full_rows)
        resolved = []
        unresolved = 0
        for record in self.records.values():
            for score in record["checks"]:
                status = score.get("status", score.get("label", "ERROR"))
                if status not in {"PASS", "FAIL"}:
                    unresolved += status not in {"NOT_APPLICABLE", "NA", "N/A"}
                    continue
                resolved.append(
                    {
                        "item": {
                            "case_id": record["case_id"],
                            "record_id": record["record_id"],
                            "metric": score["name"],
                            "status": status,
                            "finding": score.get("finding", score.get("explanation", "")),
                            "reference_dataset_id": str(self.dataset.id),
                            "result_dataset_id": str(results.id),
                        }
                    }
                )
        state = {
            "url": self.url,
            "reference_dataset_id": str(self.dataset.id),
            "result_dataset_id": str(results.id),
            "resolved_checks": len(resolved),
            "unresolved_checks": unresolved,
        }
        if resolved:
            check_deadline(self.deadline)
            api = self.client.evaluations()
            evaluation = api.evals.create(
                name=self.run_id,
                metadata={
                    "assessment": "imported_independent_checks",
                    "judge_provider": "google",
                    "human_calibrated": "false",
                },
                data_source_config={
                    "type": "custom",
                    "include_sample_schema": False,
                    "item_schema": {
                        "type": "object",
                        "properties": {k: {"type": "string"} for k in resolved[0]["item"]},
                        "required": list(resolved[0]["item"]),
                    },
                },
                testing_criteria=[
                    {
                        "type": "string_check",
                        "name": "Independent check passed",
                        "input": "{{item.status}}",
                        "reference": "PASS",
                        "operation": "eq",
                    }
                ],
            )
            check_deadline(self.deadline)
            run = api.evals.runs.create(
                evaluation.id,
                name=self.run_id,
                data_source={
                    "type": "jsonl",
                    "source": {"type": "file_content", "content": resolved},
                },
            )
            until = min(time.monotonic() + 45, self.deadline or float("inf"))
            while run.status in {"queued", "in_progress"} and time.monotonic() < until:
                time.sleep(min(1, max(0, until - time.monotonic())))
                run = api.evals.runs.retrieve(run.id, eval_id=evaluation.id)
            state.update(
                eval_id=evaluation.id,
                run_id=run.id,
                cloud_status=run.status,
                status="published"
                if run.status == "completed"
                else "publication_pending"
                if run.status in {"queued", "in_progress"}
                else "publication_failed",
                url=run.report_url or self.url,
            )
        state.setdefault("status", "published")
        self.finalized = state
        self.url = state["url"]
        return state


def case_rows(cases):
    return [
        {
            "input": {**c.runtime_input(), "case_id": c.id},
            "output": {
                "references": {k: v.model_dump(mode="json") for k, v in c.references.items()}
            },
            "metadata": {
                "case_id": c.id,
                "split": c.split,
                "fixture_sha256": c.fixture_sha256,
                "provenance": c.provenance.model_dump(mode="json"),
            },
        }
        for c in cases
    ]


def sync_cases(cases, settings, *, client=None, deadline=None):
    rows = case_rows(cases)
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:12]
    return ensure_rows(
        client or client_for(settings, deadline=deadline),
        "Retail diagnostic pilot - " + digest,
        rows,
    )


class FoundryPublisher:
    def __init__(self, run, settings, *, deadline=None, project=None, client=None):
        from evaluation.runners.artifacts import read_json

        self.run, self.settings, self.deadline = run, settings, deadline
        self.client = client or client_for(settings, deadline=deadline)
        self.path = run / "foundry.json"
        self.state: dict = read_json(self.path) if self.path.exists() else {"runs": {}}

    def save(self, status):
        from evaluation.runners.artifacts import write_json

        self.state["status"] = "publication_failed" if self.state.get("errors") else status
        write_json(self.path, self.state)
        return self.state

    def start(self):
        from evaluation.runners.artifacts import frozen_cases

        cases = frozen_cases(self.run)
        check_deadline(self.deadline)
        rows = case_rows(cases)
        self.experiment = Experiment(
            self.client, dataset_name(rows), rows, self.run.name, deadline=self.deadline
        )
        self.state.update(url=self.experiment.url, traces_url=self.experiment.url)
        return self.save("ready")

    def failed(self, exc):
        self.state.setdefault("errors", []).append(type(exc).__name__)
        return self.save("publication_failed")

    def publish_trial(self, trial):
        try:
            return self._publish_trial(trial)
        except Exception as exc:
            return self.failed(exc)

    def _publish_trial(self, trial):
        from evaluation.graders.runner import _verified_trials

        _verified_trials(self.run)
        check_deadline(self.deadline)
        from evaluation.runners.artifacts import read_json

        raw = read_json(self.run / "trials" / (trial.id + ".json"))
        if raw != trial.model_dump(mode="json"):
            raise ValueError("Trial differs from saved execution")
        if trial.id not in self.state["runs"]:
            self.state["runs"][trial.id] = self.experiment.record(
                trial.case_id, raw, [], record_id=trial.id
            )
        return self.save("published")

    def publish_grade(self, grade_dir, grade):
        try:
            return self._publish_grade(grade_dir, grade)
        except Exception as exc:
            return self.failed(exc)

    def _publish_grade(self, grade_dir, grade):
        from evaluation.graders.runner import _verified_trials
        from evaluation.runners.artifacts import read_json

        execution, _, hashes = _verified_trials(self.run)
        manifest = read_json(grade_dir / "manifest.json")
        if (
            manifest["run_id"] != self.run.name
            or manifest["dataset_sha256"] != execution["dataset_sha256"]
            or manifest["trials_sha256"].get(grade.trial_id + ".json")
            != hashes.get(grade.trial_id + ".json")
        ):
            raise ValueError("Grade does not belong to the captured execution")
        check_deadline(self.deadline)
        from evaluation.runners.artifacts import read_json

        raw = read_json(grade_dir / "trials" / (grade.trial_id + ".json"))
        if raw != grade.model_dump(mode="json"):
            raise ValueError("Grade differs from saved assessment")
        scores = [
            {
                "name": "task_success",
                "status": grade.status,
                "finding": "Independent answer and operation checks",
            }
        ]
        scores.extend(raw.get("scores", []))
        for turn in raw["turns"]:
            scores.extend({**s, "name": turn["step_id"] + "/" + s["name"]} for s in turn["scores"])
        self.experiment.update_scores(grade.trial_id, scores)
        return self.save("published")

    def finalize(self):
        try:
            self.state.update(self.experiment.finalize())
            return self.save(self.state.get("status", "published"))
        except Exception as exc:
            return self.failed(exc)
