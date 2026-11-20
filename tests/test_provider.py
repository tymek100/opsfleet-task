"""Real SDK payload shapes that scripted model content alone does not exercise."""

import json

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from retail_agent.contracts import Review
from retail_agent.provider import request_json


def test_accounting_serializes_sdk_thought_signatures_and_review_schema():
    request = LlmRequest(
        model="test",
        contents=[
            types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(name="describe_data", args={}),
                        thought_signature=b"\xff\x00signature",
                    )
                ],
            )
        ],
        config=types.GenerateContentConfig(response_schema=Review),
    )
    payload = json.loads(request_json(request))
    assert payload["config"]["response_schema"]["properties"]["decision"]
    assert payload["contents"][0]["parts"][0]["thought_signature"]
    assert request.contents[0].parts is not None
    assert request.contents[0].parts[0].thought_signature == b"\xff\x00signature"
