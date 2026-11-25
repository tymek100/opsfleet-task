"""Metric binding and state checks; no SQL-text or number-presence scoring."""

import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from evaluation.models import Case, Fact, TurnReference
from evaluation.results import Judgment, Score, ScoreStatus, Trial, TurnRecord


def verdict(name: str, passed: bool, finding: str, **kwargs) -> Score:
    return Score(
        name=name,
        status="PASS" if passed else "FAIL",
        value=float(passed),
        finding=finding,
        **kwargs,
    )


def combined(scores: list[Score]) -> ScoreStatus:
    required = [s for s in scores if s.blocks_success]
    states: tuple[ScoreStatus, ...] = ("FAIL", "ERROR", "UNJUDGEABLE")
    for state in states:
        if any(s.status == state for s in required):
            return state
    return "PASS" if required else "NOT_APPLICABLE"


def _numeric(value: str) -> Decimal:
    result = Decimal(value.replace(",", "").replace("\u2212", "-").replace("%", "").strip())
    if not result.is_finite():
        raise InvalidOperation
    return result


def value_matches(fact: Fact, value: str | None, span: str) -> bool:
    if fact.value_type == "null":
        return value is None and bool(
            re.search(r"undefined|not (?:available|applicable|defined)|n/a|null|—", span, re.I)
        )
    if value is None or fact.value is None:
        return False
    if fact.value_type == "text":
        return value.casefold() == fact.value.casefold() and value.casefold() in span.casefold()
    try:
        number = _numeric(value)
        # The extractor must quote the actual value; prevent an invented reference value.
        shown = re.findall(r"(?<![\w.])[-+\u2212]?(?:\d[\d,]*)(?:\.\d+)?%?(?!\w|\.\d)", span)
        present = any(_numeric(token) == number for token in shown)
        return present and abs(number - _numeric(fact.value)) <= fact.tolerance
    except (InvalidOperation, ValueError):
        return False


def numeric_scores(reference: TurnReference, judgment: Judgment) -> list[Score]:
    extracted = {f.id: f for f in judgment.facts}
    scores = []
    for fact in reference.facts:
        item = extracted.get(fact.id)
        passed = item is not None and value_matches(fact, item.value, item.span)
        scores.append(
            verdict(
                "numeric_fact",
                passed,
                f"{fact.entity}; {fact.metric}; {fact.period}; {fact.scope}: "
                f"expected {fact.value!r}, extracted {item.value if item else 'MISSING'!r}",
                criterion_id=fact.id,
            )
        )
    return scores


def _evidence_ids(value) -> set[str]:
    if isinstance(value, dict):
        result = (
            {value["id"]}
            if isinstance(value.get("id"), str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["id"])
            else set()
        )
        for key in value.get("evidence_ids", []):
            if isinstance(key, str) and re.fullmatch(r"E\d+", key):
                result.add(key)
        for key, child in value.items():
            if key != "rows":
                result |= _evidence_ids(child)
        return result
    if isinstance(value, list):
        return set().union(*(_evidence_ids(child) for child in value)) if value else set()
    return set()


def grounding_scores(turn: TurnRecord, judgment: Judgment, prior: list[dict]) -> list[Score]:
    ids = _evidence_ids([turn.context, *turn.observations])
    unknown = {i for claim in judgment.claims for i in claim.evidence_ids if i not in ids}
    if unknown:
        return [
            Score(
                name="claim_support",
                status="ERROR",
                finding="Judge cited unobserved evidence IDs: " + ", ".join(sorted(unknown)),
            )
        ]
    factual = [c for c in judgment.claims if c.label != "NOT_FACTUAL"]
    judgeable = [c for c in factual if c.label != "UNJUDGEABLE"]
    supported = sum(c.label == "SUPPORTED" for c in judgeable)
    material_defects = [
        c for c in factual if c.material and c.label in {"UNSUPPORTED", "CONTRADICTED"}
    ]
    status = (
        "FAIL"
        if material_defects
        else "UNJUDGEABLE"
        if (not judgment.coverage_complete or any(c.label == "UNJUDGEABLE" for c in factual))
        else "PASS"
        if factual
        else "NOT_APPLICABLE"
    )
    return [
        Score(
            name="claim_support",
            status=status,
            value=supported / len(judgeable) if judgeable else None,
            numerator=supported,
            denominator=len(judgeable),
            finding="; ".join(f"{c.label}: {c.span}" for c in material_defects)
            or "No material unsupported or contradicted claim found.",
        ),
        Score(
            name="claim_judgment_coverage",
            status="PASS" if judgment.coverage_complete else "UNJUDGEABLE",
            value=len(judgeable) / len(factual) if factual else None,
            numerator=len(judgeable),
            denominator=len(factual),
            finding=f"{len(judgeable)} of {len(factual)} factual claims judged; nonfactual claims excluded.",
        ),
    ]


def deterministic_turn(turn: TurnRecord, reference: TurnReference) -> list[Score]:
    scores = [
        verdict(
            "acceptable_outcome",
            turn.status == "approved" and turn.outcome in reference.allowed_outcomes,
            f"Actual {turn.status}/{turn.outcome}; allowed {reference.allowed_outcomes}",
        )
    ]
    text = turn.markdown or ""
    table_count = len(re.findall(r"(?m)^\s*\|?\s*:?-{3,}:?\s*\|(?:\s*:?-{3,}:?\s*\|?)+\s*$", text))
    for criterion in reference.criteria:
        options = criterion.options
        if criterion.kind == "format":
            checks = []
            if "tables" in options:
                checks.append(table_count == options["tables"])
            if "max_words" in options:
                checks.append(len(text.split()) <= options["max_words"])
            if "min_tables" in options:
                checks.append(table_count >= options["min_tables"])
            if checks:
                scores.append(
                    verdict(
                        "format",
                        all(checks),
                        f"tables={table_count}, words={len(text.split())}",
                        criterion_id=criterion.id,
                        blocks_success=criterion.blocks_success,
                    )
                )
            else:
                scores.append(
                    Score(
                        name="format",
                        status="ERROR",
                        finding="Unsupported format criterion",
                        criterion_id=criterion.id,
                    )
                )
        elif criterion.kind == "state":
            checks = []
            if "report_count" in options:
                checks.append(len(turn.reports_after) == options["report_count"])
            if options.get("unchanged"):
                checks.append(turn.reports_before == turn.reports_after)
            if options.get("exact_previous"):
                history = turn.context.get("prior_approved_conversation", [])
                previous = history[-1] if history else {}
                # New runs expose only answer handles in the initial model request.
                # The reviewer capture contains the actual historical text, if available.
                if previous and "markdown" not in previous:
                    captured = next(
                        (
                            candidate.get("conversation", [])
                            for candidate in reversed(turn.candidates)
                            if candidate.get("conversation")
                        ),
                        [],
                    )
                    previous = next(
                        (
                            item
                            for item in captured
                            if item.get("answer_id") == previous.get("answer_id")
                        ),
                        {},
                    )
                created = [r for r in turn.reports_after if r not in turn.reports_before]
                if previous.get("excerpt_only"):
                    scores.append(
                        Score(
                            name="saved_previous_content",
                            status="UNJUDGEABLE",
                            finding="Previous answer was captured as an excerpt",
                        )
                    )
                else:
                    checks.append(
                        bool(created)
                        and all(r["markdown"] == previous.get("markdown") for r in created)
                    )
            if "title" in options:
                checks.append(any(r["title"] == options["title"] for r in turn.reports_after))
            scores.append(
                verdict(
                    "report_state",
                    all(checks),
                    criterion.description,
                    criterion_id=criterion.id,
                    blocks_success=criterion.blocks_success,
                )
                if checks
                else Score(
                    name="report_state",
                    status="ERROR",
                    finding="Unsupported state criterion",
                    criterion_id=criterion.id,
                )
            )
    return scores


def judged_scores(
    turn: TurnRecord, reference: TurnReference, judgment: Judgment, prior: list[dict]
) -> list[Score]:
    scores = numeric_scores(reference, judgment) + grounding_scores(turn, judgment, prior)
    definitions = {c.id: c for c in reference.criteria}
    for finding in judgment.criteria:
        scores.append(
            verdict(
                "semantic",
                finding.passed,
                finding.finding,
                criterion_id=finding.id,
                blocks_success=definitions[finding.id].blocks_success,
            )
        )
    actual = {
        "substantive": "answer",
        "clarification": "clarification",
        "refusal": "refusal",
        "partial": "partial",
    }[judgment.response_kind]
    scores.append(
        verdict(
            "response_kind",
            actual in reference.allowed_outcomes,
            f"Independent classification: {actual}",
        )
    )
    return scores


def final_state_scores(case: Case, trial: Trial) -> list[Score]:
    scores = [
        verdict(
            "final_report_count",
            len(trial.reports_final) == case.expected_report_count,
            f"Expected {case.expected_report_count}, actual {len(trial.reports_final)} reports",
        )
    ]
    if case.expected_final_reports is not None:
        expected = Counter((r.owner, r.title, r.markdown) for r in case.expected_final_reports)
        actual = Counter((r["owner"], r["title"], r["markdown"]) for r in trial.reports_final)
        scores.append(
            verdict(
                "exact_final_report_state",
                expected == actual,
                "Final owner/title/content multiset matches the independent specification",
            )
        )
    initial = trial.turns[0].reports_before if trial.turns else []
    others = [r for r in initial if r["owner"] != case.identity]
    after = [r for r in trial.reports_final if r["owner"] != case.identity]
    scores.append(
        verdict("other_owner_state", others == after, "Other owners' reports must remain unchanged")
    )
    for turn in trial.turns:
        for report in turn.reports_after:
            if report not in turn.reports_before:
                approved_texts = [t.markdown for t in trial.turns if t.status == "approved"]
                scores.append(
                    verdict(
                        "saved_reviewed_content",
                        report["markdown"] in approved_texts,
                        "Persisted content matches a published reviewed answer",
                    )
                )
    return scores
