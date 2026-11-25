"""Small runtime records; analytical plans and answer layouts belong to the model."""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass(frozen=True)
class Identity:
    user_id: str
    brands: tuple[str, ...] | None

    @property
    def scope(self) -> str:
        return ", ".join(self.brands) if self.brands is not None else "all brands"


# A single local workspace owns conversations and reports. It has no brand restriction.
WORKSPACE_IDENTITY = Identity("workspace", None)


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str
    message: str
    evidence_ids: list[str] = Field(default_factory=list)


REVIEW_CATEGORIES = ("coverage", "grounding", "metrics", "presentation", "operations")


class ReviewCheck(BaseModel):
    """A short observable finding, not the reviewer's private reasoning."""

    model_config = ConfigDict(extra="forbid")
    category: Literal["coverage", "grounding", "metrics", "presentation", "operations"]
    passed: bool = Field(strict=True)
    finding: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(default_factory=list)


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Field order keeps the auditable findings ahead of the decision in model output.
    # Internal boundary failures may return a revision with no invented checks.
    checks: list[ReviewCheck] = Field(default_factory=list)
    issues: list[ReviewIssue] = Field(default_factory=list)
    save_authorized: bool = False
    decision: Literal["approve", "revise", "stop"]

    @model_validator(mode="after")
    def consistent_approval(self) -> "Review":
        categories = [check.category for check in self.checks]
        complete = len(categories) == len(REVIEW_CATEGORIES) and set(categories) == set(
            REVIEW_CATEGORIES
        )
        if self.checks and not complete:
            raise ValueError("Provide each of the five review categories exactly once.")
        if self.decision == "approve" and (
            not complete or not all(check.passed for check in self.checks) or self.issues
        ):
            raise ValueError("Approval requires five passed checks and no unresolved issues.")
        return self

    @classmethod
    def response_schema(cls) -> dict[str, Any]:
        """Require complete model findings while allowing internal unevaluated revisions."""
        schema = cls.model_json_schema()
        schema["required"] = ["checks", "issues", "save_authorized", "decision"]
        schema["properties"]["checks"].update(minItems=5, maxItems=5)
        return schema


@dataclass
class Answer:
    id: str
    markdown: str
    evidence_ids: list[str]
    outcome: str
    approved: bool
    receipts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TurnResult:
    answer: Answer | None
    status: str
    message: str
    trace: list[dict[str, Any]]
    usage: dict[str, Any]
    evidence: list[dict[str, Any]]
    elapsed_seconds: float
    deletion_preview: dict[str, Any] | None = None
