"""ADK model adapter with shared accounting, bounded retries and safe errors."""

import asyncio
import base64
import json
import time
from collections.abc import AsyncGenerator, Callable

import httpx
from google import genai
from google.adk.models import BaseLlm, Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types
from pydantic import BaseModel, PrivateAttr

from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.privacy import screen


class ProviderUnavailable(Exception):
    pass


def request_json(request: LlmRequest) -> str:
    def schema(value):
        if isinstance(value, bytes):
            return base64.b64encode(value).decode("ascii")
        if isinstance(value, type) and issubclass(value, BaseModel):
            return value.model_json_schema()
        raise TypeError("Unsupported model request payload")

    return json.dumps(
        request.model_dump(exclude={"tools_dict"}), default=schema, ensure_ascii=False
    )


def make_gemini(settings: Settings) -> Gemini:
    if not settings.gemini_api_key.get_secret_value():
        raise ProviderUnavailable("Configure GEMINI_API_KEY before running the analyst.")
    client = genai.Client(
        api_key=settings.gemini_api_key.get_secret_value(),
        vertexai=False,
        http_options=types.HttpOptions(
            timeout=int(settings.turn_timeout_seconds * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    return Gemini(
        model=settings.gemini_model, client=client, retry_options=types.HttpRetryOptions(attempts=1)
    )


class AccountedModel(BaseLlm):
    delegate: BaseLlm
    _budget: Budget = PrivateAttr()
    _reviewer: bool = PrivateAttr(default=False)
    _emit: Callable = PrivateAttr()

    def bind(self, budget: Budget, emit: Callable, *, reviewer: bool = False) -> "AccountedModel":
        self._budget, self._emit, self._reviewer = budget, emit, reviewer
        return self

    @property
    def capabilities(self):
        return self.delegate.capabilities

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        role = "reviewer" if self._reviewer else "analyst"
        if not self._reviewer:
            hint = (
                f"Remaining shared allowance: {self._budget.remaining():.0f}s; "
                f"{self._budget.settings.max_model_calls - self._budget.model_calls} model calls "
                "including final review. Finish with sufficient evidence rather than exhaust it."
            )
            llm_request.append_instructions([hint])
        encoded = request_json(llm_request)
        screen(encoded)
        output_limit = (
            llm_request.config.max_output_tokens or self._budget.settings.max_output_tokens
        )
        for attempt in range(2):
            self._budget.model(len(encoded.encode()), output_limit, reviewer=self._reviewer)
            delay = max(
                0,
                self._budget.settings.model_min_interval_seconds
                - (time.monotonic() - self._budget.last_model_at),
            )
            if delay:
                await asyncio.sleep(
                    min(delay, self._budget.work_remaining(reviewer=self._reviewer))
                )
            self._budget.last_model_at = time.monotonic()
            self._emit("model_call", role=role, attempt=attempt + 1)
            emitted = False
            try:
                async with asyncio.timeout(self._budget.work_remaining(reviewer=self._reviewer)):
                    async for response in self.delegate.generate_content_async(llm_request, stream):
                        if response.usage_metadata:
                            usage = response.usage_metadata
                            self._budget.input_tokens += usage.prompt_token_count or 0
                            self._budget.output_tokens += usage.candidates_token_count or 0
                            self._budget.thinking_tokens += usage.thoughts_token_count or 0
                        emitted = True
                        yield response
                return
            except (errors.APIError, httpx.NetworkError, httpx.TimeoutException) as exc:
                retryable = not isinstance(exc, errors.APIError) or exc.code in (
                    429,
                    500,
                    502,
                    503,
                    504,
                )
                code = exc.code if isinstance(exc, errors.APIError) else type(exc).__name__
                self._emit("provider_failure", role=role, code=code, retryable=retryable)
                if emitted or attempt or not retryable or self._budget.remaining() < 3:
                    raise ProviderUnavailable(
                        "The model service could not complete this request."
                    ) from None
                await asyncio.sleep(1)
