"""Provider span status, metered costs, and safe operational summaries."""

import json

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from retail_insight.integrations.phoenix.tracing import configure_tracing
from retail_insight.runtime.budget import Budget
from retail_insight.runtime.provider import ProviderUnavailable
from tests.integration.test_provider import collect, metered, request
from tests.support.models import ScriptedModel, text, usage


@pytest.fixture
def provider_capture():
    exporter = InMemorySpanExporter()
    session = configure_tracing(exporter=exporter, mode="synthetic")
    try:
        yield session, exporter
    finally:
        session.close()


def attempts(session, exporter):
    assert session.provider.force_flush(timeout_millis=2000)
    return [s for s in exporter.get_finished_spans() if s.name == "retail.provider_attempt"]


async def test_success_is_complete_before_consumer_runs_and_cost_matches_usage(
    settings, provider_capture
):
    session, exporter = provider_capture
    budget = Budget(settings)
    model = metered(ScriptedModel(script=[text("response-content-canary")]), budget, [])
    async for _ in model.generate_content_async(request("question-content-canary")):
        # ADK may start a nested reviewer while the provider generator is suspended here.
        spans = attempts(session, exporter)
        assert len(spans) == 1 and spans[0].end_time is not None
        current = spans[0]
        assert current.status.status_code == StatusCode.OK
        assert current.attributes["llm.cost.prompt"] == pytest.approx(0.0002)
        assert current.attributes["llm.cost.completion"] == pytest.approx(0.0003)
        assert current.attributes["llm.cost.total"] == pytest.approx(budget.spent_usd)
    spans = attempts(session, exporter)
    assert len(spans) == 1
    payload = spans[0].to_json()
    assert "response-content-canary" not in payload and "question-content-canary" not in payload
    events = [json.loads(e.attributes["retail.observation"]) for e in spans[0].events]
    assert events[-1]["event"] == "provider_result"
    assert events[-1]["status"] == "completed"


@pytest.mark.parametrize("metadata", [None, usage(total_token_count=999)])
async def test_unknown_usage_is_not_displayed_as_reservation_or_zero_cost(
    settings, provider_capture, metadata
):
    session, exporter = provider_capture
    budget = Budget(settings)
    model = metered(
        ScriptedModel(script=[LlmResponse(content=text("Complete"), usage_metadata=metadata)]),
        budget,
        [],
    )
    await collect(model)
    current = attempts(session, exporter)[0]
    assert current.status.status_code == StatusCode.OK
    assert budget.reserved_usd > 0 and budget.spent_usd == 0
    assert not any(k.startswith("llm.cost.") for k in current.attributes)


async def test_http_failure_has_safe_status_and_code_without_fabricated_usage(
    settings, provider_capture
):
    session, exporter = provider_capture
    failure = errors.ClientError(402, {"error": {"message": "private-billing-error-canary"}})
    budget = Budget(settings)
    model = metered(ScriptedModel(script=[failure]), budget, [])
    with pytest.raises(ProviderUnavailable):
        await collect(model)
    spans = attempts(session, exporter)
    assert len(spans) == 1
    current = spans[0]
    assert current.status.status_code == StatusCode.ERROR
    assert current.attributes["retail.provider_code"] == 402
    assert not any(k.startswith("llm.cost.") for k in current.attributes)
    assert "private-billing-error-canary" not in current.to_json()
    events = [json.loads(e.attributes["retail.observation"]) for e in current.events]
    assert events[-1]["provider_code"] == 402
    assert events[-1]["summary"] == "Provider request failed (HTTP 402)."


async def test_returned_error_response_is_not_marked_as_success(settings, provider_capture):
    session, exporter = provider_capture
    response = LlmResponse(error_code="BLOCKED", error_message="private-error-message-canary")
    model = metered(ScriptedModel(script=[response]), Budget(settings), [])
    await collect(model)
    current = attempts(session, exporter)[0]
    assert current.status.status_code == StatusCode.ERROR
    assert "private-error-message-canary" not in current.to_json()
    assert not any(k.startswith("llm.cost.") for k in current.attributes)


async def test_stream_duplicate_final_metadata_does_not_duplicate_reported_cost(
    settings, provider_capture
):
    session, exporter = provider_capture
    budget = Budget(settings)
    final = usage(prompt_token_count=130, candidates_token_count=40, thoughts_token_count=10)
    model = metered(
        ScriptedModel(
            script=[
                [
                    LlmResponse(
                        content=text("partial-content-canary"), partial=True, usage_metadata=usage()
                    ),
                    LlmResponse(
                        content=text("complete-content-canary"),
                        partial=False,
                        turn_complete=True,
                        usage_metadata=final,
                    ),
                    LlmResponse(
                        content=types.Content(role="model", parts=[]),
                        partial=False,
                        turn_complete=True,
                        usage_metadata=final,
                    ),
                ]
            ]
        ),
        budget,
        [],
    )
    await collect(model, stream=True)
    spans = attempts(session, exporter)
    assert len(spans) == 1
    assert spans[0].attributes["llm.token_count.total"] == 180
    assert spans[0].attributes["llm.cost.total"] == pytest.approx(0.00086)
    assert spans[0].attributes["llm.cost.total"] == pytest.approx(budget.spent_usd)
