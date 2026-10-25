"""Single bounded transient retry, charged to the same turn budget."""

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import httpx
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors
from pydantic import PrivateAttr

from retail_agent.budget import Budget
from retail_agent.models import AppError, RateLimitError
from retail_agent.observability import Trace


@dataclass
class ModelPacer:
    interval: float
    last_call: float = 0

    async def wait(self, budget: Budget) -> None:
        delay = max(0, self.interval - (time.monotonic() - self.last_call))
        if delay >= budget.remaining():
            raise RateLimitError()
        if delay:
            await asyncio.sleep(delay)
        self.last_call = time.monotonic()


class BoundedGemini(Gemini):
    _budget: Budget = PrivateAttr()
    _trace: Trace = PrivateAttr()
    _pacer: ModelPacer = PrivateAttr()

    def bind(
        self, budget: Budget, trace: Trace, pacer: ModelPacer | None = None
    ) -> "BoundedGemini":
        self._budget, self._trace = budget, trace
        self._pacer = pacer or ModelPacer(0)
        return self

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        emitted = False
        for attempt in range(2):
            await self._pacer.wait(self._budget)
            try:
                async for response in super().generate_content_async(llm_request, stream=stream):
                    usage = response.usage_metadata
                    self._trace.emit(
                        "provider_usage",
                        input_tokens=usage.prompt_token_count if usage else None,
                        output_tokens=usage.candidates_token_count if usage else None,
                        thinking_tokens=usage.thoughts_token_count if usage else None,
                        cached_tokens=usage.cached_content_token_count if usage else None,
                    )
                    emitted = True
                    yield response
                return
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if emitted or attempt == 1:
                    raise AppError(
                        "Gemini response timed out or the connection was interrupted. No complete model response was received; please try again."
                    ) from None
                self._trace.emit("model_retry", status=type(exc).__name__, attempt=attempt + 2)
                self._budget.model(
                    len(llm_request.model_dump_json(exclude={"tools_dict"}).encode()),
                    llm_request.config.max_output_tokens or self._budget.settings.max_output_tokens,
                )
                if self._budget.remaining() <= 1:
                    raise AppError(
                        "Gemini response timed out; the question deadline does not permit another attempt."
                    ) from None
                await asyncio.sleep(1)
            except errors.APIError as exc:
                if emitted or attempt == 1 or exc.code not in (429, 500, 502, 503, 504):
                    if exc.code == 429:
                        raise RateLimitError() from None
                    if exc.code in (500, 502, 503, 504):
                        self._trace.emit("provider_unavailable", status=exc.code)
                        message = (
                            "Gemini timed out (504)."
                            if exc.code == 504
                            else f"Gemini is temporarily unavailable ({exc.code})."
                        )
                        raise AppError(
                            message
                            + " No complete model response was received. Please try again later."
                        ) from None
                    raise
                self._trace.emit("model_retry", status=exc.code, attempt=attempt + 2)
                self._budget.model(
                    len(llm_request.model_dump_json(exclude={"tools_dict"}).encode()),
                    llm_request.config.max_output_tokens or self._budget.settings.max_output_tokens,
                )
                retry = re.search(
                    r'"retryDelay":\s*"([0-9.]+)s"',
                    json.dumps(exc.details),  # pyright: ignore[reportUnknownMemberType]  # SDK error JSON is untyped.
                )
                delay = max(1.0, float(retry.group(1)) + 1 if retry else 1.0)
                if delay > 60 or delay >= self._budget.remaining():
                    if exc.code == 429:
                        raise RateLimitError() from None
                    raise AppError(
                        "Gemini is temporarily unavailable. Please try again later."
                    ) from None
                await asyncio.sleep(delay)
