"""Blind judge controls and versioned rescoring; synthetic labels are not human calibration."""

import re
from collections import Counter
from pathlib import Path

from evaluation.graders.checks import combined, judged_scores
from evaluation.graders.judge import JudgeUnavailable, validate_judgment
from evaluation.models import TurnReference
from evaluation.results import Judgment, TurnRecord
from evaluation.runners.artifacts import digest, identifier, read_json, write_json


def control_turn(control: dict) -> TurnRecord:
    evidence = control["evidence"]
    if isinstance(evidence, dict):
        evidence = [evidence]
    return TurnRecord(
        step_id=control["id"],
        prompt=control["question"],
        status="approved",
        markdown=control["answer"],
        outcome="answer",
        observations=[{"event": "tool_observation", "result": item} for item in evidence],
    )


def expected_claim_scores(control: dict, judgment: Judgment) -> list[dict]:
    """Check supplied sentinel spans, allowing an evaluator to split atomic claims.

    Coverage is lexical coverage of code-authored spans, not human extraction recall.
    Label detection is reported separately so one supported fragment cannot hide an
    uncovered causal assertion elsewhere in the expected span.
    """
    answer = control["answer"]
    predictions = []
    for claim in judgment.claims:
        start = answer.find(claim.span)
        if start >= 0:
            predictions.append((start, start + len(claim.span), claim.label))
    result = []
    for expected in control.get("expected_claims", []):
        start = answer.find(expected["span"])
        words = (
            [
                (start + match.start(), start + match.end())
                for match in re.finditer(r"\w+", expected["span"])
            ]
            if start >= 0
            else []
        )
        covered = sum(
            any(left <= a and b <= right for left, right, _ in predictions) for a, b in words
        )
        overlap = [
            label
            for left, right, label in predictions
            if start >= 0 and left < start + len(expected["span"]) and start < right
        ]
        result.append(
            {
                "span": expected["span"],
                "expected_label": expected["label"],
                "observed_labels": sorted(set(overlap)),
                "covered_words": covered,
                "expected_words": len(words),
                "fully_covered": bool(words) and covered == len(words),
                "label_detected": expected["label"] in overlap,
            }
        )
    return result


def calibration_metrics(controls: list[dict], records: list[dict]) -> dict:
    by_id = {record["id"]: record for record in records}
    confusion = Counter()
    labels = Counter()
    expected_claims = covered_claims = detected_labels = expected_facts = extracted_facts = 0
    resolved = 0
    details = []
    for control in controls:
        record = by_id.get(control["id"], {})
        expected = "PASS" if control["expected_pass"] else "FAIL"
        expected_claims += len(control.get("expected_claims", []))
        expected_facts += len(control["reference"].get("facts", []))
        if not record.get("judgment"):
            actual = record.get("actual", "NOT_EXECUTED")
            confusion[f"{expected}_as_{actual}"] += 1
            details.append(
                {
                    "id": control["id"],
                    "expected": expected,
                    "actual": actual,
                    "claim_checks": [],
                    "error": record.get("error", "Missing judgment"),
                }
            )
            continue
        try:
            turn = control_turn(control)
            reference = TurnReference.model_validate(control["reference"])
            judgment = Judgment.model_validate(record["judgment"])
            validate_judgment(judgment, turn, reference)
            scores = judged_scores(turn, reference, judgment, [])
            actual = combined(scores)
            checks = expected_claim_scores(control, judgment)
            covered_claims += sum(check["fully_covered"] for check in checks)
            detected_labels += sum(
                check["label_detected"] and check["fully_covered"] for check in checks
            )
            for check in checks:
                labels[
                    f"{check['expected_label']}_as_{'+'.join(check['observed_labels']) or 'MISSING'}"
                ] += 1
            extracted_facts += len(judgment.facts)
            resolved += int(actual in {"PASS", "FAIL"})
            details.append(
                {
                    "id": control["id"],
                    "expected": expected,
                    "actual": actual,
                    "claim_checks": checks,
                    "scores": [score.model_dump(mode="json") for score in scores],
                }
            )
        except ValueError:
            actual = "ERROR"
            details.append(
                {
                    "id": control["id"],
                    "expected": expected,
                    "actual": actual,
                    "claim_checks": [],
                    "error": "Invalid saved judgment",
                }
            )
        confusion[f"{expected}_as_{actual}"] += 1

    def rate(numerator, denominator):
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": numerator / denominator if denominator else None,
        }

    return {
        "human_calibrated": False,
        "qualification": "Code-authored control agreement and span coverage; not human accuracy or claim-extraction recall.",
        "controls": len(controls),
        "records": len(records),
        "confusion": dict(confusion),
        "resolved_control_coverage": rate(resolved, len(controls)),
        "synthetic_expected_claim_coverage": rate(covered_claims, expected_claims),
        "synthetic_label_agreement_on_covered_claims": rate(detected_labels, covered_claims),
        "expected_label_confusion": dict(labels),
        "required_fact_extraction_coverage": rate(extracted_facts, expected_facts),
        "claim_extraction_recall": {
            "status": "NOT_MEASURED",
            "reason": "Human-annotated atomic claims are unavailable",
        },
        "control_details": details,
    }


def score_saved_controls(directory: Path, controls: list[dict] | None = None) -> Path:
    """Append rescored diagnostics without changing original results or calling a model."""
    frozen = directory / "reference_controls.json"
    selected = controls if controls is not None else read_json(frozen)
    records_path = directory / "controls.json"
    records = read_json(records_path)
    if len({item["id"] for item in selected}) != len(selected):
        raise ValueError("Duplicate control IDs")
    if {item["id"] for item in records} - {item["id"] for item in selected}:
        raise ValueError("Saved judgments include controls absent from the supplied reference set")
    target = directory / "rescores" / identifier("score")
    target.mkdir(parents=True, exist_ok=False)
    write_json(target / "reference_controls.json", selected)
    result = calibration_metrics(selected, records)
    original = (
        read_json(directory / "summary.json") if (directory / "summary.json").exists() else {}
    )
    result.update(
        judge=original.get("judge"), accounted_judge_usd=original.get("accounted_judge_usd", 0)
    )
    write_json(target / "summary.json", result)
    write_json(
        target / "manifest.json",
        {
            "schema_version": "1",
            "source_records_sha256": digest(records_path),
            "reference_controls_sha256": digest(target / "reference_controls.json"),
            "grader_code_sha256": grader_hashes(),
            "source_judge": original.get("judge"),
            "model_calls": 0,
        },
    )
    return target


def grader_hashes() -> dict[str, str]:
    return {path.name: digest(path) for path in sorted(Path(__file__).parent.glob("*.py"))}


async def calibrate(controls: list[dict], judge, artifact_root: Path) -> Path:
    directory = artifact_root / identifier("calibration")
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "reference_controls.json", controls)
    write_json(
        directory / "manifest.json",
        {
            "schema_version": "1",
            "judge": judge.version,
            "human_calibrated": False,
            "controls_sha256": digest(directory / "reference_controls.json"),
            "grader_code_sha256": grader_hashes(),
            "planned_controls": len(controls),
        },
    )
    records = []
    for control in controls:
        reference = TurnReference.model_validate(control["reference"])
        turn = control_turn(control)
        expected = "PASS" if control["expected_pass"] else "FAIL"
        try:
            result = await judge.evaluate(turn, reference, [])
            validate_judgment(result, turn, reference)
            scores = judged_scores(turn, reference, result, [])
            record = {
                "id": control["id"],
                "expected": expected,
                "actual": combined(scores),
                "judgment": result.model_dump(mode="json"),
                "scores": [score.model_dump(mode="json") for score in scores],
            }
        except (JudgeUnavailable, ValueError) as exc:
            record = {
                "id": control["id"],
                "expected": expected,
                "actual": "ERROR",
                "error": type(exc).__name__,
            }
        records.append(record)
        write_json(directory / "controls.json", records)
        write_json(directory / "judge_calls.json", judge.calls)
    summary = calibration_metrics(controls, records)
    summary.update(judge=judge.version, accounted_judge_usd=judge.accounted_usd)
    write_json(directory / "summary.json", summary)
    return directory
