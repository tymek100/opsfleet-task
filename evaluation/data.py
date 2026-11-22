"""Load canonical cases and check their references against independent raw-row oracles."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation.models import Case, TurnReference
from evaluation.oracles.retail import (
    fixture_digest,
    fixture_file,
    load_fixture,
    render_sql,
    snapshot,
)

DATASETS = Path(__file__).resolve().parent / "datasets"
GOLDEN = DATASETS / "golden"


def load_cases(suite: str = "pilot") -> list[Case]:
    """Select a split, pilot, smoke/challenge suite, or comma-separated case IDs."""
    cases = [Case.model_validate_json(path.read_text()) for path in sorted(GOLDEN.glob("*/*.json"))]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Duplicate evaluation case ID")
    if suite in {"pilot", "all"}:
        return cases
    if suite in {"dev", "regression", "holdout"}:
        return [case for case in cases if case.split == suite]
    if suite == "smoke":
        return [case for case in cases if "smoke" in case.tags]
    if suite == "challenge":
        return [case for case in cases if case.purpose == "challenge"]
    wanted = set(suite.split(","))
    selected = [case for case in cases if case.id in wanted]
    if {case.id for case in selected} != wanted:
        raise ValueError(f"Unknown suite or case IDs: {suite}")
    return selected


def fixture_path(case: Case) -> Path:
    """Return a verified SQL fixture; keep references out of the runtime adapter."""
    if fixture_digest(case.fixture) != case.fixture_sha256:
        raise ValueError(f"Fixture hash mismatch: {case.id}")
    path = fixture_file(case.fixture, ".sql")
    if path.read_text() != render_sql(load_fixture(case.fixture)):
        raise ValueError(f"SQL fixture does not match canonical raw rows: {case.id}")
    return path


def reference_for(case: Case, step: str | int) -> TurnReference:
    """Resolve an ask-step ID or zero-based step index, never an action receipt."""
    step_id = case.steps[step].id if isinstance(step, int) else step
    return case.references[step_id]


def validate_case(case: Case) -> None:
    """Reject changed environments, unresolved oracle keys, and invalid controls."""
    fixture_path(case)
    truth = snapshot(case.fixture, case.identity)
    expected_scope = {"alice": "Calvin Klein", "bob": "Levi's", "ceo": "All brands"}[case.identity]
    for reference in case.references.values():
        if not reference.reference_procedure.strip():
            raise ValueError(f"Missing feasible reference procedure: {case.id}")
        for fact in reference.facts:
            if fact.source_key not in truth or truth[fact.source_key] != fact.value:
                raise ValueError(f"Invalid oracle fact: {case.id}/{fact.id}")
            if fact.scope != expected_scope:
                raise ValueError(
                    f"Fact scope differs from authorized identity: {case.id}/{fact.id}"
                )
        if (
            reference.answerability == "clarification_required"
            and "clarification" not in reference.allowed_outcomes
        ):
            raise ValueError(f"Clarification case forbids its correct outcome: {case.id}")
        if (
            reference.answerability == "access_denied"
            and "refusal" not in reference.allowed_outcomes
        ):
            raise ValueError(f"Denied case forbids its correct outcome: {case.id}")
    if case.split == "holdout" and not case.provenance.human_reviewed:
        raise ValueError(f"Unreviewed case cannot be a sealed holdout: {case.id}")


def load_calibration(split: str | None = None) -> list[dict[str, Any]]:
    records = [
        json.loads(path.read_text())
        for path in sorted((DATASETS / "judge_calibration").glob("*/*.json"))
    ]
    return [record for record in records if split is None or record["split"] == split]


def validate_dataset() -> dict[str, Any]:
    """Offline admission checks; generated controls do not claim human calibration."""
    cases: list[Case] = []
    errors = []
    seen: set[str] = set()
    for path in sorted(GOLDEN.glob("*/*.json")):
        try:
            case = Case.model_validate_json(path.read_text())
            cases.append(case)
            if case.id in seen:
                raise ValueError("Duplicate evaluation case ID")
            seen.add(case.id)
            validate_case(case)
            if path != GOLDEN / case.split / f"{case.id}.json":
                raise ValueError("Case path must match its split and ID")
        except (ValueError, OSError) as exc:
            errors.append({"case_id": path.stem, "status": "INVALID_CASE", "error": str(exc)})
    if not cases:
        errors.append({"case_id": "dataset", "status": "INVALID_CASE", "error": "No cases found"})
    calibration = []
    family_splits: dict[str, set[str]] = {}
    for path in sorted((DATASETS / "judge_calibration").glob("*/*.json")):
        try:
            record = json.loads(path.read_text())
            calibration.append(record)
            reference = TurnReference.model_validate(record["reference"])
            truth = snapshot(record["provenance"]["fixture"])
            if any(
                fact.source_key not in truth or truth[fact.source_key] != fact.value
                for fact in reference.facts
            ):
                raise ValueError("Calibration reference disagrees with independent oracle")
            if path.parent.name != record["split"] or path.stem != record["id"]:
                raise ValueError("Calibration path must match its split and ID")
            family_splits.setdefault(record["family"], set()).add(record["split"])
            if record["human_reviewed"] is not False or record["code_verified"] is not True:
                raise ValueError("Generated controls must state their actual review provenance")
            for claim in record["expected_claims"]:
                if claim["span"] not in record["answer"]:
                    raise ValueError("Expected claim span is absent from candidate")
                if claim["label"] not in {
                    "SUPPORTED",
                    "UNSUPPORTED",
                    "CONTRADICTED",
                    "NOT_FACTUAL",
                    "UNJUDGEABLE",
                }:
                    raise ValueError("Unknown calibration label")
        except (ValueError, KeyError, OSError) as exc:
            errors.append(
                {
                    "case_id": path.stem,
                    "status": "INVALID_CASE",
                    "error": str(exc),
                }
            )
    for family, splits in family_splits.items():
        if len(splits) != 1:
            errors.append(
                {
                    "case_id": family,
                    "status": "INVALID_CASE",
                    "error": "Calibration family crosses tuning/validation splits",
                }
            )
    return {
        "valid": not errors,
        "status": "VALID" if not errors else "INVALID_CASE",
        "cases": len(cases),
        "splits": dict(Counter(case.split for case in cases)),
        "families": dict(Counter(case.family for case in cases)),
        "fixtures": len({case.fixture for case in cases}),
        "calibration_controls": len(calibration),
        "human_reviewed_cases": sum(case.provenance.human_reviewed for case in cases),
        "sealed_holdout": sum(case.split == "holdout" for case in cases),
        "limitations": [
            "Generated pilot and calibration controls await human review.",
            "No sealed holdout or human-calibrated judge accuracy is claimed.",
        ],
        "errors": errors,
    }
