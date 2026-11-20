"""Structured interpretation, bounded repair and direct execution; no live NLP assertions."""

import json
from collections.abc import AsyncGenerator
from datetime import date
from typing import cast

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import ValidationError

from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.model import BoundedGemini
from retail_agent.models import DEMO_USERS, Answer, Intent
from retail_agent.observability import Trace
from retail_agent.planning import TurnPlan, propose_plan


def analytical_plan(**changes: object) -> dict[str, object]:
    return {
        "route": "analysis",
        "intent": Intent.model_validate(
            {
                "period": {"start": "2026-01-01", "end": "2026-04-01"},
                "requirements": [{"dimension": "total"}],
                **changes,
            }
        ).model_dump(mode="json"),
    }


class Provider:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, replies: list[object]) -> None:
        self.requests: list[LlmRequest] = []
        iterator = iter(replies)

        async def generate(
            model: BoundedGemini, request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            del model, stream
            self.requests.append(request)
            reply = next(iterator)
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, types.Content):
                yield LlmResponse(content=reply)
                return
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=reply if isinstance(reply, str) else json.dumps(reply))],
                )
            )

        monkeypatch.setattr(BoundedGemini, "generate_content_async", generate)


@pytest.mark.asyncio
async def test_one_tool_free_planning_call_receives_context_and_executable_schema(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    provider = Provider(monkeypatch, [analytical_plan()])
    budget = Budget(settings)
    plan = await propose_plan(
        "Use the previous quarter.",
        None,
        [{"question": "Which quarter?", "answer": "Q1 2026"}],
        DEMO_USERS["alice"],
        date(2026, 10, 25),
        BoundedGemini(model="fixture"),
        budget,
        Trace(),
    )
    assert plan.intent and budget.model_calls == 1 and len(provider.requests) == 1
    request = provider.requests[0]
    assert not request.tools_dict and not request.config.model_dump().get("tools")
    payload = request.model_dump_json(exclude={"tools_dict"})
    assert all(
        x in payload
        for x in [
            "2026-10-25",
            "Calvin Klein",
            "Which quarter?",
            "query_schema",
            "inactivity_days",
            "maximum",
        ]
    )


def test_clarification_must_identify_missing_information_and_cannot_confirm() -> None:
    with pytest.raises(ValidationError):
        TurnPlan.model_validate(
            {"route": "clarification", "clarification_question": "Confirm again?"}
        )
    with pytest.raises(ValidationError):
        TurnPlan.model_validate({"route": "confirm", "token": "anything"})
    with pytest.raises(ValidationError):
        TurnPlan.model_validate({"route": "save", "intent": analytical_plan()["intent"]})


def test_supported_constraints_cannot_be_reported_as_unsupported() -> None:
    from retail_agent.capabilities import CapabilityIssue

    for fields in [
        {"kind": "unsupported_filter", "field": "brands"},
        {"kind": "unsupported_metric", "field": "revenue"},
        {"kind": "out_of_range", "field": "inactivity_days", "value": 30},
    ]:
        with pytest.raises(ValidationError):
            CapabilityIssue.model_validate(fields)


def test_saved_legacy_report_contract_remains_readable(answer: Answer) -> None:
    old = answer.model_dump(mode="json")
    old["intent"] = {
        **cast(dict[str, object], analytical_plan()["intent"]),
        "pending_quarter": 1,
        "period_error": "none",
        "clarification": "none",
    }
    loaded = Answer.model_validate(old)
    assert loaded.intent and loaded.intent.period and loaded.intent.period.start == date(2026, 1, 1)


def test_provider_schema_requires_explicit_decisions_and_rejects_omitted_filter() -> None:
    schema = TurnPlan.model_json_schema()
    proposal = schema["$defs"]["ProposedIntent"]
    assert set(proposal["required"]) == set(proposal["properties"])
    assert "missing_information" in schema["required"]
    payload = analytical_plan()
    contract = cast(dict[str, object], payload["intent"])
    del contract["product_ids"]
    with pytest.raises(ValidationError, match="product_ids"):
        TurnPlan.model_validate(payload)
