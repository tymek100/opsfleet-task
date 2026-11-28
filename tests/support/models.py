"""Scripted provider boundary; the real LangGraph runner and tools remain under test."""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncGenerator
from typing import Any

from google.genai import types
from pydantic import Field, PrivateAttr

from retail_insight.contracts import REVIEW_CATEGORIES
from retail_insight.runtime.model import BaseLlm, LlmCapabilities, LlmRequest, LlmResponse


def text(value: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=value)])


def calls(*actions: tuple[str, dict]) -> types.Content:
    return types.Content(
        role="model",
        parts=[
            types.Part(function_call=types.FunctionCall(name=name, args=args))
            for name, args in actions
        ],
    )


def finish(markdown: str, evidence: list[str] | None = None, outcome: str = "answer"):
    return calls(
        (
            "finish_answer",
            {
                "markdown": markdown,
                "evidence_ids": evidence or [],
                "outcome": outcome,
            },
        )
    )


def verdict(decision: str = "approve", *, save: bool = False, failed: str = "grounding"):
    return text(
        json.dumps(
            {
                "checks": [
                    {
                        "category": category,
                        "passed": decision == "approve" or category != failed,
                        "finding": "Scripted boundary assertion; not a semantic quality judgment.",
                        "evidence_ids": [],
                    }
                    for category in REVIEW_CATEGORIES
                ],
                "issues": []
                if decision == "approve"
                else [
                    {
                        "category": failed,
                        "message": "Verify the claim using observed evidence.",
                        "evidence_ids": [],
                    }
                ],
                "save_authorized": save,
                "decision": decision,
            }
        )
    )


def usage(**changes):
    return types.GenerateContentResponseUsageMetadata.model_construct(
        **{
            "prompt_token_count": 100,
            "candidates_token_count": 20,
            "thoughts_token_count": 5,
            **changes,
        }
    )


class ScriptedModel(BaseLlm):
    """Capture every request and supply content, streamed events, or failures."""

    model: str = "offline-scripted-provider"
    script: list[Any] = Field(default_factory=list, exclude=True)
    _requests: list[dict] = PrivateAttr(default_factory=list)

    @property
    def requests(self) -> list[dict]:
        return self._requests

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        snapshot = json.loads(llm_request.model_dump_json(exclude={"tools_dict"}))
        snapshot["registered_tools"] = sorted(llm_request.tools_dict)
        index = len(self._requests)
        self._requests.append(snapshot)
        if index >= len(self.script):
            raise AssertionError(f"Unexpected model call {index + 1}")
        step = self.script[index]
        if callable(step):
            step = step(snapshot)
        if inspect.isasyncgen(step):
            async for response in step:
                assert isinstance(response, LlmResponse)
                yield response
            return
        for item in step if isinstance(step, list) else [step]:
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, LlmResponse):
                yield item
            else:
                assert isinstance(item, types.Content)
                yield LlmResponse(content=item, partial=False, usage_metadata=usage())
