"""Single bounded transient retry, charged to the same turn budget."""

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors
from pydantic import PrivateAttr

from retail_agent.budget import Budget
from retail_agent.models import AppError
from retail_agent.observability import Trace


@dataclass
class ModelPacer:
    interval: float
    last_call: float = 0

    async def wait(self, budget: Budget) -> None:
        delay = max(0, self.interval - (time.monotonic() - self.last_call))
        if delay >= budget.remaining():
            raise AppError("Model rate-limit wait exceeds this question's remaining time.")
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
                    emitted = True
                    yield response
                return
            except errors.APIError as exc:
                if emitted or attempt == 1 or exc.code not in (429, 500, 502, 503, 504):
                    raise
                self._trace.emit("model_retry", status=exc.code, attempt=attempt + 2)
                self._budget.model(
                    len(llm_request.model_dump_json(exclude={"tools_dict"}).encode()), 4096
                )
                retry = re.search(
                    r'"retryDelay":\s*"([0-9.]+)s"',
                    json.dumps(exc.details),  # pyright: ignore[reportUnknownMemberType]  # SDK error JSON is untyped.
                )
                delay = max(1.0, float(retry.group(1)) + 1 if retry else 1.0)
                if delay > 60 or delay >= self._budget.remaining():
                    raise AppError(
                        "Provider rate limit exceeds the remaining deadline. Try again later."
                    ) from None
                await asyncio.sleep(delay)
