"""Google Gemini client shared by agents and independent evaluation judges.

The existing API key selects the Gemini Developer API. BigQuery uses ADC and
GOOGLE_CLOUD_PROJECT separately; a Foundry endpoint never changes either route.
"""

from google import genai
from google.genai import types


class GCPConnector:
    @staticmethod
    def model_client(api_key: str, *, timeout_seconds: float) -> genai.Client:
        if not api_key:
            raise ValueError("Configure GEMINI_API_KEY for the Google model connection")
        return genai.Client(
            api_key=api_key,
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
