"""Versioned evaluation inputs and trusted references, separate from runtime knowledge."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Fact(Record):
    id: str
    value: str | None
    value_type: Literal["number", "text", "null"] = "number"
    source_key: str
    metric: str
    entity: str = "authorized brand"
    period: str = "Q1 2026"
    scope: str = "Calvin Klein"
    unit: str = "count"
    denominator: str | None = None
    tolerance: Decimal = Decimal("0")

    @model_validator(mode="after")
    def valid_value(self) -> Fact:
        if self.value_type == "number":
            try:
                valid = self.value is not None and Decimal(self.value).is_finite()
            except InvalidOperation:
                valid = False
            if not valid:
                raise ValueError("Numeric references require a finite decimal value")
        elif self.value_type == "text" and self.value is None:
            raise ValueError("Text references require a value")
        elif self.value_type == "null" and self.value is not None:
            raise ValueError("Null references cannot contain a value")
        if self.tolerance < 0 or not self.tolerance.is_finite():
            raise ValueError("Numeric tolerance must be finite and nonnegative")
        return self


class Criterion(Record):
    id: str
    kind: Literal["numeric", "semantic", "format", "state", "outcome"]
    description: str
    severity: Literal["minor", "material", "critical"] = "material"
    blocks_success: bool = True
    options: dict[str, Any] = Field(default_factory=dict)


class TurnReference(Record):
    facts: list[Fact] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)
    allowed_outcomes: list[Literal["answer", "clarification", "refusal", "partial"]] = Field(
        default_factory=lambda: ["answer"]
    )
    answerability: Literal[
        "answerable", "clarification_required", "evidence_unavailable", "access_denied"
    ] = "answerable"
    reference_answer: str
    reference_procedure: str = "Use authorized read-only tools to obtain the required aggregates."

    @model_validator(mode="after")
    def unique_ids(self) -> TurnReference:
        for values in ([f.id for f in self.facts], [c.id for c in self.criteria]):
            if len(values) != len(set(values)):
                raise ValueError("Reference IDs must be unique within a turn")
        if not self.allowed_outcomes or not self.reference_answer.strip():
            raise ValueError("Every turn requires an allowed outcome and reference control")
        return self


class Step(Record):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,95}$")
    kind: Literal["ask", "confirm_delete", "cancel_delete"] = "ask"
    message: str = ""
    when_previous_outcome: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ask_has_message(self) -> Step:
        if self.kind == "ask" and not self.message.strip():
            raise ValueError("An ask step needs a user message")
        return self


class ReportSeed(Record):
    owner: str
    title: str
    markdown: str


class Fault(Record):
    boundary: Literal["query", "provider", "report_save"]
    occurrence: int = Field(default=1, ge=1)
    code: str = "invalid_request"
    message: str = "Controlled evaluation failure. Retry a permitted action."


class Provenance(Record):
    author: str = "Codex"
    source: Literal["synthetic", "observed_failure", "metamorphic"] = "synthetic"
    human_reviewed: bool = False
    oracle_verified: bool = False
    notes: str = "Synthetic reference; no company or human approval is claimed."


class Case(Record):
    schema_version: int = 1
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,95}$")
    family: str
    split: Literal["dev", "regression", "holdout"] = "dev"
    purpose: Literal["diagnostic", "regression", "challenge"] = "diagnostic"
    identity: Literal["alice", "bob", "ceo"] = "alice"
    fixture: str
    fixture_sha256: str
    clock_utc: datetime
    golden_enabled: bool = False
    tags: list[str] = Field(default_factory=list)
    steps: list[Step]
    references: dict[str, TurnReference]
    initial_reports: list[ReportSeed] = Field(default_factory=list)
    expected_report_count: int = Field(default=0, ge=0)
    expected_final_reports: list[ReportSeed] | None = None
    faults: list[Fault] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)

    @model_validator(mode="after")
    def validate_structure(self) -> Case:
        offset = self.clock_utc.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("Evaluation clock must be UTC-aware")
        if self.schema_version != 1:
            raise ValueError("Unsupported case schema version")
        ids = [s.id for s in self.steps]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Cases require uniquely identified steps")
        asks = {s.id for s in self.steps if s.kind == "ask"}
        if set(self.references) != asks:
            raise ValueError("Reference keys must exactly match ask-step IDs")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.fixture):
            raise ValueError("Fixture must be a registered identifier")
        if not re.fullmatch(r"[a-f0-9]{64}", self.fixture_sha256):
            raise ValueError("A frozen fixture digest is required")
        if (
            self.expected_final_reports is not None
            and len(self.expected_final_reports) != self.expected_report_count
        ):
            raise ValueError("Expected report rows must agree with expected report count")
        if self.steps[0].kind != "ask" or self.steps[0].when_previous_outcome:
            raise ValueError("The first step must be an unconditional user request")
        for step in self.steps:
            if not set(step.when_previous_outcome) <= {
                "answer",
                "clarification",
                "refusal",
                "partial",
            }:
                raise ValueError("Unknown branch outcome")
        return self

    def runtime_input(self) -> dict[str, Any]:
        """Whitelist public scenario input; references and state remain harness-owned."""
        return {
            "case_id": self.id,
            "identity": self.identity,
            "steps": [s.model_dump() for s in self.steps],
        }
