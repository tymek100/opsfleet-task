"""Judge traces show sanitized requests/results only in explicit evaluation capture."""

import json

import pytest
from google.genai import errors, types
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from evaluation.graders.judge import PROMPT_PATH, GeminiJudge, JudgeUnavailable
from evaluation.settings import EvaluationSettings
from retail_agent.observability import configure_tracing
from tests.evaluation.test_judge_budget import Client, records
from tests.evaluation.test_trajectory import assessment, captured_trial
from tests.evaluation.test_trajectory import response as trajectory_response


def response(*, span="s1"):
    content = {
        "facts": [],
        "claims": [
            {
                "span": span,
                "label": "UNSUPPORTED",
                "evidence_ids": [],
                "reason": "provider-key evidence-content-canary",
            }
        ],
        "criteria": [],
        "response_kind": "substantive",
        "coverage_complete": True,
    }
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    parts=[
                        types.Part(text="private-thought-canary", thought=True),
                        types.Part(text=json.dumps(content)),
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


def observed_events(item):
    return {
        record["event"]: record
        for event in item.events
        if event.name == "retail.observation"
        for record in [json.loads(event.attributes["retail.observation"])]
    }


@pytest.mark.parametrize("mode", ["synthetic", "metadata"])
async def test_judge_summary_usage_and_capture_mode_preserve_privacy(mode):
    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter, mode=mode)
    provider = Client(response())
    judge = GeminiJudge(
        "provider-key",
        EvaluationSettings(),
        max_cost_usd=1,
        deadline_seconds=10,
        client=provider,
    )
    turn, reference = records()
    turn.prompt = "question-content-canary provider-key"
    turn.context = {
        "evidence": "evidence-content-canary",
        "api_key": "nested-secret-canary",
        "parts": [{"thought": True, "text": "nested-thought-canary"}],
    }
    try:
        result = await judge.evaluate(turn, reference, [])
        assert result.claims[0].label == "UNSUPPORTED"
        assert tracing.provider.force_flush(timeout_millis=2000)
    finally:
        tracing.close()
    captured = next(item for item in exporter.get_finished_spans() if item.name == "retail.judge")
    assert captured.attributes is not None
    assert captured.status.status_code == StatusCode.OK  # Execution succeeded; quality did not.
    events = observed_events(captured)
    assert events["judge_result"]["status"] == "completed"
    if mode == "synthetic":
        assert events["judge_input"]["question"] == "question-content-canary [REDACTED]"
        assert events["judge_input"]["step_id"] == turn.step_id
        assert "1 UNSUPPORTED" in events["judge_result"]["summary"]
        request = provider.requests[0]
        shown = json.loads(str(captured.attributes["input.value"]))
        assert shown["messages"] == [
            {"role": "system", "content": PROMPT_PATH.read_text()},
            {"role": "user", "content": request["contents"]},
        ]
        assert (
            shown["generation_config"]["response_json_schema"]
            == request["config"].response_json_schema
        )
        assert captured.attributes["llm.input_messages.0.message.role"] == "system"
        assert captured.attributes["llm.input_messages.1.message.content"] == request["contents"]
        template = str(captured.attributes["llm.prompt_template.template"])
        assert template == f"System:\n{PROMPT_PATH.read_text()}\n\nUser:\n{{{{context}}}}"
        variables = json.loads(str(captured.attributes["llm.prompt_template.variables"]))
        assert variables == {"context": request["contents"]}
        assert template.replace("{{context}}", variables["context"]) == (
            f"System:\n{request['config'].system_instruction}\n\nUser:\n{request['contents']}"
        )
        returned = json.loads(str(captured.attributes["output.value"]))
        assert returned["claims"][0]["span"] == "s1"  # Actual output, before ID resolution.
        assert returned["claims"][0]["reason"] == "[REDACTED] evidence-content-canary"
        assert captured.attributes["output.mime_type"] == "application/json"
        assert (
            captured.attributes["llm.output_messages.0.message.content"]
            == captured.attributes["output.value"]
        )
        assert judge.calls[0]["request"] == shown
        assert captured.context is not None
        assert judge.calls[0]["span_id"] == f"{captured.context.span_id:016x}"
    else:
        assert "question" not in events["judge_input"]
        assert "summary" not in events["judge_result"]
        assert "question-content-canary" not in captured.to_json()
        assert "evidence-content-canary" not in captured.to_json()
        assert "input.value" not in captured.attributes
        assert "output.value" not in captured.attributes
        assert "llm.invocation_parameters" not in captured.attributes
        assert "llm.prompt_template.template" not in captured.attributes
        assert "llm.prompt_template.variables" not in captured.attributes
        assert not any("messages." in key for key in captured.attributes)
    assert captured.attributes["llm.token_count.total"] == 170
    assert captured.attributes["llm.cost.total"] == pytest.approx((100 * 2 + 70 * 12) / 1e6)
    assert captured.attributes["retail.judge_kind"] == "answer"
    serialized = captured.to_json()
    assert all(
        secret not in serialized
        for secret in (
            "provider-key",
            "private-thought-canary",
            "nested-secret-canary",
            "nested-thought-canary",
        )
    )


async def test_invalid_judge_attribution_marks_span_error_after_provider_success():
    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter, mode="synthetic")
    judge = GeminiJudge(
        "provider-key",
        EvaluationSettings(),
        max_cost_usd=1,
        deadline_seconds=10,
        client=Client(response(span="invented-source")),
    )
    turn, reference = records()
    try:
        with pytest.raises(JudgeUnavailable, match="unknown source"):
            await judge.evaluate(turn, reference, [])
        assert tracing.provider.force_flush(timeout_millis=2000)
    finally:
        tracing.close()
    captured = next(item for item in exporter.get_finished_spans() if item.name == "retail.judge")
    assert captured.attributes is not None
    assert captured.status.status_code == StatusCode.ERROR
    event = observed_events(captured)["judge_result"]
    assert event["error_stage"] == "attribution"
    assert "No judgment produced" in event["summary"]
    assert captured.attributes["llm.token_count.total"] == 170
    assert (
        json.loads(str(captured.attributes["output.value"]))["claims"][0]["span"]
        == "invented-source"
    )
    assert "unknown source" in json.loads(str(captured.attributes["metadata"]))["validation_error"]


async def test_judge_provider_error_exposes_http_code_but_not_message_or_reserved_cost():
    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter, mode="synthetic")
    judge = GeminiJudge(
        "provider-key",
        EvaluationSettings(),
        max_cost_usd=1,
        deadline_seconds=10,
        client=Client(
            errors.ClientError(402, {"error": {"message": "provider-key billing-canary"}})
        ),
    )
    turn, reference = records()
    try:
        with pytest.raises(JudgeUnavailable, match="402"):
            await judge.evaluate(turn, reference, [])
        assert tracing.provider.force_flush(timeout_millis=2000)
    finally:
        tracing.close()
    captured = next(item for item in exporter.get_finished_spans() if item.name == "retail.judge")
    assert captured.attributes is not None
    assert captured.status.status_code == StatusCode.ERROR
    event = observed_events(captured)["judge_result"]
    assert event["provider_code"] == 402 and "HTTP 402" in event["summary"]
    assert not any(key.startswith(("llm.cost.", "llm.token_count.")) for key in captured.attributes)
    assert judge.accounted_usd > 0
    assert "billing-canary" not in captured.to_json()
    assert "llm.output_messages.0.message.content" not in captured.attributes
    assert "No judgment produced" in str(captured.attributes["output.value"])


async def test_trajectory_preview_identifies_the_conversation_and_diagnostic_findings():
    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter, mode="synthetic")
    trial = captured_trial()
    judge = GeminiJudge(
        "provider-key",
        EvaluationSettings(),
        max_cost_usd=1,
        deadline_seconds=10,
        client=Client(trajectory_response(assessment(trial, fail=True).model_dump(mode="json"))),
    )
    try:
        await judge.evaluate_trajectory(trial)
        assert tracing.provider.force_flush(timeout_millis=2000)
    finally:
        tracing.close()
    captured = next(item for item in exporter.get_finished_spans() if item.name == "retail.judge")
    events = observed_events(captured)
    assert captured.status.status_code == StatusCode.OK
    assert events["judge_input"]["kind"] == "trajectory"
    assert trial.turns[0].prompt in events["judge_input"]["question"]
    assert "progress: FAIL" in events["judge_result"]["summary"]
    assert captured.attributes is not None
    shown = json.loads(str(captured.attributes["input.value"]))
    assert "untrusted_execution" in json.loads(shown["messages"][1]["content"])
    assert str(captured.attributes["llm.prompt_template.template"]).startswith(
        "System:\n# Agent trajectory evaluation"
    )
    assert json.loads(str(captured.attributes["llm.prompt_template.variables"])) == {
        "context": shown["messages"][1]["content"]
    }
    assert json.loads(str(captured.attributes["output.value"]))["coverage_complete"] is True
    assert "HIDDEN_" not in captured.to_json()


async def test_judge_large_evidence_and_response_are_not_preview_truncated():
    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter, mode="synthetic")
    model_response = response()
    assert model_response.candidates
    content = model_response.candidates[0].content
    assert content and content.parts and content.parts[1].text
    decoded = json.loads(content.parts[1].text)
    decoded["claims"][0]["reason"] = "Evidence review: " + "界" * 25_000
    content.parts[1].text = json.dumps(decoded, ensure_ascii=False)
    provider = Client(model_response)
    judge = GeminiJudge(
        "provider-key",
        EvaluationSettings(),
        max_cost_usd=2,
        deadline_seconds=10,
        client=provider,
    )
    turn, reference = records()
    turn.context = {"evidence": "界" * 25_000}
    try:
        await judge.evaluate(turn, reference, [])
        assert tracing.provider.force_flush(timeout_millis=2000)
    finally:
        tracing.close()
    captured = next(item for item in exporter.get_finished_spans() if item.name == "retail.judge")
    assert captured.attributes is not None
    shown = json.loads(str(captured.attributes["input.value"]))
    assert shown["messages"][1]["content"] == provider.requests[0]["contents"]
    assert json.loads(str(captured.attributes["output.value"])) == decoded
    assert judge.calls[0]["visible_response_truncated"] is False
