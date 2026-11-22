"""Diagnostic assessment of observed agent actions, independent of reference answers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from evaluation.results import Record, Score, Trial
from retail_agent.observability import sanitize_capture

PROMPT_PATH = Path(__file__).parents[1] / "prompts/trajectory.md"
CRITERIA = (
    "tool_selection",
    "tool_arguments",
    "evidence_use",
    "error_recovery",
    "progress",
)
POLICY = "visible-ordered-events-v1"


class TrajectoryFinding(Record):
    criterion: Literal[
        "tool_selection", "tool_arguments", "evidence_use", "error_recovery", "progress"
    ]
    status: Literal["PASS", "FAIL", "UNJUDGEABLE", "NOT_APPLICABLE"]
    explanation: str = Field(min_length=1, max_length=2000)
    event_ids: list[str]


class TrajectoryJudgment(Record):
    findings: list[TrajectoryFinding]
    assessed_event_ids: list[str]
    coverage_complete: bool
    summary: str = Field(min_length=1, max_length=3000)


def version() -> dict:
    return {
        "policy": POLICY,
        "prompt_sha256": hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest(),
        "schema_sha256": hashlib.sha256(
            json.dumps(TrajectoryJudgment.model_json_schema(), sort_keys=True).encode()
        ).hexdigest(),
        "diagnostic_only": True,
        "human_calibrated": False,
    }


def capture_problem(trial: Trial) -> str | None:
    if trial.status == "NOT_EXECUTED":
        return "The trajectory was not executed"
    if trial.error:
        return "Execution did not produce a complete trajectory"
    applicable = [turn for turn in trial.turns if turn.status != "NOT_APPLICABLE"]
    if not applicable:
        return "No applicable execution steps were captured"
    for turn in applicable:
        if turn.status in {"NOT_EXECUTED", "ERROR", "deadline"}:
            return f"Incomplete trajectory capture for step {turn.step_id}"
        if turn.kind != "ask":
            continue
        names = [event.get("event") for event in turn.timeline]
        if not names or names[0] != "initial_context" or names[-1] != "turn_result":
            return f"Missing ordered context or completion event for step {turn.step_id}"
        definitions = [
            event.get("available_tools")
            for event in turn.timeline
            if event.get("event") == "available_tools"
        ]
        if not any(isinstance(tools, list) and tools for tools in definitions):
            return f"Available tool definitions were not captured for step {turn.step_id}"
        if turn.observations and "tool_call" not in names:
            return f"Tool arguments were not captured for step {turn.step_id}"
    return None


def event_catalog(trial: Trial) -> dict[str, dict]:
    """Assign bounded stable references without exposing the full hidden evidence bundle."""
    catalog = {}
    for turn in trial.turns:
        if turn.status == "NOT_APPLICABLE":
            continue
        if turn.kind != "ask":
            catalog[f"{turn.step_id}:action"] = {
                "step_id": turn.step_id,
                "event": "trusted_action",
                "kind": turn.kind,
                "status": turn.status,
                "receipts": turn.receipts,
            }
            continue
        for index, source in enumerate(turn.timeline, 1):
            event = dict(source)
            if event.get("event") == "answer_candidate":
                # Reviewers receive stored rows that may never have been shown to the analyst.
                event.pop("evidence", None)
            if event.get("event") == "turn_result":
                result = event.get("result", {})
                event = {
                    "event": "turn_result",
                    "status": result.get("status", turn.status),
                    "answer": {
                        "markdown": turn.markdown,
                        "outcome": turn.outcome,
                        "evidence_ids": turn.evidence_ids,
                    },
                    "capture_errors": event.get("capture_errors", 0),
                }
            for key in ("conversation_id", "turn_id", "trace_id", "span_id", "event_id"):
                event.pop(key, None)
            catalog[f"{turn.step_id}:e{index}"] = {"step_id": turn.step_id, **event}
    return sanitize_capture(catalog)


def trajectory_input(trial: Trial) -> dict:
    return {
        "policy": POLICY,
        "criteria": list(CRITERIA),
        "untrusted_execution": {
            "steps": [
                {
                    "step_id": turn.step_id,
                    "kind": turn.kind,
                    "question": turn.prompt,
                    "status": turn.status,
                }
                for turn in trial.turns
            ],
            "events": event_catalog(trial),
        },
    }


def response_schema(trial: Trial) -> dict:
    schema = TrajectoryJudgment.model_json_schema()
    ids = list(event_catalog(trial))
    schema["$defs"]["TrajectoryFinding"]["properties"]["event_ids"]["items"]["enum"] = ids
    schema["properties"]["assessed_event_ids"]["items"]["enum"] = ids
    return schema


def validate_judgment(judgment: TrajectoryJudgment, trial: Trial) -> None:
    findings = [finding.criterion for finding in judgment.findings]
    if len(findings) != len(CRITERIA) or set(findings) != set(CRITERIA):
        raise ValueError("Trajectory judgment has missing or repeated criteria")
    catalog = event_catalog(trial)
    assessed = judgment.assessed_event_ids
    if len(assessed) != len(set(assessed)) or not set(assessed) <= catalog.keys():
        raise ValueError("Trajectory judgment has repeated or unobserved event IDs")
    decisions = {
        key
        for key, event in catalog.items()
        if event["event"] in {"tool_call", "tool_observation", "answer_candidate", "trusted_action"}
    }
    if judgment.coverage_complete and not decisions <= set(assessed):
        raise ValueError("Trajectory judge claimed complete coverage without all decision events")
    for finding in judgment.findings:
        if len(finding.event_ids) != len(set(finding.event_ids)):
            raise ValueError("Trajectory finding repeats event IDs")
        if not set(finding.event_ids) <= catalog.keys():
            raise ValueError("Trajectory finding cites an unobserved event")
        if finding.status in {"PASS", "FAIL"} and not finding.event_ids:
            raise ValueError("Trajectory finding has no observed event attribution")
        if not set(finding.event_ids) <= set(assessed):
            raise ValueError("Trajectory finding cites an event that was not assessed")


def scores(judgment: TrajectoryJudgment) -> list[Score]:
    result = [
        Score(
            name=f"trajectory/{finding.criterion}",
            status=finding.status,
            value=float(finding.status == "PASS") if finding.status in {"PASS", "FAIL"} else None,
            finding=finding.explanation,
            blocks_success=False,
            version=POLICY,
        )
        for finding in judgment.findings
    ]
    result.append(
        Score(
            name="trajectory/coverage",
            status="PASS" if judgment.coverage_complete else "UNJUDGEABLE",
            value=float(judgment.coverage_complete),
            finding="Decision-event coverage reported by the judge; not human-measured recall.",
            blocks_success=False,
            version=POLICY,
        )
    )
    return result


def unavailable_score(reason: str, *, error=False) -> Score:
    return Score(
        name="trajectory/assessment",
        status="ERROR" if error else "UNJUDGEABLE",
        finding=reason,
        blocks_success=False,
        version=POLICY,
    )
