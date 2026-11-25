"""ADK model adapter with shared accounting, bounded retries and safe errors."""

import asyncio
import base64
import json
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from typing import cast

import httpx
from google import genai
from google.adk.models import BaseLlm, Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types
from opentelemetry.trace import Span, Status, StatusCode
from pydantic import BaseModel, PrivateAttr

from retail_insight.config import Settings
from retail_insight.integrations.phoenix.tracing import detached_span, prompt_attributes
from retail_insight.runtime.budget import Budget
from retail_insight.runtime.privacy import screen
from retail_insight.runtime.prompts import PromptSpec


class ProviderUnavailable(Exception):
    pass


def _provider_event(current: Span, event: str, **fields) -> None:
    """Fixed operational summaries only; never include provider payloads or errors."""
    current.add_event(
        "retail.observation", {"retail.observation": json.dumps({"event": event, **fields})}
    )


def _provider_result(current: Span, role: str, error: BaseException | None = None) -> None:
    if not current.is_recording():
        return
    fields: dict[str, str | int] = {"role": role, "status": "ERROR" if error else "completed"}
    summary = "Model response received."
    if error is not None:
        summary = "Provider request failed."
        if isinstance(error, errors.APIError):
            current.set_attribute("retail.provider_code", error.code)
            fields["provider_code"] = error.code
            summary = f"Provider request failed (HTTP {error.code})."
        elif isinstance(error, (TimeoutError, httpx.TimeoutException)):
            summary = "Provider request timed out."
        elif isinstance(error, asyncio.CancelledError):
            summary = "Provider request cancelled."
    current.set_attribute("retail.status", fields["status"])
    current.set_status(Status(StatusCode.ERROR, summary) if error else Status(StatusCode.OK))
    _provider_event(current, "provider_result", **fields, summary=summary)


def _provider_usage(current: Span, counts: tuple[int, int, int], settings: Settings) -> None:
    if not current.is_recording():
        return
    inputs, outputs, thinking = counts
    prompt_cost = inputs * settings.input_usd_per_million / 1e6
    completion_cost = (outputs + thinking) * settings.output_usd_per_million / 1e6
    for name, value in {
        "llm.token_count.prompt": inputs,
        "llm.token_count.completion": outputs + thinking,
        "llm.token_count.total": sum(counts),
        "llm.cost.prompt": prompt_cost,
        "llm.cost.completion": completion_cost,
        "llm.cost.total": prompt_cost + completion_cost,
    }.items():
        current.set_attribute(name, value)


def _usage_counts(
    usage: types.GenerateContentResponseUsageMetadata | None,
) -> tuple[int, int, int] | None:
    """Accept a complete metering snapshot; unknown usage keeps its full reservation."""
    if usage is None:
        return None
    counts = (
        usage.prompt_token_count,
        usage.candidates_token_count,
        usage.thoughts_token_count if usage.thoughts_token_count is not None else 0,
        usage.tool_use_prompt_token_count if usage.tool_use_prompt_token_count is not None else 0,
    )
    if any(type(count) is not int or count < 0 for count in counts):
        return None
    prompt, output, thinking, tool_input = cast(tuple[int, int, int, int], counts)
    if usage.total_token_count is not None and (
        type(usage.total_token_count) is not int
        or usage.total_token_count != prompt + output + thinking + tool_input
    ):
        return None
    # Cached tokens are already part of prompt_token_count. Use full configured
    # input pricing until a provider-specific cache discount is configured.
    return prompt + tool_input, output, thinking


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
    _prompt: PromptSpec | None = PrivateAttr(default=None)
    _screener: Callable[[str], str] = PrivateAttr()

    def bind(
        self,
        budget: Budget,
        emit: Callable,
        *,
        reviewer: bool = False,
        prompt: PromptSpec | None = None,
        screener: Callable[[str], str] = screen,
    ) -> "AccountedModel":
        self._budget, self._emit, self._reviewer = budget, emit, reviewer
        self._prompt = prompt
        self._screener = screener
        return self

    @property
    def capabilities(self):
        return self.delegate.capabilities

    def _settle_usage(
        self, reservation: int, usage: types.GenerateContentResponseUsageMetadata | None
    ) -> None:
        counts = _usage_counts(usage)
        if counts is None:
            return
        input_tokens, output_tokens, thinking_tokens = counts
        if self._budget.settle_model(
            reservation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
        ):
            self._emit(
                "model_usage",
                role="reviewer" if self._reviewer else "analyst",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                thinking_tokens=thinking_tokens,
                spent_usd=round(self._budget.spent_usd, 6),
                reserved_usd=round(self._budget.reserved_usd, 6),
            )

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
                f"including final review; ${self._budget.work_available_usd:.3f} available "
                "for further work after protecting review. Finish with sufficient evidence "
                "rather than exhaust it."
            )
            llm_request.append_instructions([hint])
        encoded = request_json(llm_request)
        self._screener(encoded)
        output_limit = (
            llm_request.config.max_output_tokens or self._budget.settings.max_output_tokens
        )
        for attempt in range(2):
            reservation = self._budget.model(
                len(encoded.encode()), output_limit, reviewer=self._reviewer
            )
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
            last_usage = None
            complete_response = False
            response_failed = False
            try:
                with detached_span(
                    "retail.provider_attempt",
                    **{
                        "openinference.span.kind": "LLM",
                        "retail.role": role,
                        "retail.attempt": attempt + 1,
                        "retail.provider_reservation": reservation,
                        "llm.model_name": self.model,
                        **(prompt_attributes(self._prompt) if self._prompt else {}),
                    },
                ) as provider_span:
                    _provider_event(provider_span, "provider_input", role=role)
                    try:
                        async with aclosing(
                            self.delegate.generate_content_async(llm_request, stream)
                        ) as responses:
                            while True:
                                try:
                                    # Time only provider IO. ADK runs tools, including
                                    # the completion reviewer, while suspended at yield.
                                    # Their own budgets govern that work and must retain
                                    # the time explicitly reserved for review.
                                    async with asyncio.timeout(
                                        self._budget.work_remaining(
                                            reviewer=self._reviewer or complete_response
                                        )
                                    ):
                                        response = await anext(responses)
                                except StopAsyncIteration:
                                    break
                                complete_response = response.partial is not True
                                response_failed = bool(response.error_code)
                                last_usage = response.usage_metadata if complete_response else None
                                if complete_response and (
                                    not stream or response.finish_reason or response.turn_complete
                                ):
                                    # ADK executes tools (including the reviewer) while
                                    # suspended at yield, so refund completed usage first.
                                    self._settle_usage(reservation, last_usage)
                                counts = _usage_counts(last_usage)
                                if counts is not None:
                                    _provider_usage(provider_span, counts, self._budget.settings)
                                if (
                                    complete_response
                                    and (
                                        not stream
                                        or response.finish_reason
                                        or response.turn_complete
                                    )
                                    and provider_span.is_recording()
                                ):
                                    # ADK can run tools while this generator is suspended.
                                    # Provider latency ends when its complete response arrives.
                                    _provider_result(
                                        provider_span,
                                        role,
                                        ProviderUnavailable() if response_failed else None,
                                    )
                                    provider_span.end()
                                emitted = True
                                yield response
                                if complete_response and (
                                    not stream or response.finish_reason or response.turn_complete
                                ):
                                    break
                        if complete_response:
                            # Streaming metadata is cumulative, not an increment per chunk.
                            # Legacy streams may mark completion only through exhaustion.
                            self._settle_usage(reservation, last_usage)
                            _provider_result(
                                provider_span,
                                role,
                                ProviderUnavailable() if response_failed else None,
                            )
                        else:
                            _provider_result(provider_span, role, ProviderUnavailable())
                    except BaseException as exc:
                        _provider_result(provider_span, role, exc)
                        raise
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
