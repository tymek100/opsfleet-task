"""One Gemini call. Tool execution belongs to our graph, not the SDK."""

from google import genai
from google.genai import types

from retail_insight.config import Settings
from retail_insight.core.tool import Tool


class GeminiModel:
    def __init__(self, settings: Settings):
        if not settings.gemini_api_key.get_secret_value():
            raise ValueError("Set GEMINI_API_KEY in .env before starting the agent.")
        self.settings = settings
        self.client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=60_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    async def generate(
        self, messages: list[types.Content], instruction: str, tools: list[Tool]
    ) -> types.Content:
        response = await self.client.aio.models.generate_content(
            model=self.settings.gemini_model,
            contents=messages,
            config=types.GenerateContentConfig(
                system_instruction=instruction,
                tools=[types.Tool(function_declarations=[tool.declaration() for tool in tools])]
                if tools
                else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel(self.settings.thinking_level)
                ),
                max_output_tokens=self.settings.max_output_tokens,
            ),
        )
        if not response.candidates or not response.candidates[0].content:
            raise RuntimeError("The model returned no answer.")
        if response.candidates[0].finish_reason != types.FinishReason.STOP:
            raise RuntimeError("The model did not complete its response; try a smaller request.")
        # Keep the original content, including tool-call signatures, for the next call.
        return response.candidates[0].content

    async def close(self):
        await self.client.aio.aclose()
        self.client.close()
