"""Real accounting wrapper around an offline external-provider boundary."""

import asyncio

import httpx
import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from retail_agent.budget import Budget
from retail_agent.provider import AccountedModel, ProviderUnavailable
from tests.support.models import ScriptedModel, text, usage


def request(value="Summarize qualifying sales."):
    return LlmRequest(
        contents=[types.Content(role="user", parts=[types.Part(text=value)])],
        config=types.GenerateContentConfig(max_output_tokens=4096),
    )


def metered(model, budget, events, reviewer=False):
    return AccountedModel(model=model.model, delegate=model).bind(
        budget, lambda event, **fields: events.append({"event": event, **fields}), reviewer=reviewer
    )


async def collect(model, *, stream=False, prompt=None):
    return [
        item
        async for item in model.generate_content_async(
            request(prompt) if prompt else request(), stream=stream
        )
    ]


async def test_settlement_occurs_before_nested_review_and_counts_each_role_once(settings):
    budget, events = Budget(settings), []
    boundary = ScriptedModel(script=[text("Candidate"), text("Review")])
    analyst = metered(boundary, budget, events)
    reviewer = metered(boundary, budget, events, reviewer=True)
    async for _ in analyst.generate_content_async(request()):
        assert budget.reserved_usd == 0
        assert budget.spent_usd == pytest.approx(0.0005)
        await collect(reviewer)
    assert budget.model_calls == 2
    assert budget.spent_usd == pytest.approx(0.001)
    assert [e["role"] for e in events if e["event"] == "model_usage"] == ["analyst", "reviewer"]


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        usage(prompt_token_count=None),
        usage(candidates_token_count=True),
        usage(thoughts_token_count=-1),
        usage(total_token_count=999),
    ],
)
async def test_missing_or_inconsistent_usage_keeps_conservative_hold(settings, metadata):
    budget, events = Budget(settings), []
    model = ScriptedModel(
        script=[LlmResponse(content=text("Done"), partial=False, usage_metadata=metadata)]
    )
    await collect(metered(model, budget, events))
    assert budget.reserved_usd > 0
    assert budget.spent_usd == 0
    assert not any(e["event"] == "model_usage" for e in events)


async def test_stream_cumulative_usage_is_not_double_counted(settings):
    budget, events = Budget(settings), []
    final = usage(
        prompt_token_count=100,
        candidates_token_count=40,
        thoughts_token_count=10,
        tool_use_prompt_token_count=30,
        cached_content_token_count=80,
        total_token_count=180,
    )
    model = ScriptedModel(
        script=[
            [
                LlmResponse(content=text("Draft"), partial=True, usage_metadata=usage()),
                LlmResponse(
                    content=text("Done"), partial=False, turn_complete=True, usage_metadata=final
                ),
                LlmResponse(
                    content=text("Done"), partial=False, turn_complete=True, usage_metadata=final
                ),
            ]
        ]
    )
    await collect(metered(model, budget, events), stream=True)
    assert (budget.input_tokens, budget.output_tokens, budget.thinking_tokens) == (130, 40, 10)
    assert budget.spent_usd == pytest.approx(0.00086)
    assert budget.reserved_usd == 0
    assert len([e for e in events if e["event"] == "model_usage"]) == 1


async def test_retry_retains_unknown_first_attempt_and_settles_success(settings, monkeypatch):
    async def immediate(_delay):
        return None

    monkeypatch.setattr("retail_agent.provider.asyncio.sleep", immediate)
    budget, events = Budget(settings), []
    model = ScriptedModel(script=[httpx.ConnectError("synthetic outage"), text("Recovered")])
    assert len(await collect(metered(model, budget, events))) == 1
    assert budget.model_calls == 2 and len(model.requests) == 2
    assert budget.reserved_usd > 0 and budget.spent_usd == pytest.approx(0.0005)
    assert [e["attempt"] for e in events if e["event"] == "model_call"] == [1, 2]


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError("synthetic outage"), asyncio.CancelledError()]
)
async def test_partial_output_failure_is_never_retried_or_refunded(settings, failure):
    budget, events = Budget(settings), []
    model = ScriptedModel(
        script=[
            [
                LlmResponse(content=text("Partial"), partial=True, usage_metadata=usage()),
                failure,
            ]
        ]
    )
    expected = (
        asyncio.CancelledError
        if isinstance(failure, asyncio.CancelledError)
        else ProviderUnavailable
    )
    with pytest.raises(expected):
        await collect(metered(model, budget, events), stream=True)
    assert len(model.requests) == budget.model_calls == 1
    assert budget.reserved_usd > 0 and budget.spent_usd == 0


async def test_contact_canary_is_blocked_before_any_provider_request(settings):
    budget, events = Budget(settings), []
    model = ScriptedModel()
    with pytest.raises(ValueError):
        await collect(metered(model, budget, events), prompt="Send results to canary@example.test")
    assert model.requests == [] and budget.model_calls == 0
