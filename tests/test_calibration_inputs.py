"""Calibration labels stay out of the actual review input."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from retail_agent.config import repository_root

ROOT = repository_root()


def test_ranking_calibration_preserves_evidence_and_prior_answer() -> None:
    load_cases = runpy.run_path(str(ROOT / "scripts/calibrate_reviewer.py"))["load_cases"]
    cases = load_cases(ROOT / "evals/rewrite/runs/fixture-smoke-01", "ranking_grounding")
    capture = json.loads((ROOT / "evals/rewrite/runs/ranking-ties-03/rankings-1.json").read_text())
    answer = capture["result"]["answer"]
    evidence = [
        item for item in capture["result"]["evidence"] if item["id"] in answer["evidence_ids"]
    ]
    assert len(cases) == 4
    assert [case["expected_decisions"] for case in cases] == [
        ["revise"],
        ["revise"],
        ["approve"],
        ["approve"],
    ]
    for case in cases:
        payload = case["payload"]
        assert payload["evidence"] == evidence
        assert payload["conversation"][0]["markdown"] == answer["markdown"]
        assert payload["conversation"][0]["evidence_ids"] == answer["evidence_ids"]
        assert payload["pending_save"] is None
        assert payload["save_target"] is None


def test_changing_expected_labels_cannot_change_reviewer_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_cases = runpy.run_path(str(ROOT / "scripts/calibrate_reviewer.py"))["load_cases"]
    source = ROOT / "evals/rewrite/runs/fixture-smoke-01"
    original = load_cases(source, "ranking_grounding")
    fixture = json.loads((ROOT / "evals/rewrite/ranking_grounding_cases.json").read_text())
    fixture["source_capture"] = str(ROOT / fixture["source_capture"])
    for case in fixture["cases"]:
        case["expected_decisions"] = ["LABEL_MUST_NOT_ENTER_MODEL_INPUT"]
        case["known_issue"] = "GRADER_FEEDBACK_MUST_NOT_ENTER_MODEL_INPUT"
    path = tmp_path / "evals/rewrite/ranking_grounding_cases.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(fixture))
    monkeypatch.setitem(load_cases.__globals__, "ROOT", tmp_path)
    mutated = load_cases(source, "ranking_grounding")
    assert [case["payload"] for case in mutated] == [case["payload"] for case in original]
    assert all(case["expected_decisions"] != original[0]["expected_decisions"] for case in mutated)


def test_original_four_case_suite_remains_available() -> None:
    load_cases = runpy.run_path(str(ROOT / "scripts/calibrate_reviewer.py"))["load_cases"]
    cases = load_cases(ROOT / "evals/rewrite/runs/fixture-smoke-01")
    assert {case["id"] for case in cases} == {
        "monthly_distinct_total",
        "inactivity_eligibility_without_purchases",
        "invented_currency",
        "correct_concise_aov_control",
    }
    assert all(not case["payload"]["conversation"] for case in cases)
