"""Script the provider boundary; keep the real ADK loop and tool implementations."""

import json
from collections.abc import AsyncGenerator, Callable

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from retail_agent.evaluator import INSTRUCTION, Evaluation
from retail_agent.model import BoundedGemini


def tool(name: str, **args: object) -> types.Content:
    return types.Content(
        role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]
    )


def query(sql: str, purpose: str = "Answer the requested analysis") -> types.Content:
    return tool("run_analysis", sql=sql, purpose=purpose, definitions="UTC; qualifying item sales.")


def submit(text: str, *evidence: str) -> types.Content:
    return tool("submit_answer", text=text, evidence_ids=list(evidence))


type Reply = types.Content | Exception | Callable[[LlmRequest], types.Content]
type ReviewReply = Evaluation | types.Content | Exception


class Script:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        replies: list[Reply],
        reviews: list[ReviewReply] | None = None,
    ) -> None:
        self.requests: list[LlmRequest] = []
        self.review_requests: list[LlmRequest] = []
        sequence = iter(replies)
        review_sequence = iter(reviews if reviews is not None else [Evaluation(decision="approve")])

        async def generate(
            model: BoundedGemini, request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            del model, stream
            is_review = (
                request.config.model_dump(mode="json").get("system_instruction") == INSTRUCTION
            )
            (self.review_requests if is_review else self.requests).append(
                request.model_copy(
                    update={
                        "contents": [c.model_copy(deep=True) for c in request.contents],
                        "config": request.config.model_copy(deep=True),
                    }
                )
            )
            response = next(review_sequence) if is_review else next(sequence)
            if isinstance(response, Exception):
                raise response
            if isinstance(response, Evaluation):
                content = types.Content(
                    role="model", parts=[types.Part(text=response.model_dump_json())]
                )
            else:
                content = response(request) if callable(response) else response
            yield LlmResponse(content=content)

        monkeypatch.setattr(BoundedGemini, "generate_content_async", generate)

    @property
    def payloads(self) -> str:
        return json.dumps(
            [
                r.model_dump(mode="json", exclude={"tools_dict"})
                for r in [*self.requests, *self.review_requests]
            ]
        )
