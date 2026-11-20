"""Provider metering refunds completed calls without refunding unknown work."""

import asyncio
from collections.abc import AsyncGenerator

import httpx
import pytest
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.provider import AccountedModel, ProviderUnavailable


class MeteredProvider(BaseLlm):
    model: str = "offline-metered-model"
    responses: list[LlmResponse]
    failure: str | None = None
    _calls: int = PrivateAttr(default=0)

    @property
    def calls(self) -> int:
        return self._calls

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self._calls += 1
        for response in self.responses:
            yield response
        if self.failure == "network":
            raise httpx.ConnectError("Synthetic interruption after partial output")
        if self.failure == "cancelled":
            raise asyncio.CancelledError


def request(text: str = "Find qualifying sales totals.") -> LlmRequest:
    return LlmRequest(
        contents=[types.Content(role="user", parts=[types.Part(text=text)])],
        config=types.GenerateContentConfig(max_output_tokens=4096),
    )


def response(
    usage: types.GenerateContentResponseUsageMetadata | None,
    *,
    partial: bool | None = None,
    terminal: bool = False,
) -> LlmResponse:
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name="describe_data", args={}))],
        ),
        usage_metadata=usage,
        partial=partial,
        finish_reason=types.FinishReason.STOP if terminal else None,
    )


def usage(**overrides) -> types.GenerateContentResponseUsageMetadata:
    return types.GenerateContentResponseUsageMetadata.model_construct(
        **{
            "prompt_token_count": 100,
            "candidates_token_count": 20,
            "thoughts_token_count": 5,
            **overrides,
        }
    )


def wrapper(provider: MeteredProvider, budget: Budget, events: list[dict], *, reviewer=False):
    def emit(event: str, **fields) -> None:
        events.append({"event": event, **fields})

    return AccountedModel(model=provider.model, delegate=provider).bind(
        budget, emit, reviewer=reviewer
    )


@pytest.mark.asyncio
async def test_completed_call_is_refunded_before_consumer_starts_nested_review():
    budget = Budget(Settings.model_construct())
    events: list[dict] = []
    provider = MeteredProvider(responses=[response(usage())])
    analyst = wrapper(provider, budget, events)
    reviewer = wrapper(provider, budget, events, reviewer=True)

    async for _ in analyst.generate_content_async(request()):
        # ADK executes finish_answer and its reviewer before resuming this generator.
        assert budget.reserved_usd == 0
        assert budget.spent_usd == pytest.approx(0.0005)
        assert len([item async for item in reviewer.generate_content_async(request())]) == 1

    assert budget.model_calls == 2
    assert budget.spent_usd == pytest.approx(0.001)
    assert budget.reserved_usd == 0
    assert [event["role"] for event in events if event["event"] == "model_usage"] == [
        "analyst",
        "reviewer",
    ]


@pytest.mark.asyncio
async def test_six_short_tool_responses_do_not_accumulate_maximum_output_cost():
    budget = Budget(Settings.model_construct())
    events: list[dict] = []
    provider = MeteredProvider(
        responses=[response(usage(prompt_token_count=6000, candidates_token_count=200))]
    )
    analyst = wrapper(provider, budget, events)
    for _ in range(6):
        assert (
            len(
                [
                    item
                    async for item in analyst.generate_content_async(request("retail data " * 5000))
                ]
            )
            == 1
        )
        assert budget.reserved_usd == 0
    assert provider.calls == budget.model_calls == 6
    assert budget.spent_usd == pytest.approx(0.08676)
    assert budget.input_tokens == 36_000
    assert budget.output_tokens == 1200
    assert budget.thinking_tokens == 30


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        None,
        usage(prompt_token_count=None),
        usage(candidates_token_count=None),
        usage(prompt_token_count=-1),
        usage(candidates_token_count=True),
        usage(thoughts_token_count="5"),
        usage(tool_use_prompt_token_count=-1),
        usage(total_token_count=999),
    ],
)
async def test_unknown_or_invalid_completed_usage_retains_its_reservation(metadata):
    budget = Budget(Settings.model_construct())
    events: list[dict] = []
    provider = MeteredProvider(responses=[response(metadata)])
    analyst = wrapper(provider, budget, events)
    assert len([item async for item in analyst.generate_content_async(request())]) == 1
    assert budget.reserved_usd > 4096 * budget.settings.output_usd_per_million / 1e6
    assert budget.spent_usd == 0
    assert budget.input_tokens == budget.output_tokens == budget.thinking_tokens == 0
    assert not any(event["event"] == "model_usage" for event in events)


@pytest.mark.asyncio
async def test_cached_input_tool_use_and_thinking_are_accounted_without_double_counting():
    budget = Budget(Settings.model_construct())
    events: list[dict] = []
    metadata = usage(
        prompt_token_count=100,
        cached_content_token_count=80,
        tool_use_prompt_token_count=30,
        candidates_token_count=20,
        thoughts_token_count=10,
        total_token_count=160,
    )
    analyst = wrapper(MeteredProvider(responses=[response(metadata)]), budget, events)
    assert len([item async for item in analyst.generate_content_async(request())]) == 1
    assert budget.input_tokens == 130
    assert budget.output_tokens == 20
    assert budget.thinking_tokens == 10
    assert budget.spent_usd == pytest.approx(0.00062)
    assert budget.reserved_usd == 0


@pytest.mark.asyncio
async def test_explicit_zero_usage_releases_the_hold():
    budget = Budget(Settings.model_construct())
    events: list[dict] = []
    metadata = usage(
        prompt_token_count=0,
        candidates_token_count=0,
        thoughts_token_count=None,
        total_token_count=0,
    )
    analyst = wrapper(MeteredProvider(responses=[response(metadata)]), budget, events)
    assert len([item async for item in analyst.generate_content_async(request())]) == 1
    assert budget.reserved_usd == budget.spent_usd == 0
    assert len([event for event in events if event["event"] == "model_usage"]) == 1


@pytest.mark.asyncio
async def test_cumulative_stream_metadata_is_settled_once_at_completion():
    budget = Budget(Settings.model_construct())
    events: list[dict] = []
    final_usage = usage(candidates_token_count=40, thoughts_token_count=10)
    provider = MeteredProvider(
        responses=[
            response(usage(), partial=True),
            response(final_usage, partial=True),
            response(final_usage, partial=False, terminal=True),
            response(final_usage, partial=False, terminal=True),
        ]
    )
    analyst = wrapper(provider, budget, events)
    async for item in analyst.generate_content_async(request(), stream=True):
        if item.partial:
            assert budget.spent_usd == 0
            assert budget.reserved_usd > 0
        else:
            assert budget.reserved_usd == 0
    assert budget.input_tokens == 100
    assert budget.output_tokens == 40
    assert budget.thinking_tokens == 10
    assert budget.spent_usd == pytest.approx(0.0008)
    assert len([event for event in events if event["event"] == "model_usage"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["network", "cancelled"])
async def test_interrupted_partial_response_retains_unknown_cost_and_is_not_retried(failure):
    budget = Budget(Settings.model_construct())
    events: list[dict] = []
    provider = MeteredProvider(responses=[response(usage(), partial=True)], failure=failure)
    analyst = wrapper(provider, budget, events)
    observed = []
    expected = ProviderUnavailable if failure == "network" else asyncio.CancelledError
    with pytest.raises(expected):
        async for item in analyst.generate_content_async(request(), stream=True):
            observed.append(item)
    assert len(observed) == 1
    assert provider.calls == budget.model_calls == 1
    assert budget.spent_usd == 0
    assert budget.reserved_usd > 0
    assert not any(event["event"] == "model_usage" for event in events)
