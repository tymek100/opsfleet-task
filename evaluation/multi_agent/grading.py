"""Reuse the independent answer judge, with namespaced A2A evidence attribution."""

from evaluation.graders.checks import combined, verdict
from evaluation.graders.judge import JudgeUnavailable, validate_judgment
from evaluation.results import Score, TurnRecord

from .observation_sources import bind_observations
from .partitions import extraction_reference, numeric_partition_scores
from .reference_context import bounded_reference


def evidence_ids(value):
    if isinstance(value, list):
        return set().union(*(evidence_ids(v) for v in value)) if value else set()
    if not isinstance(value, dict):
        return set()
    found = {
        str(value[k])
        for k in ("id", "evidence_id", "observation_source_id")
        if isinstance(value.get(k), str)
    }
    found.update(v for v in value.get("evidence_ids", []) if isinstance(v, str))
    for key, child in value.items():
        if key != "rows":
            found.update(evidence_ids(child))
    return found


def turn_record(raw, question, number, prior):
    evidence = raw.get("evidence", [])
    if isinstance(evidence, dict):
        evidence = [{"id": k, **v} for k, v in evidence.items()]
    # Answer quality and process quality have different evaluation targets.
    # Drafts, finish arguments and reviewer verdicts can contain superseded
    # assertions. Only the published markdown is the answer being graded.
    observations = [
        event
        for event in raw.get("observations", [])
        if event.get("event") in {"initial_context", "evidence"}
        or (
            event.get("event") == "tool_observation"
            and event.get("name", event.get("tool")) != "finish_answer"
        )
    ]
    # Selected evidence may originate in a prior authorized turn and need not
    # have a new tool event in this turn. Preserve its full returned payload.
    observations.extend({"event": "evidence", "result": item} for item in evidence)
    observations = bind_observations(observations)
    context = {"prior_authorized_answers": prior, "as_of": raw.get("as_of")}
    context["evaluation_source_ids"] = sorted(evidence_ids([context, observations]))
    return TurnRecord(
        step_id=f"turn-{number}",
        prompt=question,
        status=raw.get("status", "ERROR"),
        markdown=raw.get("markdown"),
        outcome=raw.get("outcome", "answer"),
        evidence=evidence,
        observations=observations,
        context=context,
        trace=raw.get("trace", []),
        trace_id=raw.get("trace_id"),
        usage=raw.get("usage", {}),
        elapsed_seconds=raw.get("elapsed_seconds", 0),
        error=raw.get("error"),
    )


async def grade(raw, question, number, ref, judge, prior):
    turn = turn_record(raw, question, number, prior)
    scores = []
    judgment = None
    if not turn.markdown or turn.status in {
        "ERROR",
        "error",
        "failed",
        "unavailable",
        "deadline",
        "NOT_EXECUTED",
    }:
        scores.append(
            Score(
                name="execution",
                status="ERROR",
                finding=turn.error or "No completed answer was available.",
            )
        )
    else:
        scores.append(
            verdict(
                "reviewed_completion",
                turn.status in {"approved", "completed"},
                f"Runtime status: {turn.status}; approval is only a publication contract, not a correctness score.",
            )
        )
        try:
            extraction = bounded_reference(extraction_reference(ref), turn.markdown, prior)
            judgment = await judge.evaluate(turn, extraction, [])
            validate_judgment(judgment, turn, extraction)
            scores.extend(numeric_partition_scores(ref, judgment))
            mapped = {
                "substantive": "answer",
                "partial": "partial",
                "refusal": "refusal",
                "clarification": "clarification",
            }[judgment.response_kind]
            scores.append(
                verdict(
                    "acceptable_outcome",
                    mapped in ref.allowed_outcomes,
                    f"Observed response type {mapped}; expected one of {ref.allowed_outcomes}.",
                )
            )
            scores.extend(
                verdict("semantic", c.passed, c.finding, criterion_id=c.id)
                for c in judgment.criteria
            )
            observed = evidence_ids([turn.context, turn.observations])
            unknown = {
                eid for c in judgment.claims for eid in c.evidence_ids if eid not in observed
            }
            factual = [c for c in judgment.claims if c.label != "NOT_FACTUAL"]
            defects = [
                c for c in factual if c.material and c.label in {"UNSUPPORTED", "CONTRADICTED"}
            ]
            unresolved = [c for c in factual if c.label == "UNJUDGEABLE"]
            scores.append(
                Score(
                    name="claim_support",
                    status="ERROR"
                    if unknown
                    else "FAIL"
                    if defects
                    else "UNJUDGEABLE"
                    if unresolved or not judgment.coverage_complete
                    else "PASS",
                    finding=("Unknown evidence IDs: " + ", ".join(sorted(unknown)))
                    if unknown
                    else "; ".join(c.reason for c in defects + unresolved)
                    or "No unsupported material claims found; judge calibration remains pending.",
                    numerator=sum(c.label == "SUPPORTED" for c in factual),
                    denominator=len(factual),
                )
            )
        except (JudgeUnavailable, ValueError) as exc:
            scores.append(
                Score(
                    name="independent_judgment",
                    status="ERROR",
                    finding=str(exc)
                    if isinstance(exc, JudgeUnavailable)
                    else "Invalid judgment or source attribution; no pass assumed.",
                )
            )
    return {
        "step_id": turn.step_id,
        "status": combined(scores),
        "scores": [s.model_dump(mode="json") for s in scores],
        "judgment": judgment.model_dump(mode="json") if judgment else None,
    }
