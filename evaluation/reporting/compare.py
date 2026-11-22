"""Paired case comparisons, refusing incompatible or incomplete evaluations."""

import random
from collections import defaultdict
from pathlib import Path

from evaluation.runners.artifacts import read_json


def compare(baseline: Path, candidate: Path) -> dict:
    left_meta, right_meta = (read_json(p / "manifest.json") for p in (baseline, candidate))
    for key in (
        "dataset_sha256",
        "judge",
        "prompt_sha256",
        "grade_candidates",
        "grader_code_sha256",
        "artifact_schema_version",
        "report_schema_version",
    ):
        if left_meta[key] != right_meta[key]:
            raise ValueError(f"Incompatible comparison: {key} changed")
    if left_meta.get("grade_trajectory", False) != right_meta.get("grade_trajectory", False):
        raise ValueError("Incompatible comparison: grade_trajectory changed")
    if left_meta.get("trajectory_evaluator") != right_meta.get("trajectory_evaluator"):
        raise ValueError("Incompatible comparison: trajectory_evaluator changed")

    def scores(directory):
        return {
            (g["case_id"], g["repetition"]): g
            for path in (directory / "trials").glob("*.json")
            for g in [read_json(path)]
        }

    left, right = scores(baseline), scores(candidate)
    if set(left) != set(right) or not left:
        raise ValueError("Comparison requires identical nonempty case/repetition sets")
    unresolved = [
        key
        for key in left
        if any(g["status"] not in {"PASS", "FAIL"} for g in (left[key], right[key]))
    ]
    if unresolved:
        return {
            "status": "INCONCLUSIVE",
            "reason": "Unresolved or unexecuted paired trials",
            "unresolved": unresolved,
        }
    by_case = defaultdict(list)
    for key in left:
        by_case[key[0]].append(
            int(right[key]["status"] == "PASS") - int(left[key]["status"] == "PASS")
        )
    differences = [sum(values) / len(values) for values in by_case.values()]
    delta = sum(differences) / len(differences)
    interval = None
    if len(differences) >= 10:
        rng = random.Random(17)
        draws = sorted(
            sum(rng.choices(differences, k=len(differences))) / len(differences)
            for _ in range(2000)
        )
        interval = [draws[50], draws[1949]]
    return {
        "status": "DIAGNOSTIC",
        "paired_cases": len(by_case),
        "paired_trials": len(left),
        "case_mean_success_change": delta,
        "case_cluster_bootstrap_95_interval": interval,
        "qualification": "Exploratory, not a release gate; synthetic controls lack human calibration. "
        "No interval is reported below ten case clusters. Family correlation remains a limitation.",
    }
