import json

import pytest
from google.genai import types

from retail_insight.agents.retail.agent import RetailAnalyst
from retail_insight.observability import tracing
from retail_insight.runtime.model import LlmResponse
from tests.support.models import ScriptedModel, finish, verdict


@pytest.fixture
def capture():
    from tests.support.tracing import MemoryClient
    exporter = MemoryClient()
    session = tracing.configure_tracing(exporter=exporter, mode="metadata")
    yield session, exporter.spans
    session.close()


async def test_private_capture_retains_nested_operations_without_payloads(settings, capture):
    _session, runs = capture
    model = ScriptedModel(script=[finish("answer-canary"), finish("answer-canary")])
    app = RetailAnalyst(
        settings, model=model, reviewer_model=ScriptedModel(script=[verdict(), verdict()])
    )
    try:
        assert (await app.ask("question-canary")).status == "approved"
        assert (await app.ask("question-canary")).status == "approved"
    finally:
        app.reports.close()
    roots = [r for r in runs if r.name == "retail.prompt"]
    assert len(roots) == 2 and roots[0].context.trace_id != roots[1].context.trace_id
    assert any(r.name.endswith(".review") for r in runs)
    assert any(r.name.endswith(".tools") for r in runs) is False
    assert all(r.parent for r in runs if r.name == "retail.provider_attempt")
    payload = json.dumps(
        [r.to_json() for r in runs],
        default=str,
    )
    assert "question-canary" not in payload and "answer-canary" not in payload


async def test_opted_in_capture_removes_thoughts_and_secrets(settings, capture):
    session, runs = capture
    session.mode = "synthetic"
    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(text="hidden-thought-canary", thought=True),
                *(finish("approved text").parts or []),
            ],
        )
    )
    app = RetailAnalyst(
        settings,
        model=ScriptedModel(script=[response]),
        reviewer_model=ScriptedModel(script=[verdict()]),
        observation_mode="synthetic",
    )
    try:
        assert (await app.ask("visible question")).status == "approved"
    finally:
        app.reports.close()
    payload = json.dumps([r.to_json() for r in runs], default=str)
    assert "visible question" in payload and "approved text" in payload
    assert "hidden-thought-canary" not in payload
    assert "offline-placeholder" not in payload


def test_recursive_redaction_and_metadata_allowlist():
    raw = {
        "event": "tool_observation",
        "name": "query",
        "result": {"rows": [{"x": 1}], "api_key": "secret"},
        "thought_signature": "opaque",
    }
    safe = tracing.observation(raw, mode="synthetic")
    assert "secret" not in json.dumps(safe) and "opaque" not in json.dumps(safe)
    metadata = tracing.observation(raw, mode="metadata")
    assert metadata["row_count"] == 1 and "result" not in metadata
