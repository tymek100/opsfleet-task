"""Check Phoenix's actual OTLP storage of judge messages without paid model calls."""

import json
import time
from uuid import uuid4

import httpx
import pytest

from evaluation.graders.judge import PROMPT_PATH, GeminiJudge
from evaluation.reporting.phoenix import client_for
from evaluation.settings import EvaluationSettings
from retail_agent.observability import configure_tracing
from tests.evaluation.test_judge_budget import Client, records
from tests.evaluation.test_judge_tracing import response

pytestmark = [pytest.mark.phoenix, pytest.mark.enable_socket]


async def test_collector_keeps_system_user_and_full_judge_response(phoenix_url):
    project = "judge-messages-" + uuid4().hex
    config = EvaluationSettings(phoenix_url=phoenix_url)
    client = client_for(config)
    provider = Client(response())
    judge = GeminiJudge(
        "provider-key", config, max_cost_usd=2, deadline_seconds=20, client=provider
    )
    turn, reference = records()
    turn.context = {"evidence": "界" * 25_000, "api_key": "credential-canary"}
    tracing = configure_tracing(phoenix_url + "/v1/traces", project=project, mode="synthetic")
    try:
        await judge.evaluate(turn, reference, [])
        assert tracing.provider.force_flush(timeout_millis=2000)
    finally:
        assert tracing.close()
    spans = []
    for _ in range(30):
        try:
            spans = client.spans.get_spans(project_identifier=project, limit=5)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
        if spans:
            break
        time.sleep(0.1)
    assert len(spans) == 1
    captured = spans[0]
    attrs = captured.get("attributes")
    assert attrs is not None
    assert attrs["llm.input_messages.0.message.role"] == "system"
    assert attrs["llm.input_messages.0.message.content"] == PROMPT_PATH.read_text()
    assert attrs["llm.input_messages.1.message.role"] == "user"
    assert attrs["llm.input_messages.1.message.content"] == provider.requests[0]["contents"]
    template = attrs["llm.prompt_template.template"]
    # Phoenix parses the OTLP JSON variable map and flattens it in its REST response.
    variables = {"context": attrs["llm.prompt_template.variables.context"]}
    assert template == f"System:\n{PROMPT_PATH.read_text()}\n\nUser:\n{{{{context}}}}"
    assert variables == {"context": provider.requests[0]["contents"]}
    assert template.replace("{{context}}", variables["context"]) == (
        f"System:\n{PROMPT_PATH.read_text()}\n\nUser:\n{provider.requests[0]['contents']}"
    )
    assert json.loads(attrs["input.value"]) == judge.calls[0]["request"]
    assert json.loads(attrs["llm.invocation_parameters"])["response_json_schema"] == (
        provider.requests[0]["config"].response_json_schema
    )
    assert attrs["output.value"] == judge.calls[0]["visible_response"]
    assert attrs["llm.output_messages.0.message.content"] == attrs["output.value"]
    assert json.loads(attrs["output.value"])["claims"][0]["label"] == "UNSUPPORTED"
    assert captured["status_code"] == "OK"
    assert all(
        secret not in json.dumps(captured)
        for secret in ("provider-key", "credential-canary", "private-thought-canary")
    )
