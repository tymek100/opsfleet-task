"""Comparison completeness and declared denominators."""

import pytest

from evaluation.reporting.compare import compare
from evaluation.reporting.summary import summarize
from evaluation.results import Trial, TrialGrade
from evaluation.runners.artifacts import write_json


def test_missing_attempts_do_not_inflate_consistency():
    manifest = {
        "id": "run",
        "planned_trials": 3,
        "repetitions": 3,
        "case_ids": ["task"],
        "completed_trials": 1,
        "accounted_usd": 0.4,
    }
    trial = Trial(
        id="task-r1", case_id="task", repetition=1, status="completed", elapsed_seconds=10
    )
    grade = TrialGrade(
        trial_id=trial.id, case_id=trial.case_id, repetition=1, status="PASS", turns=[]
    )
    result = summarize(manifest, [trial], [grade], {"id": "grade"})
    assert result["task_success_over_planned"]["value"] == pytest.approx(1 / 3)
    assert result["all_repetitions_success"]["value"] is None
    assert result["unresolved_or_missing"] == 2
    assert result["agent_cost_per_success"] == 0.4


def test_compare_rejects_changed_judge_and_preserves_uncertainty(tmp_path):
    metadata = {
        "dataset_sha256": "same",
        "judge": {"model": "judge"},
        "prompt_sha256": "same",
        "grade_candidates": True,
        "grader_code_sha256": "same",
        "artifact_schema_version": "1",
        "report_schema_version": "1",
    }
    baseline, candidate = tmp_path / "baseline", tmp_path / "candidate"
    for path in (baseline, candidate):
        write_json(path / "manifest.json", metadata)
        write_json(
            path / "trials/task-r1.json",
            {"case_id": "task", "repetition": 1, "status": "UNJUDGEABLE"},
        )
    assert compare(baseline, candidate)["status"] == "INCONCLUSIVE"
    write_json(candidate / "manifest.json", {**metadata, "judge": {"model": "different"}})
    with pytest.raises(ValueError, match="judge"):
        compare(baseline, candidate)
