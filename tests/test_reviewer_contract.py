"""Reviewer findings are complete and consistent before approval can be accepted."""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from google.adk.models import BaseLlm
from google.adk.models._capabilities import LlmCapabilities
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field, PrivateAttr, SecretStr, ValidationError

from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.contracts import REVIEW_CATEGORIES, Review, ReviewIssue
from retail_agent.provider import ProviderUnavailable, request_json
from retail_agent.reviewer import evaluate


def review_json(*, decision: str = "approve", failed: str | None = None) -> dict[str, Any]:
    return {
        "checks": [
            {
                "category": category,
                "passed": category != failed,
                "finding": "A concise test finding about the supplied candidate.",
                "evidence_ids": [],
            }
            for category in REVIEW_CATEGORIES
        ],
        "issues": [],
        "save_authorized": False,
        "decision": decision,
    }


class ReviewerBoundary(BaseLlm):
    model: str = "offline-reviewer-boundary"
    responses: list[dict[str, Any]] = Field(exclude=True)
    _requests: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        index = len(self._requests)
        assert not llm_request.tools_dict
        self._requests.append(json.loads(request_json(llm_request)))
        assert index < len(self.responses), "Reviewer exceeded its scripted allowance"
        yield LlmResponse(
            content=types.Content(
                role="model", parts=[types.Part(text=json.dumps(self.responses[index]))]
            ),
            partial=False,
        )


def settings(tmp_path: Path) -> Settings:
    return Settings(
        gemini_api_key=SecretStr("offline-test-key"),
        google_cloud_project="offline-project",
        data_dir=tmp_path,
        backend="fixture",
        max_model_calls=4,
        max_context_bytes=150_000,
        max_review_bytes=20_000,
        question_budget_usd=10,
        turn_timeout_seconds=15,
        review_thinking_level="medium",
        model_min_interval_seconds=0,
    )


def payload() -> dict[str, Any]:
    return {
        "question": "Which year should I specify?",
        "scope": "Calvin Klein",
        "conversation": [],
        "candidate": {
            "markdown": "Which year should I use for the requested report?",
            "outcome": "clarification",
        },
        "evidence": [],
        "other_results_manifest": [],
        "retrieved_methods": [],
        "pending_save": None,
        "save_target": None,
    }


def test_response_schema_requires_findings_before_the_decision() -> None:
    schema = Review.response_schema()
    assert list(schema["properties"]) == ["checks", "issues", "save_authorized", "decision"]
    assert set(schema["required"]) == {"checks", "issues", "save_authorized", "decision"}
    assert schema["properties"]["checks"]["minItems"] == 5
    assert schema["properties"]["checks"]["maxItems"] == 5
    assert Review.model_validate(review_json()).decision == "approve"


@pytest.mark.parametrize(
    "defect", ["missing", "duplicate", "failed", "unresolved_issue", "string_boolean"]
)
def test_incomplete_or_inconsistent_approval_fails_validation(defect: str) -> None:
    candidate = review_json()
    if defect == "missing":
        del candidate["checks"]
    elif defect == "duplicate":
        candidate["checks"][-1] = copy.deepcopy(candidate["checks"][0])
    elif defect == "failed":
        candidate["checks"][2]["passed"] = False
    elif defect == "unresolved_issue":
        candidate["issues"] = [
            {
                "category": "grounding",
                "message": "A factual claim is unsupported.",
                "evidence_ids": [],
            }
        ]
    else:
        candidate["checks"][0]["passed"] = "true"
    with pytest.raises(ValidationError):
        Review.model_validate(candidate)


def test_internal_boundary_revision_does_not_fabricate_review_findings() -> None:
    review = Review(
        decision="revise",
        issues=[ReviewIssue(category="evidence_bundle_too_large", message="Narrow the evidence.")],
    )
    assert review.checks == []
    assert review.decision == "revise"


@pytest.mark.asyncio
async def test_missing_checks_get_one_schema_repair_in_same_review_conversation(
    tmp_path: Path,
) -> None:
    config = settings(tmp_path)
    budget = Budget(config)
    malformed = {"decision": "approve", "issues": [], "save_authorized": False}
    model = ReviewerBoundary(responses=[malformed, review_json()])
    events: list[dict] = []
    result = await evaluate(
        payload(),
        model,
        budget,
        config,
        lambda event, **fields: events.append({"event": event, **fields}),
    )
    assert result.decision == "approve" and len(result.checks) == 5
    assert len(model._requests) == budget.model_calls == 2
    assert any(event["event"] == "review_schema_error" for event in events)
    assert "Which year should I use for the requested report?" in json.dumps(model._requests[1])
    assert model._requests[0]["config"]["thinking_config"]["thinking_level"] == "MEDIUM"


@pytest.mark.asyncio
async def test_failed_check_cannot_approve_and_revision_issues_are_usable(tmp_path: Path) -> None:
    config = settings(tmp_path)
    model = ReviewerBoundary(
        responses=[
            review_json(failed="grounding"),
            review_json(decision="revise", failed="grounding"),
        ]
    )
    result = await evaluate(
        payload(), model, Budget(config), config, lambda *_args, **_kwargs: None
    )
    assert result.decision == "revise"
    assert result.issues[0].category == "grounding"
    assert result.issues[0].message == result.checks[1].finding
    assert len(model._requests) == 2


@pytest.mark.asyncio
async def test_fabricated_review_evidence_id_requires_correction(tmp_path: Path) -> None:
    config = settings(tmp_path)
    incorrect = review_json()
    incorrect["checks"][1]["evidence_ids"] = ["E999"]
    model = ReviewerBoundary(responses=[incorrect, review_json()])
    result = await evaluate(
        payload(), model, Budget(config), config, lambda *_args, **_kwargs: None
    )
    assert result.decision == "approve"
    assert len(model._requests) == 2
    assert all(check.evidence_ids == [] for check in result.checks)


@pytest.mark.asyncio
async def test_repeated_missing_checks_end_unavailable_without_approval(tmp_path: Path) -> None:
    config = settings(tmp_path)
    model = ReviewerBoundary(responses=[{"decision": "approve"}, {"decision": "approve"}])
    budget = Budget(config)
    with pytest.raises(ProviderUnavailable):
        await evaluate(payload(), model, budget, config, lambda *_args, **_kwargs: None)
    assert len(model._requests) == budget.model_calls == 2


@pytest.mark.asyncio
async def test_oversized_evidence_never_calls_model_or_invents_checks(tmp_path: Path) -> None:
    config = settings(tmp_path)
    config.max_review_bytes = 2000
    candidate = payload()
    candidate["candidate"]["markdown"] = "x" * 3000
    model = ReviewerBoundary(responses=[])
    budget = Budget(config)
    result = await evaluate(candidate, model, budget, config, lambda *_args, **_kwargs: None)
    assert result.decision == "revise" and result.checks == []
    assert result.issues[0].category == "evidence_bundle_too_large"
    assert budget.model_calls == 0 and model._requests == []
