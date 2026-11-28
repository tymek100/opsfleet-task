"""Independent domain references and Foundry experiment publication."""

from evaluation.reporting.foundry import Experiment, ensure_rows

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
    return ensure_rows(client, NAMES[role], dataset_rows(role, cases, snapshot))


class Publisher:
    def __init__(self, client, role, cases, snapshot, run_id):
        self.experiment = Experiment(
            client, NAMES[role], dataset_rows(role, cases, snapshot), run_id + "-" + role
        )
        self.url = self.experiment.url

    def record(self, case, turns, grades, started_at, ended_at, *, trajectory=None):
        scores = []
        for i, grade in enumerate(grades, 1):
            scores.append({"name": f"turn-{i}/answer", "status": grade["status"]})
            for n, score in enumerate(grade["scores"]):
                scores.append({**score, "name": f"turn-{i}/{score['name']}/{n}"})
        if trajectory:
            scores.extend({**s, "name": "trajectory/" + s["name"]} for s in trajectory["scores"])
        return self.experiment.record(
            case["id"],
            {"turns": turns, "evaluation": grades, "trajectory": trajectory},
            scores,
            started_at,
            ended_at,
        )

    def finalize(self):
        return self.experiment.finalize()
