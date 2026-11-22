"""Regrade saved outputs without importing or invoking the agent runner."""

import hashlib
import json
from pathlib import Path

from evaluation.graders.checks import (
    combined,
    deterministic_turn,
    final_state_scores,
    judged_scores,
)
from evaluation.graders.judge import PROMPT_PATH, JudgeUnavailable, validate_judgment
from evaluation.models import Case
from evaluation.results import Score, Trial, TrialGrade, TurnGrade, TurnRecord
from evaluation.runners.artifacts import digest, frozen_cases, identifier, read_json, write_json


async def grade_turn(
    turn: TurnRecord, reference, judge, prior: list[dict], *, candidate=False
) -> TurnGrade:
    if turn.status == "NOT_APPLICABLE":
        return TurnGrade(step_id=turn.step_id, status="NOT_APPLICABLE", scores=[])
    if turn.kind != "ask":
        receipt = turn.receipts[0] if len(turn.receipts) == 1 else {}
        successful = (
            turn.status == "completed"
            and receipt.get("status") == "ok"
            and (
                bool(receipt.get("deleted_ids"))
                if turn.kind == "confirm_delete"
                else receipt.get("cancelled") is True
                if turn.kind == "cancel_delete"
                else False
            )
        )
        score = Score(
            name="trusted_action",
            status="PASS" if successful else "FAIL",
            value=float(successful),
            finding=turn.error or f"{turn.kind}: {receipt.get('status', 'missing receipt')}",
        )
        return TurnGrade(step_id=turn.step_id, status=score.status, scores=[score])
    deterministic = deterministic_turn(turn, reference)
    scores = (
        [score for score in deterministic if score.name == "format"] if candidate else deterministic
    )
    judgment = None
    if turn.markdown:
        if judge is None:
            scores.append(
                Score(
                    name="independent_judgment",
                    status="UNJUDGEABLE",
                    finding="Code-only mode cannot extract bound facts or assess claim support",
                )
            )
        else:
            try:
                judgment = await judge.evaluate(turn, reference, prior)
                validate_judgment(judgment, turn, reference)
                scores.extend(judged_scores(turn, reference, judgment, prior))
            except (JudgeUnavailable, ValueError) as exc:
                scores.append(
                    Score(
                        name="independent_judgment",
                        status="ERROR",
                        finding=str(exc)
                        if isinstance(exc, JudgeUnavailable)
                        else "Invalid judge schema or attribution",
                    )
                )
    elif turn.status == "NOT_EXECUTED":
        scores = [Score(name="execution", status="UNJUDGEABLE", finding="Task was not executed")]
    elif not scores:
        scores = [Score(name="execution", status="FAIL", finding="No answer available")]
    return TurnGrade(
        step_id=turn.step_id, status=combined(scores), scores=scores, judgment=judgment
    )


async def grade_trial(case: Case, trial: Trial, judge, *, grade_candidates=True) -> TrialGrade:
    if trial.status == "NOT_EXECUTED":
        return TrialGrade(
            trial_id=trial.id,
            case_id=case.id,
            repetition=trial.repetition,
            status="UNJUDGEABLE",
            turns=[],
            scores=[
                Score(
                    name="execution", status="UNJUDGEABLE", finding="Run limits prevented execution"
                )
            ],
        )
    if [turn.step_id for turn in trial.turns] != [step.id for step in case.steps]:
        return TrialGrade(
            trial_id=trial.id,
            case_id=case.id,
            repetition=trial.repetition,
            status="ERROR",
            turns=[],
            scores=[
                Score(
                    name="turn_coverage",
                    status="ERROR",
                    finding="Missing, duplicate, reordered, or unexpected steps",
                )
            ],
        )
    grades = []
    prior: list[dict] = []
    for turn in trial.turns:
        reference = case.references.get(turn.step_id)
        grade = await grade_turn(turn, reference, judge, prior)
        if grade_candidates and reference is not None:
            for index, item in enumerate(turn.candidates):
                candidate = item.get("candidate", {})
                draft = turn.model_copy(
                    update={
                        "markdown": candidate.get("markdown"),
                        "outcome": candidate.get("outcome"),
                        "evidence_ids": candidate.get("evidence_ids", []),
                        "observations": item.get("visible_observations", []),
                        "context": {
                            **turn.context,
                            "prior_approved_conversation": item.get("conversation", []),
                        },
                    }
                )
                evaluated = await grade_turn(draft, reference, judge, prior, candidate=True)
                grade.candidate_grades.append(
                    {
                        "index": index,
                        "status": evaluated.status,
                        "review_decision": item.get("review", {}).get("decision"),
                        "scores": [s.model_dump(mode="json") for s in evaluated.scores],
                        "judgment": evaluated.judgment.model_dump(mode="json")
                        if evaluated.judgment
                        else None,
                        "published": candidate.get("markdown") == turn.markdown,
                    }
                )
        grades.append(grade)
        prior.extend(turn.observations)
    scores = final_state_scores(case, trial)
    if trial.error:
        scores.append(Score(name="harness", status="ERROR", finding=trial.error))
    every_turn = [Score(name="turn", status=g.status, finding=g.step_id) for g in grades]
    return TrialGrade(
        trial_id=trial.id,
        case_id=case.id,
        repetition=trial.repetition,
        status=combined([*scores, *every_turn]),
        turns=grades,
        scores=scores,
    )


async def grade_run(directory: Path, judge=None, *, grade_candidates=True, progress=print) -> Path:
    cases = {c.id: c for c in frozen_cases(directory)}
    grade_dir = directory / "grades" / identifier("grade")
    grade_dir.mkdir(parents=True, exist_ok=False)
    paths = sorted((directory / "trials").glob("*.json"))
    execution = read_json(directory / "manifest.json")
    expected_hashes = execution.get("trials_sha256", {})
    actual_hashes = {path.name: digest(path) for path in paths}
    if actual_hashes != expected_hashes:
        raise ValueError("Execution artifacts are missing or were modified after capture")
    code_root = Path(__file__).parents[1]
    code_paths = [
        *Path(__file__).parent.glob("*.py"),
        *code_root.glob("reporting/*.py"),
        code_root / "models.py",
        code_root / "results.py",
    ]
    code_hashes = {str(path.relative_to(code_root)): digest(path) for path in sorted(code_paths)}
    manifest = {
        "id": grade_dir.name,
        "run_id": directory.name,
        "status": "running",
        "judge": judge.version if judge else {"mode": "code-only"},
        "prompt_sha256": digest(PROMPT_PATH),
        "trials_sha256": actual_hashes,
        "dataset_sha256": execution["dataset_sha256"],
        "grade_candidates": grade_candidates,
        "human_calibrated": False,
        "grader_code_sha256": hashlib.sha256(
            json.dumps(code_hashes, sort_keys=True).encode()
        ).hexdigest(),
        "artifact_schema_version": "1",
        "report_schema_version": "2",
    }
    write_json(grade_dir / "manifest.json", manifest)
    for path in paths:
        trial = Trial.model_validate(read_json(path))
        grade = await grade_trial(
            cases[trial.case_id], trial, judge, grade_candidates=grade_candidates
        )
        write_json(grade_dir / "trials" / path.name, grade)
        if judge:
            write_json(grade_dir / "judge_calls.json", judge.calls)
        progress(f"{trial.id}: {grade.status}")
    manifest.update(status="completed", accounted_judge_usd=judge.accounted_usd if judge else 0)
    write_json(grade_dir / "manifest.json", manifest)
    from evaluation.reporting.summary import write_summary

    write_summary(directory, grade_dir)
    return grade_dir
