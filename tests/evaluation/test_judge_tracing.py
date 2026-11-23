"""Judge traces distinguish completed assessments from errors without exporting evidence."""

import json

import pytest
from google.genai import errors, types
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from evaluation.graders.judge import GeminiJudge, JudgeUnavailable
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
    judge = GeminiJudge(
        "provider-key",
        EvaluationSettings(),
        max_cost_usd=1,
        deadline_seconds=10,
        client=Client(response()),
    )
    turn, reference = records()
    turn.prompt = "question-content-canary provider-key"
    turn.context = {"evidence": "evidence-content-canary"}
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
    else:
        assert "question" not in events["judge_input"]
        assert "summary" not in events["judge_result"]
        assert "question-content-canary" not in captured.to_json()
    assert captured.attributes["llm.token_count.total"] == 170
    assert captured.attributes["llm.cost.total"] == pytest.approx((100 * 2 + 70 * 12) / 1e6)
    assert captured.attributes["retail.judge_kind"] == "answer"
    serialized = captured.to_json()
    assert all(
        secret not in serialized
        for secret in (
            "provider-key",
            "private-thought-canary",
            "evidence-content-canary",
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
    assert "invented-source" not in captured.to_json()


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
    assert "HIDDEN_" not in captured.to_json()
