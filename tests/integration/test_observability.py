"""Trace isolation and capture privacy, with the real ADK runner and no network."""

import json
import threading
import time
from datetime import UTC, datetime

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

from retail_agent.contracts import DEMO_USERS
from retail_agent.observability import configure_tracing, record_observation, span, trace_context
from retail_agent.runtime import Analyst
from tests.support.models import ScriptedModel, calls, finish, verdict


@pytest.fixture
def capture():
    exporter = InMemorySpanExporter()
    session = configure_tracing(exporter=exporter)
    yield session, exporter
    session.close()


async def test_two_turns_have_separate_roots_and_shared_session_without_payloads(settings, capture):
    session, exporter = capture
    assert configure_tracing(exporter=exporter) is session
    question, answer, thought = "question-content-canary", "answer-content-canary", "thought-canary"
    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(text=thought, thought=True),
                *(finish(answer, outcome="clarification").parts or []),
            ],
        )
    )
    analyst = Analyst(
        settings,
        DEMO_USERS["alice"],
        model=ScriptedModel(script=[response, response]),
        reviewer_model=ScriptedModel(script=[verdict(), verdict()]),
    )
    try:
        first, second = await analyst.ask(question), await analyst.ask(question)
        assert first.status == second.status == "approved"
        assert first.usage["model_calls"] == second.usage["model_calls"] == 2
    finally:
        analyst.reports.close()
    assert session.provider.force_flush(timeout_millis=2000)
    spans = exporter.get_finished_spans()
    roots = [item for item in spans if item.name == "retail.prompt"]
    assert len(roots) == 2 and len({item.context.trace_id for item in roots}) == 2
    assert {item.attributes["session.id"] for item in roots} == {analyst.conversation_id}
    assert len({item.attributes["retail.turn_id"] for item in roots}) == 2
    for root in roots:
        attempts = [
            item
            for item in spans
            if item.name == "retail.provider_attempt"
            and item.context.trace_id == root.context.trace_id
        ]
        assert {item.attributes["retail.role"] for item in attempts} == {"analyst", "reviewer"}
        assert len(attempts) == 2
        analyst_attempt = next(
            item for item in attempts if item.attributes["retail.role"] == "analyst"
        )
        reviewer_attempt = next(
            item for item in attempts if item.attributes["retail.role"] == "reviewer"
        )
        assert analyst_attempt.end_time <= reviewer_attempt.start_time
        assert reviewer_attempt.parent.span_id != analyst_attempt.context.span_id
    serialized = "".join(item.to_json() for item in spans)
    assert all(
        canary not in serialized for canary in [question, answer, thought, "offline-placeholder"]
    )
    assert not [
        item
        for item in spans
        if item.name != "retail.provider_attempt" and "llm.token_count.total" in item.attributes
    ]


def test_export_policy_scrubs_custom_attributes_resources_exception_events_and_status(capture):
    session, exporter = capture
    with span("untrusted-name-canary") as current:
        current.set_attribute("input.value", "raw-input-canary")
        current.set_attribute("credential", "credential-canary")
        current.record_exception(RuntimeError("exception-canary"))
        current.set_status(Status(StatusCode.ERROR, "status-description-canary"))
        current.add_event("raw-event-canary", {"value": "event-payload-canary"})
        record_observation(
            {"event": "initial_context", "context": {"raw": "raw-question-canary"}}, "synthetic"
        )
    session.provider.force_flush(timeout_millis=2000)
    serialized = "".join(item.to_json() for item in exporter.get_finished_spans())
    assert "canary" not in serialized


async def test_synthetic_observer_records_visible_evidence_and_exact_review_candidate(settings):
    records = []
    fixed = datetime(2026, 4, 1, tzinfo=UTC)
    sql = "SELECT product_id, product_name FROM products ORDER BY product_id"
    final = "Product results are available [E1]."
    app = Analyst(
        settings,
        DEMO_USERS["alice"],
        observer=records.append,
        observation_mode="synthetic",
        clock=lambda: fixed,
        model=ScriptedModel(
            script=[
                calls(("query_data", {"sql": sql, "purpose": "Inspect products"})),
                finish(final, ["E1"]),
            ]
        ),
        reviewer_model=ScriptedModel(script=[verdict()]),
    )
    try:
        result = await app.ask("List our products.")
        assert result.status == "approved" and app.observer_errors == 0
        context = next(item for item in records if item["event"] == "initial_context")
        assert context["context"]["today_utc"] == "2026-04-01"
        observation = next(item for item in records if item["event"] == "tool_observation")
        assert observation["name"] == "query_data"
        assert observation["result"]["rows"] == result.evidence[0]["rows"][:20]
        assert observation["result"]["queried_at"] == fixed.isoformat()
        candidate = next(item for item in records if item["event"] == "answer_candidate")
        assert candidate["candidate"] == {
            "markdown": final,
            "evidence_ids": ["E1"],
            "outcome": "answer",
        }
        assert candidate["conversation"] == []
        assert (
            next(item for item in records if item["event"] == "review_result")["review"]["decision"]
            == "approve"
        )
        assert records[-1]["event"] == "turn_result"
        assert records[-1]["result"]["answer"]["markdown"] == final
        observation["result"]["rows"].clear()
        assert app.results["E1"]["rows"]  # Snapshots cannot mutate runtime evidence.
    finally:
        app.reports.close()


async def test_synthetic_capture_omits_delete_tokens_and_known_secrets(settings):
    records = []
    app = Analyst(
        settings,
        DEMO_USERS["alice"],
        observer=records.append,
        observation_mode="synthetic",
        model=ScriptedModel(
            script=[
                calls(("preview_report_deletion", {"query": "Quarterly"})),
                finish("Confirm deletion in the CLI."),
            ]
        ),
        reviewer_model=ScriptedModel(script=[verdict()]),
    )
    try:
        app.reports.save("alice", "Quarterly", "Saved result", [], "A1")
        result = await app.ask("Delete my Quarterly report.")
        assert result.deletion_preview is not None
        token = result.deletion_preview["token"]
        app.observe(
            "test",
            data={
                "api_key": "private-key-canary",
                "nested": [
                    {"thought": True, "text": "hidden-thought-canary"},
                    {"text": "offline-placeholder /confirm sensitive-token"},
                ],
            },
        )
        serialized = json.dumps(records)
        assert all(
            value not in serialized
            for value in [
                token,
                "private-key-canary",
                "hidden-thought-canary",
                "offline-placeholder",
                "sensitive-token",
            ]
        )
    finally:
        app.reports.close()


async def test_phoenix_prompt_preview_has_exact_answer_and_evaluation_context(settings):
    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter, mode="synthetic")
    app = Analyst(
        settings,
        DEMO_USERS["alice"],
        observation_mode="synthetic",
        model=ScriptedModel(script=[finish("Which quarter?", outcome="clarification")]),
        reviewer_model=ScriptedModel(script=[verdict()]),
    )
    try:
        with trace_context(
            run_id="manual-recheck-test", case_id="scenario-14", step_id="turn-1", phase="recheck"
        ):
            await app.ask("Describe sales. offline-placeholder")
        assert tracing.provider.force_flush(timeout_millis=2000)
        root = next(s for s in exporter.get_finished_spans() if s.name == "retail.prompt")
        assert root.attributes is not None
        assert root.attributes["input.value"] == "Describe sales. [REDACTED]"
        assert root.attributes["output.value"] == "Which quarter?"
        assert root.status.status_code == StatusCode.OK
        metadata = json.loads(str(root.attributes["metadata"]))
        assert metadata["case_id"] == "scenario-14" and metadata["turn"] == "Initial question"
        assert (
            metadata["run_id"] == "manual-recheck-test"
            and metadata["execution_status"] == "approved"
        )
        with span("retail.prompt"):
            pass
        assert tracing.provider.force_flush(timeout_millis=2000)
        last = exporter.get_finished_spans()[-1]
        assert last.attributes is not None
        assert "case_id" not in json.loads(str(last.attributes["metadata"]))
    finally:
        app.reports.close()
        tracing.close()


async def test_phoenix_provider_outage_shows_question_and_error_without_fabricated_answer(settings):
    from google.genai import errors

    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter, mode="synthetic")
    error = errors.ClientError(
        402, {"error": {"message": "private-provider-error", "status": "RESOURCE_EXHAUSTED"}}
    )
    app = Analyst(
        settings,
        DEMO_USERS["alice"],
        observation_mode="synthetic",
        model=ScriptedModel(script=[error]),
        reviewer_model=ScriptedModel(script=[]),
    )
    try:
        result = await app.ask("Show Q1 revenue.")
        assert result.answer is None and result.status == "unavailable"
        assert tracing.provider.force_flush(timeout_millis=2000)
        root = next(s for s in exporter.get_finished_spans() if s.name == "retail.prompt")
        assert root.attributes is not None
        assert root.attributes["input.value"] == "Show Q1 revenue."
        assert "No answer generated" in str(root.attributes["output.value"])
        assert "HTTP 402" in str(root.attributes["output.value"])
        assert root.status.status_code == StatusCode.ERROR
        assert "private-provider-error" not in root.to_json()
    finally:
        app.reports.close()
        tracing.close()


def test_synthetic_preview_does_not_promote_automatic_raw_payloads():
    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter, mode="synthetic")
    try:
        with span("retail.prompt") as current:
            current.set_attribute("input.value", "raw-secret-canary")
            current.set_attribute("metadata", '{"private":"raw-secret-canary"}')
        assert tracing.provider.force_flush(timeout_millis=2000)
        assert "raw-secret-canary" not in exporter.get_finished_spans()[0].to_json()
    finally:
        tracing.close()


def test_explicit_execution_error_cannot_be_overridden_by_approved_observation():
    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter, mode="synthetic")
    try:
        with span("retail.prompt") as current:
            record_observation(
                {
                    "event": "turn_result",
                    "result": {"status": "approved", "answer": {"markdown": "Approved answer."}},
                },
                mode="synthetic",
            )
            current.set_status(Status(StatusCode.ERROR, "unsafe-error-details"))
        assert tracing.provider.force_flush(timeout_millis=2000)
        root = exporter.get_finished_spans()[0]
        assert root.status.status_code == StatusCode.ERROR
        assert "unsafe-error-details" not in root.to_json()
    finally:
        tracing.close()


async def test_preview_export_failure_does_not_abort_answer(settings, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("Collector preview unavailable")

    monkeypatch.setattr("retail_agent.runtime.record_observation", broken)
    app = Analyst(
        settings,
        DEMO_USERS["alice"],
        model=ScriptedModel(script=[finish("Which quarter?", outcome="clarification")]),
        reviewer_model=ScriptedModel(script=[verdict()]),
    )
    try:
        result = await app.ask("Describe sales.")
        assert result.status == "approved" and app.observer_errors > 0
    finally:
        app.reports.close()


async def test_metadata_observer_remains_private_inside_synthetic_session(settings):
    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter, mode="synthetic")
    app = Analyst(
        settings,
        DEMO_USERS["alice"],
        observation_mode="metadata",
        model=ScriptedModel(script=[finish("Private answer", outcome="clarification")]),
        reviewer_model=ScriptedModel(script=[verdict()]),
    )
    try:
        await app.ask("Private question")
        assert tracing.provider.force_flush(timeout_millis=2000)
        root = next(s for s in exporter.get_finished_spans() if s.name == "retail.prompt")
        assert root.attributes is not None
        assert "input.value" not in root.attributes and "output.value" not in root.attributes
        assert root.status.status_code == StatusCode.OK
    finally:
        app.reports.close()
        tracing.close()


async def test_observer_failure_never_blocks_reviewed_result(settings):
    def unavailable(_):
        raise RuntimeError("observer-failure-canary")

    app = Analyst(
        settings,
        DEMO_USERS["alice"],
        observer=unavailable,
        observation_mode="synthetic",
        model=ScriptedModel(script=[finish("Which period?", outcome="clarification")]),
        reviewer_model=ScriptedModel(script=[verdict()]),
    )
    try:
        result = await app.ask("Describe sales.")
        assert result.status == "approved" and app.observer_errors > 0
    finally:
        app.reports.close()


def test_export_failure_and_shutdown_are_bounded():
    released = threading.Event()

    class BrokenExporter(SpanExporter):
        def export(self, spans):
            raise RuntimeError("export-error-canary")

        def shutdown(self):
            released.wait(3)

    session = configure_tracing(exporter=BrokenExporter())
    try:
        with span("retail.prompt"):
            pass
        session.provider.force_flush(timeout_millis=1000)
        assert session.failed_exports == 1
        start = time.monotonic()
        assert session.close(timeout_seconds=0.02) is False
        assert time.monotonic() - start < 0.5
    finally:
        released.set()
        session.close()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://remote.example/v1/traces",
        "http://user:password@127.0.0.1:6006/v1/traces",
        "http://127.0.0.1:6006/v1/traces?token=private",
    ],
)
def test_remote_or_credential_bearing_collector_is_rejected(endpoint):
    with pytest.raises(ValueError):
        configure_tracing(endpoint)


def test_cli_phoenix_initialization_failure_keeps_answer_available(make_agent, monkeypatch):
    from typer.testing import CliRunner

    from retail_agent import cli

    app = make_agent([finish("Which quarter?", outcome="clarification")], [verdict()])
    monkeypatch.setattr(cli, "build", lambda *_args: app)

    def unavailable(**_kwargs):
        raise RuntimeError("collector-credential-canary")

    monkeypatch.setattr(cli, "configure_tracing", unavailable)
    result = CliRunner().invoke(cli.app, ["ask", "Describe sales.", "--phoenix"])
    assert result.exit_code == 0 and "Which quarter?" in result.output
    assert "continuing without tracing" in result.output
    assert "collector-credential-canary" not in result.output
