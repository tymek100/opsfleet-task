"""Report failures and missing judgments explicitly, including every repetition."""

from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from evaluation.models import Case
from evaluation.results import Trial, TrialGrade
from evaluation.runners.artifacts import read_json, write_json


def fraction(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def distribution(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "median": None, "p95": None}
    ordered = sorted(values)
    # Nearest-rank p95 is descriptive; no distributional inference for small samples.
    import math

    return {
        "n": len(values),
        "median": median(values),
        "p95": ordered[max(0, math.ceil(0.95 * len(values)) - 1)],
    }


def summarize(
    manifest: dict,
    trials: list[Trial],
    grades: list[TrialGrade],
    judge_manifest: dict,
    cases: list[Case] | None = None,
) -> dict:
    by_id = {g.trial_id: g for g in grades}
    statuses = Counter(g.status for g in grades)
    expected = manifest["planned_trials"]
    passed = statuses["PASS"]
    attempted = [t for t in trials if t.status != "NOT_EXECUTED"]
    by_case = defaultdict(list)
    for grade in grades:
        by_case[grade.case_id].append(grade)
    complete_groups = [
        group
        for group in by_case.values()
        if len(group) == manifest["repetitions"]
        and not any(g.status in {"ERROR", "UNJUDGEABLE", "NOT_APPLICABLE"} for g in group)
    ]
    all_pass = sum(all(g.status == "PASS" for g in group) for group in complete_groups)
    any_pass = sum(any(g.status == "PASS" for g in group) for group in complete_groups)
    claims = [
        score
        for g in grades
        for t in g.turns
        for score in t.scores
        if score.name == "claim_support"
    ]
    numeric = [
        score
        for grade in grades
        for turn in grade.turns
        for score in turn.scores
        if score.name == "numeric_fact"
    ]
    required = {
        (case.id, step): len(reference.facts)
        for case in cases or []
        for step, reference in case.references.items()
    }
    expected_facts = sum(
        required.get((trial.case_id, turn.step_id), 0)
        for trial in trials
        for turn in trial.turns
        if turn.kind == "ask" and turn.status not in {"NOT_APPLICABLE", "NOT_EXECUTED"}
    )
    support = sum(s.numerator or 0 for s in claims)
    judgeable = sum(s.denominator or 0 for s in claims)
    claim_coverage = [
        s for g in grades for t in g.turns for s in t.scores if s.name == "claim_judgment_coverage"
    ]
    factual_answers = [
        t
        for g in grades
        for t in g.turns
        if t.judgment is not None
        and any(c.label not in {"NOT_FACTUAL", "UNJUDGEABLE"} for c in t.judgment.claims)
    ]
    affected = sum(
        any(
            c.label in {"UNSUPPORTED", "CONTRADICTED"}
            for c in (t.judgment.claims if t.judgment else [])
        )
        for t in factual_answers
    )
    materially_affected = sum(
        any(
            c.material and c.label in {"UNSUPPORTED", "CONTRADICTED"}
            for c in (t.judgment.claims if t.judgment else [])
        )
        for t in factual_answers
    )
    claim_turns = [
        t
        for g in grades
        for t in g.turns
        if any(s.name in {"claim_support", "independent_judgment"} for s in t.scores)
    ]
    resolved_claim_turns = [
        t
        for t in claim_turns
        if t.judgment is not None
        and t.judgment.coverage_complete
        and not any(
            s.name in {"claim_support", "claim_judgment_coverage"}
            and s.status in {"ERROR", "UNJUDGEABLE"}
            for s in t.scores
        )
    ]
    candidates = [c for g in grades for t in g.turns for c in t.candidate_grades]
    reviewed = [c for c in candidates if c.get("review_decision") in {"approve", "revise", "stop"}]
    invalid = [c for c in reviewed if c["status"] == "FAIL"]
    valid = [c for c in reviewed if c["status"] == "PASS"]
    false_accept = sum(c["review_decision"] == "approve" for c in invalid)
    false_reject = sum(c["review_decision"] in {"revise", "stop"} for c in valid)
    transitions = Counter()
    for g in grades:
        for turn in g.turns:
            ordered = turn.candidate_grades
            if len(ordered) > 1:
                transitions[f"{ordered[0]['status']}_to_{ordered[-1]['status']}"] += 1
    usage = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "calls": 0}
    )
    for t in trials:
        for turn in t.turns:
            for event in turn.trace:
                role = event.get("role", "unknown")
                if event["event"] == "model_call":
                    usage[role]["calls"] += 1
                if event["event"] == "model_usage":
                    for key in ("input_tokens", "output_tokens", "thinking_tokens"):
                        usage[role][key] += event.get(key, 0)
    return {
        "run_id": manifest["id"],
        "grade_id": judge_manifest["id"],
        "qualification": "Diagnostic pilot: references and judge controls are not human-approved.",
        "release_ready": False,
        "planned": expected,
        "attempted": len(attempted),
        "completed": manifest["completed_trials"],
        "graded": len(grades),
        "statuses": dict(statuses),
        "not_executed": sum(t.status == "NOT_EXECUTED" for t in trials),
        "unresolved_or_missing": expected - passed - statuses["FAIL"],
        "task_success_over_planned": fraction(passed, expected),
        "factual_claim_precision": fraction(support, judgeable),
        "numeric_fact_accuracy": fraction(sum(s.status == "PASS" for s in numeric), len(numeric)),
        "numeric_fact_grading_coverage": fraction(len(numeric), expected_facts),
        "factual_claim_judgment_coverage": fraction(
            sum(s.numerator or 0 for s in claim_coverage),
            sum(s.denominator or 0 for s in claim_coverage),
        ),
        "claim_extraction_recall": {
            "status": "NOT_MEASURED",
            "reason": "No human-annotated claim audit",
        },
        "answer_grounding_grade_coverage": fraction(len(resolved_claim_turns), len(claim_turns)),
        "affected_answer_rate": fraction(affected, len(factual_answers)),
        "materially_affected_answer_rate": fraction(materially_affected, len(factual_answers)),
        "answerability": answerability_metrics(trials, grades, cases),
        "claim_precision_macro": claim_macro(grades, cases),
        "all_repetitions_success": fraction(all_pass, len(complete_groups)),
        "any_repetition_success": fraction(any_pass, len(complete_groups)),
        "repetition_group_coverage": fraction(len(complete_groups), len(manifest["case_ids"])),
        "reviewer_false_accepts": fraction(false_accept, len(invalid)),
        "reviewer_false_rejects": fraction(false_reject, len(valid)),
        "reviewer_candidates_without_decision": len(candidates) - len(reviewed),
        "reviewer_candidates_with_unresolved_grade": sum(
            c["status"] not in {"PASS", "FAIL"} for c in reviewed
        ),
        "reviewer_transitions_observational": dict(transitions),
        "latency_all_attempts_seconds": distribution([t.elapsed_seconds for t in attempted]),
        "latency_success_seconds": distribution(
            [t.elapsed_seconds for t in trials if by_id.get(t.id) and by_id[t.id].status == "PASS"]
        ),
        "accounted_agent_usd": manifest["accounted_usd"],
        "accounted_judge_usd": judge_manifest.get("accounted_judge_usd", 0),
        "agent_cost_per_success": manifest["accounted_usd"] / passed if passed else None,
        "provider_usage_by_role": dict(usage),
    }


def answerability_metrics(
    trials: list[Trial], grades: list[TrialGrade], cases: list[Case] | None
) -> dict:
    if cases is None:
        return {"status": "NOT_MEASURED", "reason": "Frozen reference cases were not supplied"}
    references = {case.id: case.references for case in cases}
    by_id = {grade.trial_id: {turn.step_id: turn for turn in grade.turns} for grade in grades}
    attempted = []
    for trial in trials:
        for turn in trial.turns:
            if turn.kind != "ask" or turn.status in {"NOT_EXECUTED", "NOT_APPLICABLE"}:
                continue
            reference = references.get(trial.case_id, {}).get(turn.step_id)
            grade = by_id.get(trial.id, {}).get(turn.step_id)
            if reference is None:
                continue
            gradable = (
                grade is not None
                and grade.judgment is not None
                and not any(
                    score.blocks_success and score.status in {"ERROR", "UNJUDGEABLE"}
                    for score in grade.scores
                )
            )
            attempted.append((reference, grade, gradable))
    answerable = [
        (ref, grade, valid) for ref, grade, valid in attempted if ref.answerability == "answerable"
    ]
    gradable_answerable = [(ref, grade) for ref, grade, valid in answerable if valid]
    substantive = [
        (ref, grade)
        for ref, grade, valid in attempted
        if valid and grade.judgment.response_kind == "substantive"
    ]
    correct = sum(
        grade is not None
        and grade.status == "PASS"
        and grade.judgment is not None
        and grade.judgment.response_kind == "substantive"
        for _, grade, _ in answerable
    )
    unnecessary = sum(
        grade.judgment.response_kind in {"clarification", "refusal"}
        and grade.judgment.response_kind not in ref.allowed_outcomes
        for ref, grade in gradable_answerable
    )
    risky = sum(
        any(
            c.material and c.label in {"UNSUPPORTED", "CONTRADICTED"} for c in grade.judgment.claims
        )
        or any(s.name == "numeric_fact" and s.status == "FAIL" for s in grade.scores)
        for _, grade in substantive
    )
    limited = {}
    for category in ("clarification_required", "evidence_unavailable", "access_denied"):
        rows = [
            (ref, grade, valid) for ref, grade, valid in attempted if ref.answerability == category
        ]
        successful = sum(
            valid and grade.status == "PASS" and grade.judgment.response_kind != "substantive"
            for _, grade, valid in rows
        )
        limited[category] = fraction(successful, len(rows))
    return {
        "status": "MEASURED",
        "attempted_turns": len(attempted),
        "answer_level_grading_coverage": fraction(
            sum(valid for _, _, valid in attempted), len(attempted)
        ),
        "useful_answer_coverage": fraction(correct, len(answerable)),
        "unnecessary_abstention": fraction(unnecessary, len(gradable_answerable)),
        "material_error_among_substantive": fraction(risky, len(substantive)),
        "appropriate_limited_response": limited,
        "unresolved_turns": sum(not valid for _, _, valid in attempted),
    }


def claim_macro(grades: list[TrialGrade], cases: list[Case] | None) -> dict:
    families = {case.id: case.family for case in cases or []}
    grouped = {"case": defaultdict(lambda: [0, 0]), "family": defaultdict(lambda: [0, 0])}
    for grade in grades:
        for turn in grade.turns:
            for score in turn.scores:
                if score.name != "claim_support" or not score.denominator:
                    continue
                for kind, key in (("case", grade.case_id), ("family", families.get(grade.case_id))):
                    if key is not None:
                        grouped[kind][key][0] += score.numerator or 0
                        grouped[kind][key][1] += score.denominator
    result = {}
    for kind, entries in grouped.items():
        values = {key: fraction(*counts) for key, counts in entries.items()}
        result[kind] = {
            "groups": values,
            "groups_with_judgeable_claims": len(values),
            "mean": sum(item["value"] for item in values.values()) / len(values)
            if values
            else None,
        }
    return result


def write_summary(run: Path, grade: Path) -> dict:
    manifest = read_json(run / "manifest.json")
    trials = [Trial.model_validate(read_json(p)) for p in sorted((run / "trials").glob("*.json"))]
    grades = [
        TrialGrade.model_validate(read_json(p)) for p in sorted((grade / "trials").glob("*.json"))
    ]
    from evaluation.runners.artifacts import frozen_cases

    result = summarize(
        manifest, trials, grades, read_json(grade / "manifest.json"), frozen_cases(run)
    )
    write_json(grade / "summary.json", result)
    lines = [
        f"# Evaluation {manifest['id']}",
        "",
        result["qualification"],
        "",
        f"Planned: {result['planned']}; attempted: {result['attempted']}; completed: {result['completed']}; graded: {result['graded']}.",
        f"Statuses: {result['statuses']}. Unresolved or missing: {result['unresolved_or_missing']}.",
        "",
        f"Agent accounted cost: ${result['accounted_agent_usd']:.4f}; judge: ${result['accounted_judge_usd']:.4f}.",
        "Unknown provider usage retains its reservation. Missing judgments do not count as passes.",
        f"Factual claim precision: {result['factual_claim_precision']}; judgment coverage: {result['factual_claim_judgment_coverage']}.",
        f"Numerical accuracy: {result['numeric_fact_accuracy']}; grading coverage: {result['numeric_fact_grading_coverage']}.",
        f"Affected answers: {result['affected_answer_rate']}; material defects: {result['materially_affected_answer_rate']}.",
        f"Answerability and abstention: {result['answerability']}.",
        f"Reviewer rates exclude {result['reviewer_candidates_without_decision']} candidates without a decision and {result['reviewer_candidates_with_unresolved_grade']} reviewed candidates without a resolved independent grade.",
        "",
        "| Trial | Result | Blocking findings |",
        "|---|---|---|",
    ]
    for g in grades:
        failures = [
            s.finding
            for t in g.turns
            for s in t.scores
            if s.blocks_success and s.status in {"FAIL", "ERROR", "UNJUDGEABLE"}
        ]
        failures += [s.finding for s in g.scores if s.status in {"FAIL", "ERROR", "UNJUDGEABLE"}]
        detail = "; ".join(failures).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {g.trial_id} | {g.status} | {detail} |")
    lines += [
        "",
        "Numerical accuracy and evidence support are separate checks. Reviewer transitions are observational; they do not establish causality.",
        "Repeated-trial statistics require complete groups. Small-sample p95 is descriptive. This pilot does not establish production quality.",
        "",
    ]
    (grade / "summary.md").write_text("\n".join(lines))
    return result
