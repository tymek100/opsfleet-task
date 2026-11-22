"""Provider failures and malformed judgments cannot become successful grades."""

import json
from types import SimpleNamespace

import pytest
from google.genai import types

from evaluation.graders.judge import GeminiJudge, JudgeUnavailable
from evaluation.models import TurnReference
from evaluation.results import TurnRecord
from evaluation.settings import EvaluationSettings


class Client:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self.generate))

    async def generate(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def records():
    return (
        TurnRecord(
            step_id="ask",
            prompt="What can be concluded?",
            status="approved",
            markdown="Consider further analysis.",
            outcome="answer",
        ),
        TurnReference(reference_answer="Consider further analysis."),
    )


async def test_judge_filters_thought_parts_and_settles_actual_usage():
    payload = {
        "facts": [],
        "claims": [
            {
                "span": "s1",
                "label": "NOT_FACTUAL",
                "evidence_ids": [],
                "reason": "Advice",
                "material": False,
            }
        ],
        "criteria": [],
        "response_kind": "substantive",
        "coverage_complete": True,
    }
    client = Client(
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        parts=[
                            types.Part(text="PRIVATE_THOUGHT_CANARY", thought=True),
                            types.Part(text=json.dumps(payload)),
                        ]
                    )
                )
            ],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100,
                candidates_token_count=50,
                thoughts_token_count=20,
                total_token_count=170,
            ),
        )
    )
    judge = GeminiJudge(
        "offline", EvaluationSettings(), max_cost_usd=1, deadline_seconds=10, client=client
    )
    turn, reference = records()
    result = await judge.evaluate(turn, reference, [])
    assert result.claims[0].label == "NOT_FACTUAL"
    assert judge.accounted_usd == pytest.approx((100 * 2 + 70 * 12) / 1e6)
    assert "PRIVATE_THOUGHT_CANARY" not in str(judge.calls)
    assert "tools" not in client.requests[0]


async def test_unknown_usage_retains_reservation_and_never_retries():
    client = Client(TimeoutError("API_KEY_CANARY"))
    judge = GeminiJudge(
        "offline", EvaluationSettings(), max_cost_usd=1, deadline_seconds=10, client=client
    )
    turn, reference = records()
    with pytest.raises(JudgeUnavailable):
        await judge.evaluate(turn, reference, [])
    assert len(client.requests) == 1
    assert judge.accounted_usd > 0
    assert "API_KEY_CANARY" not in str(judge.calls)


async def test_cost_admission_prevents_provider_call():
    client = Client(AssertionError("Should not execute"))
    judge = GeminiJudge(
        "offline", EvaluationSettings(), max_cost_usd=0.000001, deadline_seconds=10, client=client
    )
    turn, reference = records()
    with pytest.raises(JudgeUnavailable, match="budget"):
        await judge.evaluate(turn, reference, [])
    assert not client.requests and judge.accounted_usd == 0


async def test_invalid_schema_is_error_even_with_successful_provider_usage():
    client = Client(
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(parts=[types.Part(text='{"score":1,"approved":true}')])
                )
            ]
        )
    )
    judge = GeminiJudge(
        "offline", EvaluationSettings(), max_cost_usd=1, deadline_seconds=10, client=client
    )
    turn, reference = records()
    with pytest.raises(JudgeUnavailable):
        await judge.evaluate(turn, reference, [])
    assert judge.calls[0]["status"] == "ERROR"


@pytest.mark.parametrize(
    "endpoint",
    ["https://example.org", "http://secret@localhost:6006", "http://127.0.0.1:6006?token=x"],
)
def test_publication_is_local_and_credential_free(endpoint):
    with pytest.raises(ValueError):
        EvaluationSettings(phoenix_url=endpoint)
