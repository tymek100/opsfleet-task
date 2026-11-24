"""Post-hoc labels must target the correct run, role and candidate verdict."""

import pytest

from evaluation.multi_agent.inspections import parse_report


def test_comparison_report_selects_candidate_verdict_without_relabeling_baseline(tmp_path):
    path = tmp_path / "review.md"
    path.write_text(
        "Run: `a2a-20261124T195511Z-d0f6edc6`\n"
        "| Scenario | Turn | Baseline manual verdict | Candidate manual verdict | Finding |\n"
        "| scenario-02 | 1 | FAIL | PASS | Fixed the source interpretation. |\n"
    )
    rows = parse_report(path, "distribution")
    assert len(rows) == 1 and rows[0]["status"] == "PASS"
    assert rows[0]["run_id"] == "a2a-20261124T195511Z-d0f6edc6"
    assert rows[0]["role"] == "distribution"


def test_mixed_role_report_rejects_duplicate_turn_labels(tmp_path):
    path = tmp_path / "review.md"
    path.write_text(
        "Run: `a2a-20261124T195511Z-d0f6edc6`\n"
        "| Agent | Scenario | Turn | Verdict | Finding |\n"
        "| Inventory | scenario-02 | 1 | PASS | Supported. |\n"
        "| Inventory | scenario-02 | 1 | FAIL | Conflicting duplicate. |\n"
    )
    with pytest.raises(ValueError, match="Duplicate"):
        parse_report(path)
