"""Publish saved synthetic outputs through public Phoenix APIs; never rerun tasks."""

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import httpx

from evaluation.models import Case
from evaluation.runners.artifacts import digest, frozen_cases, read_json, write_json
from evaluation.settings import EvaluationSettings
from retail_agent.observability import sanitize_capture


def client_for(settings: EvaluationSettings):
    from phoenix.client import Client

    return Client(
        base_url=settings.phoenix_url,
        http_client=httpx.Client(
            base_url=settings.phoenix_url, timeout=5, follow_redirects=False, trust_env=False
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


def publish(
    run: Path,
    settings: EvaluationSettings,
    *,
    grade: Path | None = None,
    client=None,
    deadline_seconds: float = 120,
) -> dict:
    client = client or client_for(settings)
    publication_path = run / "phoenix.json"
    state = (
        read_json(publication_path)
        if publication_path.exists()
        else {"runs": {}, "status": "pending"}
    )
    deadline = time.monotonic() + deadline_seconds

    def remaining():
        value = deadline - time.monotonic()
        if value < 1:
            raise TimeoutError("Publication deadline exhausted")
        return int(min(5, value))

    try:
        manifest = read_json(run / "manifest.json")
        paths = sorted((run / "trials").glob("*.json"))
        trial_hashes = {path.name: digest(path) for path in paths}
        if trial_hashes != manifest.get("trials_sha256", {}):
            raise ValueError("Execution artifacts are missing or were modified after capture")
        if grade:
            grading = read_json(grade / "manifest.json")
            if (
                grading.get("run_id") != manifest["id"]
                or grading.get("dataset_sha256") != manifest["dataset_sha256"]
                or grading.get("trials_sha256") != trial_hashes
            ):
                raise ValueError("Grade artifacts do not belong to this captured execution")
        dataset = sync_cases(frozen_cases(run), settings, client=client, deadline=deadline)
        state.update(dataset_id=dataset.id, dataset_version_id=dataset.version_id)
        examples = {e["input"]["case_id"]: e["id"] for e in dataset.examples}
        if "experiment_id" not in state:
            experiment = client.experiments.create(
                dataset_id=dataset.id,
                dataset_version_id=dataset.version_id,
                experiment_name=manifest["id"],
                experiment_description="Saved agent trial import; timestamps and usage belong to original execution.",
                experiment_metadata=sanitize_capture(manifest),
                repetitions=manifest["repetitions"],
                timeout=remaining(),
            )
            state["experiment_id"] = experiment["id"]
            write_json(publication_path, state)
        for path in paths:
            trial = read_json(path)
            if trial["status"] == "NOT_EXECUTED" or trial["id"] in state["runs"]:
                continue
            recorded = client.experiments.log_run(
                experiment_id=state["experiment_id"],
                dataset_example_id=examples[trial["case_id"]],
                output=sanitize_capture(trial),
                start_time=datetime.fromisoformat(trial["started_at"]),
                end_time=datetime.fromisoformat(trial["ended_at"]),
                repetition_number=trial["repetition"],
                trace_id=trial.get("trace_id"),
                error=sanitize_capture(trial.get("error")),
                timeout=remaining(),
            )
            state["runs"][trial["id"]] = recorded["id"]
            write_json(publication_path, state)
        if grade:
            for path in sorted((grade / "trials").glob("*.json")):
                result = read_json(path)
                remote = state["runs"].get(result["trial_id"])
                if not remote:
                    continue
                # Grade IDs keep regrades distinct rather than overwriting prior annotations.
                annotations = [
                    (
                        "task_success",
                        result["status"],
                        float(result["status"] == "PASS")
                        if result["status"] in {"PASS", "FAIL"}
                        else None,
                        "All required turns and state checks",
                    )
                ]
                for turn in result["turns"]:
                    for score in turn["scores"]:
                        name = f"{turn['step_id']}/{score['name']}/{score.get('criterion_id') or 'overall'}"
                        annotations.append(
                            (name, score["status"], score["value"], score["finding"])
                        )
                for name, label, score, explanation in annotations:
                    client.experiments.log_evaluation(
                        experiment_run_id=remote,
                        name=f"{grade.name}/{name}",
                        annotator_kind="CODE"
                        if name == "task_success"
                        else "LLM"
                        if "/semantic/" in name or "/claim_" in name
                        else "CODE",
                        score=score,
                        label=label,
                        explanation=sanitize_capture(explanation),
                        metadata={"grade_id": grade.name, "human_calibrated": False},
                        timeout=remaining(),
                    )
        state.update(
            status="published",
            url=client.experiments.get_experiment_url(
                dataset_id=state["dataset_id"], experiment_id=state["experiment_id"]
            ),
        )
        state.pop("error", None)
    except Exception as exc:
        state.update(status="publication_failed", error=type(exc).__name__)
    write_json(publication_path, state)
    return state
