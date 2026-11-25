"""Publish authored conversation captures and attributed reviews to one Phoenix dataset."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from evaluation.reporting.phoenix import client_for
from evaluation.runners.artifacts import digest, read_json, write_json
from evaluation.runners.manual import load_scenarios
from evaluation.settings import EvaluationSettings
from retail_insight.integrations.phoenix.tracing import sanitize_capture

DATASET_NAME = "Retail agent — 20 conversations"
PROJECT_NAME = "retail-conversations-20"
REVIEW_KIND = "assistant_review_not_human_validation"
SEVERITY = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}


class MissingTraces(ValueError):
    """Original spans have not arrived in the shared project."""


def checksum(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepare_phase(phase: dict, root: Path, scenarios: list) -> dict:
    """Validate frozen inputs, capture hashes and review attribution before any upload."""
    canonical = {case.id: case for case in scenarios}
    records = {}
    manifests = {}
    for run_name in phase["runs"]:
        run = root / run_name
        manifest = read_json(run / "manifest.json")
        state = read_json(run / "progress.json")
        if digest(run / "scenarios.json") != manifest["scenario_sha256"]:
            raise ValueError(f"Changed scenario capture: {run.name}")
        manifests[run.name] = {
            "model": manifest["model"],
            "clock_utc": manifest["clock_utc"],
            "data_source": manifest["data_source"],
            "source_sha256": manifest["source_sha256"],
        }
        for case in load_scenarios(run / "scenarios.json"):
            if case.id not in canonical or case != canonical[case.id] or case.id in records:
                raise ValueError(f"Unknown, changed or repeated scenario: {case.id}")
            turns = []
            for number, prompt in enumerate((case.prompt, case.follow_up), 1):
                relative = f"cases/{case.id}/turn-{number}.json"
                path = run / relative
                if digest(path) != state["turn_hashes"].get(relative):
                    raise ValueError(f"Changed or unregistered capture: {run.name}/{relative}")
                turn = read_json(path)
                if turn["prompt"] != prompt or turn["step_id"] != f"turn-{number}":
                    raise ValueError(f"Prompt order mismatch: {case.id}/{number}")
                turns.append(turn)
            records[case.id] = {"source_run": run.name, "turns": turns, "reviews": {}}
    review_hashes = {}
    for filename in phase.get("reviews", []):
        path = root / "reviews" / filename
        data = read_json(path)
        review_hashes[filename] = digest(path)
        entries = data["cases"] if isinstance(data, dict) else data
        for case in entries:
            if case["id"] not in records:
                raise ValueError(f"Review of an unexecuted scenario: {case['id']}")
            record = records[case["id"]]
            source = case.get("source_run") or case.get("capture_run")
            if source is None and isinstance(data, dict):
                source = data.get("source_run") or data.get("capture_run")
            if source and Path(source).name != record["source_run"]:
                raise ValueError(f"Review belongs to another execution: {case['id']}")
            for review in case["turns"]:
                number = str(review["turn"]).removeprefix("turn-")
                if number not in {"1", "2"} or number in record["reviews"]:
                    raise ValueError(f"Duplicate or invalid review: {case['id']}/{number}")
                if review["verdict"] not in SEVERITY:
                    raise ValueError("Unknown assistant review verdict")
                record["reviews"][number] = {**review, "review_file": filename}
    if phase.get("reviews") and any(set(r["reviews"]) != {"1", "2"} for r in records.values()):
        raise ValueError("Every executed turn requires an attributed review")
    counts = Counter(
        review["verdict"] for r in records.values() for review in r["reviews"].values()
    )
    if len(records) * 2 != phase.get("expected_turns", len(records) * 2):
        raise ValueError("Incomplete phase: unexpected number of captured turns")
    if "expected_verdicts" in phase and counts != Counter(phase["expected_verdicts"]):
        raise ValueError("Review totals differ from the recorded phase summary")
    result = {
        "name": phase["name"],
        "records": records,
        "sources": manifests,
        "review_hashes": review_hashes,
        "verdicts": dict(counts),
        "coverage": f"{len(records)} of {len(scenarios)} conversations",
        "reviewer_kind": REVIEW_KIND if review_hashes else "pending",
    }
    result["sha256"] = checksum(result)
    return result


def dataset_rows(scenarios, references=None):
    return [
        {
            "input": {
                "case_id": case.id,
                "identity": case.identity,
                "question": case.prompt,
                "follow_up": case.follow_up,
            },
            "output": {
                "acceptance_criteria": case.checks,
                "reference_status": "Independently computed facts and behavioral criteria; model answers are not reference truth."
                if references
                else "Behavioral criteria; observed answers are not reference truth.",
                **(
                    {"turns": references["cases"][case.id], "provenance": references["provenance"]}
                    if references
                    else {}
                ),
            },
            "metadata": {
                "case_id": case.id,
                "intent": case.intent,
                "provenance": "assistant-authored, not production traffic",
                "oracle_topics": case.oracle_topics,
            },
        }
        for case in scenarios
    ]


def ensure_dataset(client, scenarios, references=None):
    rows = dataset_rows(scenarios, references)
    try:
        dataset = client.datasets.get_dataset(dataset=DATASET_NAME, timeout=5)
    except ValueError as exc:
        if not str(exc).startswith("Dataset not found:"):
            raise
        dataset = client.datasets.create_dataset(
            name=DATASET_NAME,
            inputs=[row["input"] for row in rows],
            outputs=[row["output"] for row in rows],
            metadata=[row["metadata"] for row in rows],
            dataset_description=(
                "20 authored retail scenarios with initial questions and fixed follow-ups. "
                "Versioned independent facts are separate from observed answers. Historical assistant "
                "reviews and new automatic grades are labeled separately; human calibration is pending."
            ),
        )
    expected = {row["input"]["case_id"]: row for row in rows}
    actual = {row["input"]["case_id"]: row for row in dataset.examples}
    if (
        len(dataset.examples) != len(rows)
        or actual.keys() != expected.keys()
        or any(
            any(actual[key].get(field) != row[field] for field in ("input", "metadata"))
            or actual[key].get("output", {}).get("acceptance_criteria")
            != row["output"]["acceptance_criteria"]
            for key, row in expected.items()
        )
    ):
        raise ValueError("Phoenix dataset differs from the frozen 20-conversation definition")
    if references and any(actual[key]["output"] != row["output"] for key, row in expected.items()):
        # Stable node IDs create new revisions without replacing examples or old experiments.
        dataset = client.datasets.create_dataset(
            name=DATASET_NAME,
            examples=[{"id": actual[row["input"]["case_id"]]["id"], **row} for row in rows],
            timeout=20,
        )
        revised = {e["input"]["case_id"]: e for e in dataset.examples}
        if len(revised) != len(expected) or any(
            revised[key]["id"] != actual[key]["id"] or revised[key]["output"] != row["output"]
            for key, row in expected.items()
        ):
            raise ValueError("Phoenix did not preserve example identity and exact reference values")
    return dataset


def ensure_project(client):
    try:
        return client.projects.get(project_name=PROJECT_NAME)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
    return client.projects.create(
        name=PROJECT_NAME,
        description="Traces of the 20 authored retail conversations and their fixed follow-ups.",
    )


def collect_roots(client, phase, project_id: str):
    """Require original traces in the shared project; never move source projects implicitly."""
    turns = [t for r in phase["records"].values() for t in r["turns"]]
    if any(not t.get("trace_id") or not t.get("span_id") for t in turns):
        raise MissingTraces("A captured turn has no original trace or span identifier")
    identifiers = [t["trace_id"] for t in turns]
    roots = (
        {
            s["context"]["trace_id"]: {**s, "source_project": project_id}
            for s in client.spans.get_spans(
                project_identifier=project_id,
                trace_ids=identifiers,
                name="retail.prompt",
                limit=200,
            )
        }
        if identifiers
        else {}
    )
    for turn in turns:
        if (
            turn["trace_id"] not in roots
            or roots[turn["trace_id"]]["context"]["span_id"] != turn["span_id"]
        ):
            raise MissingTraces("A captured turn's original trace is missing; publication stopped")
    return roots


def output_record(record, endpoint, project_id):
    turns = []
    for number, turn in enumerate(record["turns"], 1):
        trace_id = turn.get("trace_id")
        turns.append(
            {
                "question": turn["prompt"],
                "answer": turn.get("markdown"),
                "runtime_status": turn["status"],
                "elapsed_seconds": turn["elapsed_seconds"],
                "receipts": turn["receipts"],
                "assistant_review": record["reviews"].get(str(number)),
                "trace_url": f"{endpoint}/projects/{quote(project_id, safe='')}/traces/{trace_id}"
                if trace_id
                else None,
            }
        )
    return sanitize_capture(
        {"initial": turns[0], "follow_up": turns[1], "source_run": record["source_run"]}
    )


def quality_annotations(record) -> list[dict]:
    reviews = record["reviews"]
    if not reviews:
        return [
            {
                "name": "Conversation quality",
                "label": "PENDING",
                "explanation": "Independent review has not been supplied; runtime approval is not a quality pass.",
            }
        ]
    annotations: list[dict] = []
    for number, name in (("1", "Initial answer"), ("2", "Follow-up answer")):
        review = reviews[number]
        annotations.append(
            {
                "name": name,
                "label": review["verdict"],
                "score": float(review["verdict"] == "PASS"),
                "explanation": "\n".join(review["findings"]),
            }
        )
    worst = max((r["verdict"] for r in reviews.values()), key=SEVERITY.__getitem__)
    annotations.append(
        {
            "name": "Conversation quality",
            "label": worst,
            "score": float(worst == "PASS"),
            "explanation": "Worst verdict across the initial answer and follow-up. Assistant review; not human validation.",
        }
    )
    return annotations


def publish_phase(phase, scenarios, config: EvaluationSettings, state_path: Path, *, client=None):
    client = client or client_for(config)
    dataset = ensure_dataset(client, scenarios)
    project = ensure_project(client)
    state = read_json(state_path) if state_path.exists() else {}
    if state and (state.get("sha256") != phase["sha256"] or state.get("dataset_id") != dataset.id):
        raise ValueError("Publication state belongs to another phase or dataset")
    state.update(sha256=phase["sha256"], dataset_id=dataset.id, project_id=project["id"])
    # Collector ingestion may finish shortly after the export flush returns.
    for attempt in range(5):
        try:
            roots = collect_roots(client, phase, project["id"])
            break
        except MissingTraces:
            if attempt == 4:
                raise
            time.sleep(0.5)
    if "experiment_id" not in state:
        metadata = {k: v for k, v in phase.items() if k != "records"}
        experiment = client.experiments.create(
            dataset_id=dataset.id,
            dataset_version_id=dataset.version_id,
            # Phoenix 22 exports this name in a Latin-1 HTTP header.
            experiment_name=phase["name"].replace("—", "-"),
            experiment_metadata=metadata,
            experiment_description=(
                f"{phase['coverage']}; {len(phase['records']) * 2} captured turns. "
                f"Review: {phase['reviewer_kind']}. Unexecuted rows are not passes."
            ),
        )
        state["experiment_id"] = experiment["id"]
        write_json(state_path, state)
    span_annotations = []
    for case_id, record in phase["records"].items():
        for number, turn in enumerate(record["turns"], 1):
            if not turn.get("span_id"):
                continue
            metadata = {"case_id": case_id, "turn": number, "source_run": record["source_run"]}
            for name, label in (("Scenario", case_id), ("Evaluation phase", phase["name"])):
                span_annotations.append(
                    {
                        "span_id": turn["span_id"],
                        "name": name,
                        "annotator_kind": "CODE",
                        "identifier": "retail-conversations",
                        "result": {"label": label},
                        "metadata": metadata,
                    }
                )
            review = record["reviews"].get(str(number))
            span_annotations.append(
                {
                    "span_id": turn["span_id"],
                    "name": "Answer review",
                    "annotator_kind": "LLM" if review else "CODE",
                    "identifier": "retail-conversations",
                    "result": {
                        "label": review["verdict"] if review else "PENDING",
                        "explanation": "\n".join(review["findings"])
                        if review
                        else "Independent review pending.",
                    },
                    "metadata": {**metadata, "reviewer_kind": phase["reviewer_kind"]},
                }
            )
    if span_annotations:
        client.spans.log_span_annotations(span_annotations=span_annotations, sync=True)
    state.setdefault("runs", {})
    examples = {e["input"]["case_id"]: e["id"] for e in dataset.examples}
    for case_id, record in phase["records"].items():
        if case_id not in state["runs"]:
            spans = [roots[t["trace_id"]] for t in record["turns"] if t.get("trace_id")]
            if not spans:
                raise ValueError(
                    "A published conversation must contain at least one observed trace"
                )
            output = output_record(record, config.phoenix_url, project["id"])
            remote = client.experiments.log_run(
                experiment_id=state["experiment_id"],
                dataset_example_id=examples[case_id],
                output=output,
                start_time=min(datetime.fromisoformat(s["start_time"]) for s in spans),
                end_time=max(datetime.fromisoformat(s["end_time"]) for s in spans),
                trace_id=record["turns"][0].get("trace_id") or None,
                timeout=5,
            )
            state["runs"][case_id] = remote["id"]
            write_json(state_path, state)
        for annotation in quality_annotations(record):
            client.experiments.log_evaluation(
                experiment_run_id=state["runs"][case_id],
                **annotation,
                annotator_kind="LLM" if record["reviews"] else "CODE",
                metadata={
                    "reviewer_kind": phase["reviewer_kind"],
                    "human_validated": False,
                    "calibrated": False,
                    "review_files": phase["review_hashes"],
                },
                timeout=5,
            )
    state["url"] = client.experiments.get_experiment_url(
        dataset_id=dataset.id, experiment_id=state["experiment_id"]
    )
    state["project_url"] = config.phoenix_url + "/projects/" + quote(project["id"], safe="")
    state["status"] = "published"
    write_json(state_path, state)
    return state


def publish_history(
    history_path: Path, artifact_root: Path, config: EvaluationSettings, *, progress=print
):
    scenarios = load_scenarios(Path(__file__).parents[1] / "scenarios/manual_20.json")
    history = read_json(history_path)
    phases = [prepare_phase(p, artifact_root, scenarios) for p in history["phases"]]
    client = client_for(config)
    results = []
    for phase in phases:
        state_path = artifact_root / "phoenix" / f"{phase['sha256'][:20]}.json"
        state = publish_phase(phase, scenarios, config, state_path, client=client)
        results.append(state)
        progress(f"{phase['name']}: {state['url']}")
    return {
        "dataset_id": results[0]["dataset_id"],
        "project_id": results[0]["project_id"],
        "phases": results,
        "trace_ids": [
            t["trace_id"]
            for p in phases
            for r in p["records"].values()
            for t in r["turns"]
            if t.get("trace_id")
        ],
    }
