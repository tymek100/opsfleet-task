"""Independent conversation grades published as Foundry experiments."""

from pathlib import Path

from evaluation.graders.checks import combined
from evaluation.reporting.conversations import DATASET_NAME, dataset_rows
from evaluation.reporting.foundry import Experiment
from evaluation.results import Score
from evaluation.runners.artifacts import write_json


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
    directory: Path
    experiment: Experiment
    state: dict

    @classmethod
    def start(cls, client, config, directory, scenarios, name, references):
        obj = cls()
        obj.directory = directory
        obj.experiment = Experiment(
            client, DATASET_NAME, dataset_rows(scenarios, references), directory.name
        )
        obj.state = {"url": obj.experiment.url, "traces_url": obj.experiment.url}
        write_json(directory / "foundry.json", obj.state)
        return obj

    def record(self, scenario, turns, grade):
        self.experiment.record(
            scenario.id,
            {"turns": [t.model_dump(mode="json") for t in turns], "evaluation": grade},
            grade_annotations(grade),
        )

    def finalize(self):
        self.state.update(self.experiment.finalize())
        write_json(self.directory / "foundry.json", self.state)
        return self.state
