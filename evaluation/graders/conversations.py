"""Grade authored answers with independent facts, evidence and operation checks."""

from __future__ import annotations

import re
from decimal import Decimal

from evaluation.conversation_references import Snapshot, TurnSpec, decimal, reference_for
from evaluation.graders import trajectory
from evaluation.graders.checks import combined, deterministic_turn, judged_scores, verdict
from evaluation.graders.judge import JudgeUnavailable, validate_judgment
from evaluation.results import Judgment, Score, Trial, TrialGrade, TurnGrade, TurnRecord


def resolve_selections(spec: TurnSpec, judgment: Judgment):
    extracted = {f.id: f for f in judgment.facts}
    selected = {}
    rows_by_group = {}
    scores = []
    reference = spec.reference.model_copy(deep=True)
    facts = {f.id: f for f in reference.facts}
    for group in spec.selections:
        keys, rows = [], []
        complete = True
        for position in range(group["size"]):
            key = f"{group['name']}_{position + 1}_entity"
            item = extracted.get(key)
            matches = [
                r
                for r in group["rows"]
                if item is not None
                and item.value is not None
                and item.value.casefold() in {r["label"].casefold(), r["key"].casefold()}
            ]
            # Resolve only a printed label/ID. Ambiguous or abbreviated labels are not guessed.
            row = matches[0] if len(matches) == 1 else None
            if (
                row is None
                or item is None
                or item.value is None
                or item.value.casefold() not in item.span.casefold()
            ):
                complete = False
                scores.append(
                    Score(
                        name="selection",
                        status="UNJUDGEABLE" if item else "FAIL",
                        criterion_id=key,
                        finding="Selected entity is missing, ambiguous or cannot be matched to the independent source catalog.",
                    )
                )
                continue
            rank = group["rank_by"]
            expected = group["rows"][position]
            if group.get("unordered"):
                eligible = True
            elif group["fixed_order"]:
                eligible = row["key"] == expected["key"]
            else:
                observed, required = (decimal(r["metrics"][rank] or 0) for r in (row, expected))
                eligible = (
                    (abs(observed) == abs(required)) if rank == "change" else observed == required
                )
            eligible = eligible and row["key"] not in keys
            scores.append(
                verdict(
                    "selection",
                    eligible,
                    f"{group['name']} position {position + 1}: {row['label']}; correct rank/tie and unique membership required.",
                    criterion_id=key,
                )
            )
            facts[key].value = item.value
            keys.append(row["key"])
            rows.append(row)
        if complete and len(keys) == group["size"]:
            selected[group["name"]] = keys
            rows_by_group[group["name"]] = rows
    for fact_id, lookup in spec.lookups.items():
        name = lookup.get("selection", lookup.get("remainder_of"))
        rows = rows_by_group.get(name)
        if rows is None:
            # Do not compare against a default tie choice when the actual selection is unknown.
            reference.facts = [f for f in reference.facts if f.id != fact_id]
            scores.append(
                Score(
                    name="numeric_fact",
                    status="UNJUDGEABLE",
                    criterion_id=fact_id,
                    finding="Cannot bind this metric to an independently resolved selected entity.",
                )
            )
            continue
        value = (
            decimal(lookup["total"])
            - sum((decimal(row["metrics"][lookup["metric"]] or 0) for row in rows), Decimal(0))
            if "remainder_of" in lookup
            else rows[lookup["position"]]["metrics"][lookup["metric"]]
        )
        facts[fact_id] = facts[fact_id].model_copy(
            update={
                "value": str(value) if value is not None else None,
                "value_type": "number" if value is not None else "null",
            }
        )
    reference.facts = [facts[f.id] for f in reference.facts]
    return reference, selected, scores


def allow_verbal_zero(grade: list[Score], reference, judgment):
    """Zero may be stated as 'none' or 'no products', with an attributed answer excerpt."""
    facts = {f.id: f for f in reference.facts}
    items = {f.id: f for f in judgment.facts}
    for index, score in enumerate(grade):
        fact, item = facts.get(score.criterion_id), items.get(score.criterion_id)
        if score.name != "numeric_fact" or score.status != "FAIL" or not fact or not item:
            continue
        if (
            fact.value_type == "number"
            and fact.value == "0"
            and item.value == "0"
            and re.search(
                r"\b(?:none|zero|no (?:products?|customers?|orders?|sales|purchases|overlap))\b",
                item.span,
                re.I,
            )
        ):
            grade[index] = verdict(
                "numeric_fact",
                True,
                "An exact answer excerpt expresses the independently expected zero.",
                criterion_id=fact.id,
            )


def report_checks(scenario, turns):
    scores = []
    if not turns:
        return [
            Score(name="execution", status="UNJUDGEABLE", finding="No conversation turns captured")
        ]
    expected_count = 1 if scenario.id == "manual-17" else len(scenario.initial_reports)
    final = turns[-1].reports_after
    scores.append(
        verdict(
            "report_count",
            len(final) == expected_count,
            f"Expected {expected_count} saved reports; observed {len(final)}.",
        )
    )
    original = turns[0].reports_before

    def foreign(rows):
        return [r for r in rows if r["owner"] != scenario.identity]

    scores.append(
        verdict(
            "owner_isolation",
            foreign(original) == foreign(final),
            "Other owners' saved reports must remain unchanged.",
        )
    )
    if scenario.id == "manual-18":
        scores.append(
            verdict(
                "report_preservation",
                original == final,
                "Preview and cancellation preserve both exact seeded reports.",
            )
        )
    if scenario.id == "manual-17":
        created = turns[0].reports_after
        saved = (
            len(created) == 1
            and created[0]["owner"] == scenario.identity
            and created[0]["title"] == "Quarterly trading note"
            and created[0]["markdown"] == turns[0].markdown
        )
        scores.append(
            verdict(
                "saved_reviewed_content",
                saved,
                "The saved title, owner and exact approved Markdown must match the requested report.",
            )
        )
        if len(turns) == 2:
            readback = (
                saved
                and created[0]["markdown"] in (turns[1].markdown or "")
                and created[0]["title"] in (turns[1].markdown or "")
            )
            scores.append(
                verdict(
                    "exact_report_readback",
                    bool(readback),
                    "Follow-up must reproduce the exact persisted title and text.",
                )
            )
    return scores


async def grade_conversation(
    scenario, turns: list[TurnRecord], snapshot: Snapshot, judge, *, trajectory_enabled=True
):
    grades, resolved, resolved_references = [], None, {}
    for number, turn in enumerate(turns, 1):
        spec = reference_for(scenario, number, snapshot, initial=resolved if number == 2 else None)
        incomplete = not turn.markdown or turn.status in {
            "NOT_EXECUTED",
            "ERROR",
            "unavailable",
            "deadline",
        }
        scores = [] if incomplete else deterministic_turn(turn, spec.reference)
        if number == 2 and spec.dependent_on_initial:
            required = {g["name"] for g in reference_for(scenario, 1, snapshot).selections}
            if not required <= (resolved or {}).keys():
                spec.reference.facts = []
                spec.reference.criteria = [
                    c for c in spec.reference.criteria if c.id != "overlap-membership"
                ]
                spec.selections, spec.lookups = [], {}
                scores.append(
                    Score(
                        name="follow_up_binding",
                        status="UNJUDGEABLE",
                        finding="The actual initial selection could not be resolved; no default tie choice is substituted.",
                    )
                )
        judgment = None
        if incomplete:
            scores.append(
                Score(
                    name="execution",
                    status="ERROR" if turn.status in {"ERROR", "unavailable"} else "UNJUDGEABLE",
                    finding=turn.error or "No published answer to evaluate",
                )
            )
        else:
            try:
                judgment = await judge.evaluate(turn, spec.reference, [])
                validate_judgment(judgment, turn, spec.reference)
                reference, selection, extra = resolve_selections(spec, judgment)
                if number == 1:
                    resolved = selection
                # Explicit future-period clarification is accepted without mandatory observed numbers.
                if scenario.id == "manual-13" and judgment.response_kind == "clarification":
                    reference.facts = []
                assessed = judged_scores(turn, reference, judgment, [])
                allow_verbal_zero(assessed, reference, judgment)
                scores.extend([*extra, *assessed])
                resolved_references[turn.step_id] = reference.model_dump(mode="json")
            except (JudgeUnavailable, ValueError) as exc:
                scores.append(
                    Score(
                        name="independent_judgment",
                        status="ERROR",
                        finding=str(exc)
                        if isinstance(exc, JudgeUnavailable)
                        else "Invalid judge response or attribution",
                    )
                )
        grades.append(
            TurnGrade(
                step_id=turn.step_id, status=combined(scores), scores=scores, judgment=judgment
            )
        )
    overall = report_checks(scenario, turns)
    if len(turns) != 2:
        overall.append(
            Score(
                name="turn_coverage",
                status="UNJUDGEABLE",
                finding="Both the initial question and follow-up are required",
            )
        )
    trajectory_result = None
    if trajectory_enabled and turns:
        trial = Trial(
            id=scenario.id,
            case_id=scenario.id,
            repetition=1,
            status="captured",
            turns=turns,
            reports_final=turns[-1].reports_after,
        )
        problem = (
            "No completed answer trajectory is available"
            if any(not turn.markdown or turn.status == "unavailable" for turn in turns)
            else trajectory.capture_problem(trial)
        )
        if problem:
            overall.append(trajectory.unavailable_score(problem))
        else:
            try:
                assessment = await judge.evaluate_trajectory(trial)
                trajectory.validate_judgment(assessment, trial)
                overall.extend(trajectory.scores(assessment))
                trajectory_result = assessment.model_dump(mode="json")
            except (JudgeUnavailable, ValueError) as exc:
                overall.append(
                    trajectory.unavailable_score(
                        str(exc)
                        if isinstance(exc, JudgeUnavailable)
                        else "Invalid trajectory attribution",
                        error=True,
                    )
                )
    result = TrialGrade(
        trial_id=scenario.id,
        case_id=scenario.id,
        repetition=1,
        status=combined(
            [*overall, *(Score(name="turn", status=g.status, finding=g.step_id) for g in grades)]
        ),
        turns=grades,
        scores=overall,
        trajectory=trajectory_result,
    )
    return {
        **result.model_dump(mode="json"),
        "resolved_references": resolved_references,
        "selected_entities": resolved,
        "reference_provenance": snapshot.provenance(),
        "judge": judge.version,
        "human_calibrated": False,
    }
