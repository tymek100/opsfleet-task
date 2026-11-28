"""Small provider contract shared by production Gemini and offline scripted models."""

from collections.abc import AsyncGenerator
from typing import Any

from google.genai import types
from pydantic import BaseModel, ConfigDict, Field


class LlmCapabilities(BaseModel):
    output_schema_and_tools: bool = True


class LlmRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    model: str = ""
    contents: list[types.Content] = Field(default_factory=list)
    config: types.GenerateContentConfig = Field(default_factory=types.GenerateContentConfig)
    tools_dict: dict[str, Any] = Field(default_factory=dict)

    def append_instructions(self, instructions: list[str]) -> None:
        existing = self.config.system_instruction or ""
        self.config.system_instruction = str(existing) + "\n" + "\n".join(instructions)


class LlmResponse(BaseModel):
    content: types.Content | None = None
    usage_metadata: types.GenerateContentResponseUsageMetadata | None = None
    partial: bool = False
    turn_complete: bool = True
    finish_reason: Any = None
    error_code: str | None = None
    error_message: str | None = None


class BaseLlm(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    model: str

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities()

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        raise NotImplementedError
        yield


class Gemini(BaseLlm):
    client: Any = Field(exclude=True)
    retry_options: Any = None

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        # The graph consumes complete decisions. UI progress is streamed separately.
        response = await self.client.aio.models.generate_content(
            model=self.model, contents=llm_request.contents, config=llm_request.config
        )
        candidate = response.candidates[0] if response.candidates else None
        yield LlmResponse(
            content=candidate.content if candidate else None,
            usage_metadata=response.usage_metadata,
            finish_reason=candidate.finish_reason if candidate else None,
            error_code=None if candidate and candidate.content else "empty_response",
        )
