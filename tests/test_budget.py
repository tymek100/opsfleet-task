"""Resource tests exercise shared admission and the real provider wrapper offline."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace

import httpx
import pytest
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

import retail_agent.budget as budget_module
import retail_agent.provider as provider_module
from retail_agent.budget import Budget, LimitReached
from retail_agent.config import Settings
from retail_agent.provider import AccountedModel, ProviderUnavailable


def settings(**overrides) -> Settings:
    # Constructed test configuration never reads .env, environment credentials or ADC.
    return Settings.model_construct(
        **{
            "turn_timeout_seconds": 60,
            "question_budget_usd": 1.0,
            "max_model_calls": 6,
            "max_tool_calls": 8,
            "max_queries": 3,
            "max_query_bytes": 100_000_000,
            "max_context_bytes": 150_000,
            "max_review_bytes": 10_000,
            "review_overhead_bytes": 12_000,
            "review_reserve_seconds": 12,
            "max_output_tokens": 512,
            "review_output_tokens": 256,
            "model_min_interval_seconds": 0,
            "input_usd_per_million": 2,
            "output_usd_per_million": 12,
            "bigquery_usd_per_tib": 6.25,
            **overrides,
        }
    )


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    now = [100.0]
    # Patch this module's clock binding, not time.monotonic used by asyncio itself.
    monkeypatch.setattr(budget_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def assert_limit(code: str, operation) -> None:
    with pytest.raises(LimitReached) as caught:
        operation()
    assert caught.value.code == code


def test_optional_work_preserves_review_cost_and_denied_work_does_not_spend(clock):
    budget = Budget(settings(question_budget_usd=0.1), started=clock[0])
    available = budget.settings.question_budget_usd - budget.review_reserve
    assert available > 0
    budget.reserve(available / 2)
    before = budget.reserved_usd
    assert_limit("cost_budget", lambda: budget.reserve(available))
    assert budget.reserved_usd == before
    budget.model(10_000, 256, reviewer=True)
    assert budget.model_calls == 1
    assert budget.reserved_usd <= budget.settings.question_budget_usd


def test_last_model_call_is_kept_for_review_and_retries_share_the_cap(clock):
    budget = Budget(settings(max_model_calls=3), started=clock[0])
    budget.model(1000, 512, reviewer=False)
    budget.model(1000, 512, reviewer=False)
    before = budget.snapshot()
    assert_limit("model_calls", lambda: budget.model(1000, 512, reviewer=False))
    assert budget.snapshot() == before
    budget.model(1000, 256, reviewer=True)
    assert budget.model_calls == 3
    assert_limit("model_calls", lambda: budget.model(1000, 256, reviewer=True))


def test_review_corrections_share_original_ledger(clock):
    budget = Budget(settings(max_model_calls=4), started=clock[0])
    budget.model(1000, 512, reviewer=False)
    budget.model(1500, 256, reviewer=True)
    after_review = budget.reserved_usd
    budget.model(2000, 512, reviewer=False)
    assert budget.reserved_usd > after_review
    assert_limit("model_calls", lambda: budget.model(100, 512, reviewer=False))
    budget.model(2500, 256, reviewer=True)
    assert budget.model_calls == 4


def test_queries_and_models_reserve_against_one_cost_cap(clock):
    budget = Budget(settings(), started=clock[0])
    budget.query()
    query_cost = budget.settings.max_query_bytes / 2**40 * budget.settings.bigquery_usd_per_tib
    assert budget.reserved_usd == pytest.approx(query_cost)
    budget.model(1000, 512, reviewer=False)
    assert budget.reserved_usd > query_cost
    budget.settings.question_budget_usd = budget.reserved_usd + budget.review_reserve
    assert_limit("cost_budget", budget.query)
    assert budget.queries == 1


def test_query_and_tool_limits_deny_without_increment(clock):
    budget = Budget(settings(max_queries=1, max_tool_calls=2), started=clock[0])
    budget.query()
    assert_limit("queries", budget.query)
    budget.tool()
    assert_limit("tools", budget.tool)
    budget.tool(completion=True)
    assert_limit("tools", lambda: budget.tool(completion=True))
    assert budget.queries == 1 and budget.tool_calls == 2


def test_oversize_context_is_rejected_before_spend_for_both_roles(clock):
    budget = Budget(settings(max_context_bytes=4000), started=clock[0])
    for reviewer in (False, True):
        assert_limit("context_size", lambda role=reviewer: budget.model(4001, 256, reviewer=role))
    assert budget.model_calls == 0 and budget.reserved_usd == 0


def test_review_envelope_is_reserved_and_bounded(clock):
    budget = Budget(settings(), started=clock[0])
    max_bytes = budget.settings.max_review_bytes + budget.settings.review_overhead_bytes
    expected_cost = (
        max_bytes * budget.settings.input_usd_per_million
        + budget.settings.review_output_tokens * budget.settings.output_usd_per_million
    ) / 1e6
    assert budget.review_reserve == pytest.approx(expected_cost)
    assert_limit("review_context_size", lambda: budget.model(max_bytes + 1, 256, reviewer=True))
    assert budget.model_calls == 0 and budget.reserved_usd == 0
    budget.model(max_bytes, 256, reviewer=True)
    assert budget.reserved_usd == pytest.approx(expected_cost)


def test_optional_work_cannot_use_time_reserved_for_review(clock):
    budget = Budget(settings(), started=clock[0])
    clock[0] += 47
    assert budget.work_remaining() == 1
    assert budget.work_remaining(reviewer=True) == 13
    clock[0] += 1
    for operation in (
        budget.work_remaining,
        budget.query,
        lambda: budget.model(1000, 256, reviewer=False),
    ):
        assert_limit("completion_time_reserve", operation)
    assert budget.model_calls == 0 and budget.queries == 0 and budget.reserved_usd == 0
    # The completion action and reviewer are still admitted under the original deadline.
    budget.tool()
    budget.model(1000, 256, reviewer=True)
    assert budget.model_calls == 1 and budget.work_remaining(reviewer=True) == 12


def test_elapsed_deadline_applies_to_queries_tools_models_and_review(clock):
    budget = Budget(settings(turn_timeout_seconds=60), started=clock[0])
    clock[0] += 40
    assert budget.remaining() == 20
    budget.tool()
    budget.query()
    before = budget.snapshot()
    clock[0] += 20
    for operation in (
        budget.remaining,
        budget.tool,
        budget.query,
        lambda: budget.reserve(0),
        lambda: budget.model(1000, 256, reviewer=False),
        lambda: budget.model(1000, 256, reviewer=True),
    ):
        assert_limit("deadline", operation)
    assert budget.snapshot() == before


class ScriptedProvider(BaseLlm):
    modes: list[str]
    _calls: int = PrivateAttr(default=0)

    @property
    def calls(self) -> int:
        return self._calls

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        mode = self.modes[min(self._calls, len(self.modes) - 1)]
        self._calls += 1
        if mode == "network":
            raise httpx.ConnectError("synthetic offline network fault")
        yield LlmResponse(
            content=types.Content(
                role="model", parts=[types.Part(text="Reviewed fixture response")]
            ),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=12,
                candidates_token_count=8,
                thoughts_token_count=3,
            ),
        )
        if mode == "partial_then_network":
            raise httpx.ConnectError("synthetic failure after a response")


def request(text: str = "Give a short supported answer.") -> LlmRequest:
    return LlmRequest(
        contents=[types.Content(role="user", parts=[types.Part(text=text)])],
        config=types.GenerateContentConfig(max_output_tokens=256),
    )


@pytest.fixture
def skip_retry_wait(monkeypatch: pytest.MonkeyPatch):
    waited: list[float] = []

    async def no_wait(seconds: float):
        waited.append(seconds)

    monkeypatch.setattr(provider_module.asyncio, "sleep", no_wait)
    return waited


@pytest.mark.asyncio
async def test_provider_retry_and_reviewer_are_accounted_in_same_budget(skip_retry_wait):
    budget = Budget(settings(max_model_calls=4))
    events = []

    def emit(event, **fields):
        events.append({"event": event, **fields})

    provider = ScriptedProvider(model="offline-model", modes=["network", "ok"])
    analyst = AccountedModel(model=provider.model, delegate=provider).bind(budget, emit)
    observed = [item async for item in analyst.generate_content_async(request())]
    assert len(observed) == 1 and provider.calls == 2
    assert budget.model_calls == 2
    assert len(skip_retry_wait) == 1
    after_analyst = budget.reserved_usd
    reviewer = AccountedModel(model=provider.model, delegate=provider).bind(
        budget, emit, reviewer=True
    )
    assert len([item async for item in reviewer.generate_content_async(request())]) == 1
    assert budget.model_calls == 3 and budget.reserved_usd > after_analyst
    assert budget.input_tokens == 24 and budget.output_tokens == 16 and budget.thinking_tokens == 6
    assert [event["role"] for event in events if event["event"] == "model_call"] == [
        "analyst",
        "analyst",
        "reviewer",
    ]


@pytest.mark.asyncio
async def test_retry_cannot_consume_reserved_reviewer_call(skip_retry_wait):
    budget = Budget(settings(max_model_calls=2))
    provider = ScriptedProvider(model="offline-model", modes=["network", "ok"])
    analyst = AccountedModel(model=provider.model, delegate=provider).bind(
        budget, lambda *a, **k: None
    )
    with pytest.raises(LimitReached) as caught:
        _ = [item async for item in analyst.generate_content_async(request())]
    assert caught.value.code == "model_calls"
    assert provider.calls == 1 and budget.model_calls == 1
    reviewer = AccountedModel(model=provider.model, delegate=provider).bind(
        budget,
        lambda *a, **k: None,
        reviewer=True,
    )
    assert len([item async for item in reviewer.generate_content_async(request())]) == 1
    assert budget.model_calls == 2


@pytest.mark.asyncio
async def test_failure_after_emission_is_not_retried(skip_retry_wait):
    budget = Budget(settings())
    provider = ScriptedProvider(model="offline-model", modes=["partial_then_network", "ok"])
    analyst = AccountedModel(model=provider.model, delegate=provider).bind(
        budget, lambda *a, **k: None
    )
    observed = []
    with pytest.raises(ProviderUnavailable):
        async for item in analyst.generate_content_async(request()):
            observed.append(item)
    assert len(observed) == 1 and provider.calls == 1 and budget.model_calls == 1
    assert not skip_retry_wait


@pytest.mark.asyncio
async def test_provider_stops_after_one_transient_retry(skip_retry_wait):
    budget = Budget(settings())
    provider = ScriptedProvider(model="offline-model", modes=["network"])
    analyst = AccountedModel(model=provider.model, delegate=provider).bind(
        budget, lambda *a, **k: None
    )
    with pytest.raises(ProviderUnavailable):
        _ = [item async for item in analyst.generate_content_async(request())]
    assert provider.calls == 2 and budget.model_calls == 2 and len(skip_retry_wait) == 1


@pytest.mark.asyncio
async def test_personal_data_is_rejected_before_provider_call():
    budget = Budget(settings())
    provider = ScriptedProvider(model="offline-model", modes=["ok"])
    analyst = AccountedModel(model=provider.model, delegate=provider).bind(
        budget, lambda *a, **k: None
    )
    with pytest.raises(ValueError, match="personal contact"):
        _ = [
            item
            async for item in analyst.generate_content_async(request("Email: test@example.invalid"))
        ]
    assert provider.calls == 0 and budget.model_calls == 0 and budget.reserved_usd == 0
