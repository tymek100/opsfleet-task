"""Stable Phoenix datasets and incremental experiments for the three agent suites."""

from evaluation.graders.checks import combined
from evaluation.results import Score

from .oracle import checksum, reference

NAMES = {
    role: f"{role.title()} agent - 20 conversations"
    for role in ("inventory", "distribution", "coordinator")
}


def dataset_rows(role, cases, snapshot):
    return [
        {
            "input": {
                "suite": role,
                "case_id": case["id"],
                "identity": case["identity"],
                "question": case["question"],
                "follow_up": case["follow_up"],
            },
            "output": {
                "turns": {
                    f"turn-{i}": reference(snapshot, case, i).model_dump(mode="json")
                    for i in (1, 2)
                },
                "provenance": {
                    "source": "authored development scenarios",
                    "oracle": "raw-row Decimal/set calculations",
                    "oracle_verified": True,
                    "human_reviewed": False,
                    "judge_calibrated": False,
                    "sealed_holdout": False,
                    "source_sha256": snapshot.sha256,
                    "as_of": snapshot.as_of.isoformat(),
                    "snapshot_at": snapshot.snapshot_at,
                },
            },
            "metadata": {
                "suite": role,
                "case_id": case["id"],
                "split": "dev",
                "reference_sha256": checksum(
                    [reference(snapshot, case, i).model_dump(mode="json") for i in (1, 2)]
                ),
            },
        }
        for case in cases
    ]


def ensure_dataset(client, role, cases, snapshot):
    rows = dataset_rows(role, cases, snapshot)
    name = NAMES[role]
    try:
        dataset = client.datasets.get_dataset(dataset=name, timeout=15)
    except ValueError as exc:
        if not str(exc).startswith("Dataset not found:"):
            raise
        return client.datasets.create_dataset(
            name=name,
            inputs=[r["input"] for r in rows],
            outputs=[r["output"] for r in rows],
            metadata=[r["metadata"] for r in rows],
            dataset_description="20 authored two-turn development conversations. Independent raw-row reference facts and illustrative answers; human validation and judge calibration pending. Actual agent answers are experiment outputs.",
            timeout=30,
        )
    current = {r["input"]["case_id"]: r for r in dataset.examples}
    expected = {r["input"]["case_id"]: r for r in rows}
    if current.keys() != expected.keys():
        raise ValueError(
            f"Unexpected scenario membership in Phoenix dataset {name}; refusing destructive replacement"
        )
    if any(
        any(current[key].get(field) != value[field] for field in ("input", "output", "metadata"))
        for key, value in expected.items()
    ):
        dataset = client.datasets.create_dataset(
            name=name,
            examples=[{"id": current[row["input"]["case_id"]]["id"], **row} for row in rows],
            timeout=30,
        )
    return dataset


class Publisher:
    def __init__(self, client, role, cases, snapshot, run_id):
        self.client = client
        self.dataset = ensure_dataset(client, role, cases, snapshot)
        self.experiment = client.experiments.create(
            dataset_id=self.dataset.id,
            dataset_version_id=self.dataset.version_id,
            experiment_name=run_id,
            experiment_description="A2A execution with independent numerical checks and model judgments. Failures and missing execution remain visible.",
            experiment_metadata={
                "suite": role,
                "source_sha256": snapshot.sha256,
                "human_calibrated": False,
            },
        )
        self.url = client.experiments.get_experiment_url(self.dataset.id, self.experiment["id"])
        self.example_ids = {e["input"]["case_id"]: e["id"] for e in self.dataset.examples}

    def record(self, case, turns, grades, started_at, ended_at, *, trajectory=None):
        run = self.client.experiments.log_run(
            experiment_id=self.experiment["id"],
            dataset_example_id=self.example_ids[case["id"]],
            output={
                "initial": turns[0] if turns else None,
                "follow_up": turns[1] if len(turns) > 1 else None,
                "evaluation": grades,
                "trajectory": trajectory,
            },
            start_time=started_at,
            end_time=ended_at,
            trace_id=next((t.get("trace_id") for t in turns if t.get("trace_id")), None),
            timeout=20,
        )
        for index, grade in enumerate(grades, 1):
            self.client.experiments.log_evaluation(
                experiment_run_id=run["id"],
                name=f"{'Initial' if index == 1 else 'Follow-up'} answer",
                label=grade["status"],
                score=1.0
                if grade["status"] == "PASS"
                else 0.0
                if grade["status"] == "FAIL"
                else None,
                explanation="\n".join(s["finding"] for s in grade["scores"]),
                annotator_kind="LLM",
                metadata={
                    "method": "Independent Decimal/set oracle; LLM extracts bound facts and assesses observed evidence.",
                    "human_calibrated": False,
                },
                timeout=20,
            )
            for title, names, kind in (
                ("Numerical correctness", {"numeric_fact", "numeric_partition_component"}, "CODE"),
                ("Grounding", {"claim_support"}, "LLM"),
                (
                    "Task completion",
                    {"semantic", "acceptable_outcome", "reviewed_completion"},
                    "LLM",
                ),
            ):
                selected = [s for s in grade["scores"] if s["name"] in names]
                label = combined([Score.model_validate(s) for s in selected])
                self.client.experiments.log_evaluation(
                    experiment_run_id=run["id"],
                    name=f"{'Initial' if index == 1 else 'Follow-up'} / {title}",
                    label=label,
                    score=1.0 if label == "PASS" else 0.0 if label == "FAIL" else None,
                    explanation="\n".join(s["finding"] for s in selected)
                    or "No applicable result; see the overall turn evaluation for execution or judgment errors.",
                    annotator_kind=kind,
                    metadata={
                        "method": "Code comparison uses LLM-extracted exact answer excerpts; no number-presence matching.",
                        "human_calibrated": False,
                    },
                    timeout=20,
                )
        if trajectory:
            self.client.experiments.log_evaluation(
                experiment_run_id=run["id"],
                name="Observable trajectory",
                label=trajectory["status"],
                score=1.0
                if trajectory["status"] == "PASS"
                else 0.0
                if trajectory["status"] == "FAIL"
                else None,
                explanation="\n".join(s["finding"] for s in trajectory["scores"]),
                annotator_kind="LLM",
                metadata={"human_calibrated": False},
                timeout=20,
            )
        return run["id"]
