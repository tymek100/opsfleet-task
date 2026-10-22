from collections.abc import AsyncGenerator

import pytest
from google import genai
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types

from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.model import BoundedGemini
from retail_agent.observability import Trace


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(503, 2), (429, 2), (403, 1)])
async def test_provider_retry_bounded_and_accounted(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, status: int, expected: int
) -> None:
    calls = 0

    async def fail(
        self: Gemini, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        nonlocal calls
        del self, llm_request, stream
        calls += 1
        raise errors.APIError(status, {"error": {"code": status, "message": "synthetic failure"}})
        yield LlmResponse()  # pragma: no cover

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(Gemini, "generate_content_async", fail)
    monkeypatch.setattr("retail_agent.model.asyncio.sleep", no_sleep)
    budget = Budget(settings)
    budget.model(100, 4096)
    trace = Trace()
    client = genai.Client(api_key="fake")
    model = BoundedGemini(model="fake", client=client).bind(budget, trace)
    with pytest.raises(errors.APIError):
        async for _ in model.generate_content_async(
            LlmRequest(contents=[types.Content(parts=[types.Part(text="x")])])
        ):
            pass
    assert calls == expected and budget.model_calls == expected
    await client.aio.aclose()
    client.close()


@pytest.mark.asyncio
async def test_retry_honors_provider_delay(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    calls = 0
    delays: list[float] = []

    async def flaky(
        self: Gemini, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        nonlocal calls
        del self, llm_request, stream
        calls += 1
        if calls == 1:
            raise errors.ClientError(429, {"error": {"details": [{"retryDelay": "18s"}]}})
        yield LlmResponse(content=types.Content(parts=[types.Part(text="ok")]))

    async def sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(Gemini, "generate_content_async", flaky)
    monkeypatch.setattr("retail_agent.model.asyncio.sleep", sleep)
    budget = Budget(settings)
    budget.model(100, 4096)
    client = genai.Client(api_key="fake")
    model = BoundedGemini(model="fake", client=client).bind(budget, Trace())
    responses = [r async for r in model.generate_content_async(LlmRequest())]
    assert len(responses) == 1 and delays == [19] and budget.model_calls == 2
    await client.aio.aclose()
    client.close()
