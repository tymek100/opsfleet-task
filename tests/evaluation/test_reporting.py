"""Comparison completeness and declared denominators."""

import pytest

from evaluation.reporting.compare import compare
from evaluation.reporting.summary import summarize
from evaluation.results import Score, Trial, TrialGrade, TurnGrade
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
    write_json(candidate / "manifest.json", {**metadata, "trajectory_evaluator": {"policy": "new"}})
    with pytest.raises(ValueError, match="trajectory_evaluator"):
        compare(baseline, candidate)


def test_known_failure_does_not_hide_unresolved_checks_or_draft_grades():
    trial = Trial(id="task-r1", case_id="task", repetition=1, status="completed")
    grade = TrialGrade(
        trial_id=trial.id,
        case_id=trial.case_id,
        repetition=1,
        status="FAIL",
        turns=[
            TurnGrade(
                step_id="ask",
                status="FAIL",
                scores=[
                    Score(name="format", status="FAIL", finding="Known failure"),
                    Score(name="independent_judgment", status="ERROR", finding="Missing judge"),
                ],
                candidate_grades=[
                    {
                        "status": "FAIL",
                        "scores": [{"name": "independent_judgment", "status": "ERROR"}],
                    }
                ],
            )
        ],
    )
    result = summarize(
        {
            "id": "run",
            "planned_trials": 1,
            "repetitions": 1,
            "case_ids": ["task"],
            "completed_trials": 1,
            "accounted_usd": 0,
        },
        [trial],
        [grade],
        {"id": "grade", "grade_candidates": True},
    )
    assert result["statuses"] == {"FAIL": 1}
    assert result["unresolved_required_checks"] == 1
    assert result["candidate_grading"]["unresolved"] == 1
