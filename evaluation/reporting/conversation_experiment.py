"""Incremental automatic grades on the same curated Phoenix conversation dataset."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from evaluation.graders.checks import combined
from evaluation.reporting.conversations import checksum, ensure_dataset, ensure_project
from evaluation.results import Score
from evaluation.runners.artifacts import read_json, write_json


def summary_score(name, values):
    scores = [Score.model_validate(s).model_copy(update={"blocks_success": True}) for s in values]
    status = combined(scores)
    return {
        "name": name,
        "label": status,
        "score": 1.0 if status == "PASS" else 0.0 if status == "FAIL" else None,
        "explanation": "\n".join(f"{s.status}: {s.finding}" for s in scores)
        or "Not applicable to this question.",
    }


def grade_annotations(grade):
    result = []
    for turn in grade["turns"]:
        prefix = "Initial" if turn["step_id"] == "turn-1" else "Follow-up"
        result.append(summary_score(f"{prefix} answer", turn["scores"]))
        for title, names in (
            ("Numerical correctness", {"numeric_fact", "selection", "follow_up_binding"}),
            ("Grounding", {"claim_support", "claim_judgment_coverage"}),
            ("Task completion", {"semantic", "response_kind", "acceptable_outcome", "format"}),
        ):
            result.append(
                summary_score(
                    f"{prefix} / {title}", [s for s in turn["scores"] if s["name"] in names]
                )
            )
    result.append(
        summary_score(
            "Operations", [s for s in grade["scores"] if not s["name"].startswith("trajectory")]
        )
    )
    result.append(
        summary_score(
            "Trajectory", [s for s in grade["scores"] if s["name"].startswith("trajectory")]
        )
    )
    result.append(
        summary_score(
            "Conversation quality",
            [
                {"name": "turn", "status": g["status"], "finding": g["step_id"]}
                for g in grade["turns"]
            ]
            + [s for s in grade["scores"] if s.get("blocks_success", True)],
        )
    )
    return result


class ConversationExperiment:
    def __init__(self, client, config, directory: Path, dataset, project, name, references):
        self.client, self.config, self.directory = client, config, directory
        self.dataset, self.project = dataset, project
        self.references = references
        self.path = directory / "phoenix-auto.json"
        self.state = read_json(self.path) if self.path.exists() else {}
        if self.state and (
            self.state["dataset_version_id"] != dataset.version_id
            or self.state["reference_sha256"] != checksum(references)
        ):
            raise ValueError("Publication state belongs to different reference data")
        self.state.update(
            dataset_id=dataset.id,
            dataset_version_id=dataset.version_id,
            project_id=project["id"],
            reference_sha256=checksum(references),
        )
        if "experiment_id" not in self.state:
            experiment = client.experiments.create(
                dataset_id=dataset.id,
                dataset_version_id=dataset.version_id,
                experiment_name=name.replace("—", "-"),
                experiment_description="Independent numeric checks, evidence grounding and task/operation checks. LLM judge is not human-calibrated. Historical assistant reviews remain separate.",
                experiment_metadata={
                    "source_run": directory.name,
                    "reference_provenance": references["provenance"],
                    "reference_sha256": checksum(references),
                    "reviewer_kind": "automatic_independent_evaluation",
                },
            )
            self.state["experiment_id"] = experiment["id"]
        self.state.setdefault("runs", {})
        self.state["url"] = client.experiments.get_experiment_url(
            dataset.id, self.state["experiment_id"]
        )
        self.state["traces_url"] = config.phoenix_url + "/projects/" + quote(project["id"], safe="")
        write_json(self.path, self.state)

    @classmethod
    def start(cls, client, config, directory, scenarios, name, references):
        dataset = ensure_dataset(client, scenarios, references)
        project = ensure_project(client)
        return cls(client, config, directory, dataset, project, name, references)

    def record(self, scenario, turns, grade):
        output = {
            "source_run": self.directory.name,
            "reference_provenance": self.references["provenance"],
            "evaluation": grade,
        }
        for number, turn in enumerate(turns, 1):
            output["initial" if number == 1 else "follow_up"] = {
                "question": turn.prompt,
                "answer": turn.markdown,
                "runtime_status": turn.status,
                "trace_url": f"{self.state['traces_url']}/traces/{turn.trace_id}"
                if turn.trace_id
                else None,
            }
        if scenario.id not in self.state["runs"]:
            identifiers = [t.trace_id for t in turns if t.trace_id]
            spans = (
                self.client.spans.get_spans(
                    project_identifier=self.project["id"],
                    trace_ids=identifiers,
                    name="retail.prompt",
                    limit=10,
                )
                if identifiers
                else []
            )
            # Ingestion is asynchronous; never invent execution times for a missing trace.
            for _ in range(10):
                if {s["context"]["trace_id"] for s in spans} >= set(identifiers):
                    break
                time.sleep(0.2)
                spans = self.client.spans.get_spans(
                    project_identifier=self.project["id"],
                    trace_ids=identifiers,
                    name="retail.prompt",
                    limit=10,
                )
            if {s["context"]["trace_id"] for s in spans} < set(identifiers):
                raise ValueError("Original prompt traces have not reached Phoenix")
            timestamps = [datetime.fromisoformat(s["start_time"]) for s in spans]
            endings = [datetime.fromisoformat(s["end_time"]) for s in spans]
            example = next(e for e in self.dataset.examples if e["input"]["case_id"] == scenario.id)
            # No trace is invented for an unexecuted task. Timestamp is publication time in that case.
            now = datetime.now(UTC)
            run = self.client.experiments.log_run(
                experiment_id=self.state["experiment_id"],
                dataset_example_id=example["id"],
                output=output,
                start_time=min(timestamps) if timestamps else now,
                end_time=max(endings) if endings else now,
                trace_id=turns[0].trace_id if turns else None,
                timeout=10,
            )
            self.state["runs"][scenario.id] = run["id"]
            write_json(self.path, self.state)
        for annotation in grade_annotations(grade):
            self.client.experiments.log_evaluation(
                experiment_run_id=self.state["runs"][scenario.id],
                **annotation,
                annotator_kind="CODE" if annotation["name"] == "Operations" else "LLM",
                metadata={
                    "reference_sha256": self.state["reference_sha256"],
                    "judge": grade["judge"],
                    "method": "Independent reference comparison after LLM extraction; separate evidence and behavioral judgments.",
                    "human_calibrated": False,
                },
                timeout=10,
            )
        span_annotations = []
        for turn, assessed in zip(turns, grade["turns"], strict=True):
            if not turn.span_id:
                continue
            for name, label, kind in (
                ("Scenario", scenario.id, "CODE"),
                ("Automatic answer evaluation", assessed["status"], "LLM"),
            ):
                span_annotations.append(
                    {
                        "span_id": turn.span_id,
                        "name": name,
                        "annotator_kind": kind,
                        "identifier": self.state["experiment_id"],
                        "result": {"label": label},
                        "metadata": {
                            "reference_sha256": self.state["reference_sha256"],
                            "step_id": turn.step_id,
                        },
                    }
                )
        if span_annotations:
            self.client.spans.log_span_annotations(span_annotations=span_annotations, sync=True)
        self.state["status"] = "published"
        write_json(self.path, self.state)
