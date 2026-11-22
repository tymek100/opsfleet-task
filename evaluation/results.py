"""Versioned execution and grading artifacts, independent of runtime state."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ScoreStatus = Literal["PASS", "FAIL", "ERROR", "UNJUDGEABLE", "NOT_APPLICABLE"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnRecord(Record):
    step_id: str
    kind: str = "ask"
    prompt: str = ""
    status: str
    markdown: str | None = None
    outcome: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    elapsed_seconds: float = 0
    reports_before: list[dict[str, Any]] = Field(default_factory=list)
    reports_after: list[dict[str, Any]] = Field(default_factory=list)
    receipts: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class Trial(Record):
    schema_version: str = "1"
    id: str
    case_id: str
    repetition: int
    started_at: str = ""
    ended_at: str = ""
    trace_id: str | None = None
    status: str
    turns: list[TurnRecord] = Field(default_factory=list)
    elapsed_seconds: float = 0
    accounted_usd: float = 0
    reports_final: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class Score(Record):
    name: str
    status: ScoreStatus
    value: float | None = None
    numerator: int | None = None
    denominator: int | None = None
    finding: str
    criterion_id: str | None = None
    blocks_success: bool = True
    version: str = "1"


class ExtractedFact(Record):
    id: str
    span: str
    value: str | None


class Claim(Record):
    span: str
    label: Literal["SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "NOT_FACTUAL", "UNJUDGEABLE"]
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str
    material: bool = True


class CriterionFinding(Record):
    id: str
    passed: bool
    finding: str
    spans: list[str] = Field(default_factory=list)


class Judgment(Record):
    facts: list[ExtractedFact]
    claims: list[Claim]
    criteria: list[CriterionFinding]
    response_kind: Literal["substantive", "clarification", "refusal", "partial"]
    coverage_complete: bool


class TurnGrade(Record):
    step_id: str
    status: ScoreStatus
    scores: list[Score]
    judgment: Judgment | None = None
    candidate_grades: list[dict[str, Any]] = Field(default_factory=list)


class TrialGrade(Record):
    trial_id: str
    case_id: str
    repetition: int
    status: ScoreStatus
    turns: list[TurnGrade]
    scores: list[Score] = Field(default_factory=list)


class RunManifest(Record):
    schema_version: str = "1"
    id: str
    created_at: str
    suite: str
    case_ids: list[str]
    repetitions: int
    dataset_sha256: str
    cases_sha256: dict[str, str]
    fixture_hashes: dict[str, str]
    trials_sha256: dict[str, str] = Field(default_factory=dict)
    git_commit: str
    git_diff_sha256: str
    lockfile_sha256: str
    runtime_hashes: dict[str, str]
    harness_hashes: dict[str, str] = Field(default_factory=dict)
    model: str
    settings: dict[str, Any]
    max_cost_usd: float
    deadline_seconds: float
    primary_metrics: list[str] = Field(
        default_factory=lambda: [
            "task_success_over_planned",
            "factual_claim_precision",
            "numeric_fact_accuracy",
        ]
    )
    experiment_purpose: str = "diagnostic"
    pricing_version: str = "configured-conservative-v1"
    capture_policy: str = "synthetic"
    human_reviewed: bool = False
    status: str = "running"
    completed_trials: int = 0
    planned_trials: int
    accounted_usd: float = 0
    publication: dict[str, Any] = Field(default_factory=dict)
