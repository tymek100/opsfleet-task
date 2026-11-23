"""Optional local tracing and explicit, sanitized evaluation observations.

Automatic instrumentation never exports raw model payloads. Synthetic evaluation
content is captured only through the application observer, after thought/secret
removal. The exporter applies a second allowlist to every outgoing span.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import Status

if TYPE_CHECKING:
    from retail_agent.prompt_catalog import PromptSpec

CaptureMode = Literal["metadata", "synthetic"]
Observer = Callable[[dict[str, Any]], None]
_SECRET_KEYS = frozenset(
    {
        "token",
        "confirmation_token",
        "api_key",
        "gemini_api_key",
        "authorization",
        "credentials",
        "password",
        "secret",
        "thought",
        "thoughts",
        "thinking",
        "thought_signature",
    }
)
_METADATA_FIELDS = frozenset(
    {
        "event",
        "conversation_id",
        "turn_id",
        "elapsed",
        "attempt",
        "role",
        "tool",
        "status",
        "code",
        "retryable",
        "decision",
        "issue_categories",
        "input_tokens",
        "output_tokens",
        "thinking_tokens",
        "spent_usd",
        "reserved_usd",
        "evidence_id",
        "answer_id",
        "sha256",
        "capture_errors",
        "trace_id",
        "span_id",
        "row_count",
        "truncated",
        "sql_sha256",
        "checks",
    }
)
_SAFE_ATTRIBUTES = frozenset(
    {
        "openinference.span.kind",
        "session.id",
        "retail.turn_id",
        "retail.role",
        "retail.attempt",
        "retail.status",
        "retail.capture_errors",
        "llm.model_name",
        "llm.token_count.prompt",
        "llm.token_count.completion",
        "llm.token_count.total",
        "retail.provider_reservation",
        "retail.case_id",
        "retail.repetition",
        "retail.run_id",
        "retail.prompt_name",
        "retail.prompt_sha256",
        "prompt.vendor",
        "prompt.id",
        "llm.prompt_template.version",
    }
)
_active: TracingSession | None = None
_lock = threading.Lock()


def sanitize_capture(value: Any, secrets: Sequence[str] = ()) -> Any:
    """Detach JSON data, omit thought parts, and redact secret-bearing fields."""
    if isinstance(value, Mapping):
        if value.get("thought") is True:
            return None
        return {
            str(key): sanitize_capture(item, secrets)
            for key, item in value.items()
            if str(key).lower() not in _SECRET_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [
            sanitize_capture(item, secrets)
            for item in value
            if not (isinstance(item, Mapping) and item.get("thought") is True)
        ]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", value)
        value = re.sub(r"(?i)(?:/confirm\s+)\S+", "/confirm [REDACTED]", value)
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def observation(
    record: dict[str, Any], *, mode: CaptureMode, secrets: Sequence[str] = ()
) -> dict[str, Any]:
    if mode not in ("metadata", "synthetic"):
        raise ValueError("Capture mode must be metadata or synthetic")
    selected = (
        record
        if mode == "synthetic"
        else {key: value for key, value in record.items() if key in _METADATA_FIELDS}
    )
    if mode == "metadata":
        if record.get("event") == "tool_observation" and "result" in record:
            result = record.get("result", {})
            selected.update(
                {
                    "tool": record.get("name"),
                    "status": result.get("status"),
                    "evidence_id": result.get("id"),
                    "row_count": len(result.get("rows", [])),
                    "truncated": result.get("truncated"),
                    "sql_sha256": result.get("sql_sha256"),
                }
            )
        if record.get("event") == "review_result" and "review" in record:
            selected["decision"] = record.get("review", {}).get("decision")
            selected["checks"] = record.get("review", {}).get("checks", [])
        if "checks" in selected:
            selected["checks"] = [
                {"category": check.get("category"), "passed": check.get("passed")}
                for check in selected["checks"]
            ]
    return json.loads(json.dumps(sanitize_capture(selected, secrets), allow_nan=False))


def record_observation(record: dict[str, Any], mode: CaptureMode) -> None:
    """Attach already sanitized application observations to the current span."""
    if _active is None:
        return
    payload = observation(record, mode=mode)
    if mode == "synthetic" and _active.mode != "synthetic":
        payload = observation(record, mode="metadata")
    trace.get_current_span().add_event(
        "retail.observation", {"retail.observation": json.dumps(payload)}
    )


class SanitizingExporter(SpanExporter):
    """Apply capture policy after instrumentation, including exceptions/resources."""

    def __init__(self, delegate: SpanExporter, mode: CaptureMode, project: str = "retail-agent"):
        self.delegate = delegate
        self.mode: CaptureMode = mode
        self.project = project
        self.failed_exports = 0

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        cleaned = []
        for span in spans:
            attributes = {
                key: value
                for key, value in (span.attributes or {}).items()
                if key in _SAFE_ATTRIBUTES
                and (
                    not key.startswith("llm.token_count.") or span.name == "retail.provider_attempt"
                )
            }
            events = []
            for event in span.events:
                if event.name != "retail.observation":
                    continue
                try:
                    payload = json.loads(
                        str((event.attributes or {}).get("retail.observation", "{}"))
                    )
                    payload = observation(payload, mode=self.mode)
                    events.append(
                        Event(
                            "retail.observation",
                            {"retail.observation": json.dumps(payload)},
                            event.timestamp,
                        )
                    )
                except (ValueError, TypeError):
                    continue
            kind = str(attributes.get("openinference.span.kind", "span")).lower()
            name = (
                span.name
                if span.name
                in {
                    "retail.prompt",
                    "retail.provider_attempt",
                    "retail.evaluation_trial",
                    "retail.judge",
                }
                else f"adk.{kind}"
            )
            resource = Resource(
                {"service.name": "retail-agent", "openinference.project.name": self.project}
            )
            cleaned.append(
                ReadableSpan(
                    name=name,
                    context=span.context,
                    parent=span.parent,
                    resource=resource,
                    attributes=attributes,
                    events=events,
                    links=(),
                    kind=span.kind,
                    status=Status(span.status.status_code),
                    start_time=span.start_time,
                    end_time=span.end_time,
                    instrumentation_scope=InstrumentationScope("retail_agent"),
                )
            )
        try:
            result = self.delegate.export(cleaned)
        except Exception:
            result = SpanExportResult.FAILURE
        if result is not SpanExportResult.SUCCESS:
            self.failed_exports += 1
        return result

    def shutdown(self) -> None:
        self.delegate.shutdown()

    def force_flush(self, timeout_millis: int = 1000) -> bool:
        return self.delegate.force_flush(timeout_millis)


@dataclass
class TracingSession:
    provider: TracerProvider
    exporter: SanitizingExporter
    instrumentor: Any
    endpoint: str
    project: str
    mode: CaptureMode
    closed: bool = False
    prompt_versions: dict[str, str] = field(default_factory=dict)

    def register_prompts(self, references: list[dict]) -> None:
        self.prompt_versions.update({item["sha256"]: item["version_id"] for item in references})

    @property
    def failed_exports(self) -> int:
        return self.exporter.failed_exports

    def close(self, timeout_seconds: float = 2) -> bool:
        """Bound shutdown; a failed local collector cannot stall CLI termination."""
        global _active
        if self.closed:
            return True
        self.closed = True
        try:
            self.instrumentor.uninstrument()
        except Exception:
            self.exporter.failed_exports += 1
        with _lock:
            if _active is self:
                _active = None

        def shutdown() -> None:
            try:
                self.provider.shutdown()
            except Exception:
                self.exporter.failed_exports += 1

        worker = threading.Thread(target=shutdown, daemon=True)
        worker.start()
        worker.join(max(0, timeout_seconds))
        return not worker.is_alive()


def prompt_attributes(spec: PromptSpec) -> dict[str, str]:
    """Attribute only an exact synchronized definition; unknown versions keep their hash."""
    attributes = {"retail.prompt_name": spec.name, "retail.prompt_sha256": spec.sha256}
    version_id = _active.prompt_versions.get(spec.sha256) if _active else None
    if version_id:
        attributes.update(
            {
                "prompt.vendor": "arize-phoenix",
                "prompt.id": version_id,
                "llm.prompt_template.version": version_id,
            }
        )
    return attributes


def configure_tracing(
    endpoint: str = "http://127.0.0.1:6006/v1/traces",
    *,
    project: str = "retail-agent",
    mode: CaptureMode = "metadata",
    exporter: SpanExporter | None = None,
) -> TracingSession:
    """Explicit opt-in; import/install optional instrumentors only on activation."""
    global _active
    if mode not in ("metadata", "synthetic"):
        raise ValueError("Capture mode must be metadata or synthetic")
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Phoenix tracing requires a localhost HTTP endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Trace endpoints cannot contain credentials or query parameters")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", project):
        raise ValueError("Invalid trace project name")
    with _lock:
        if _active is not None:
            if (_active.endpoint, _active.project, _active.mode) != (endpoint, project, mode):
                raise ValueError("Tracing is already configured differently in this process")
            return _active
        from openinference.instrumentation import TraceConfig
        from openinference.instrumentation.google_adk import GoogleADKInstrumentor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        delegate = exporter or OTLPSpanExporter(endpoint=endpoint, timeout=1)
        safe_exporter = SanitizingExporter(delegate, mode, project)
        provider = TracerProvider(
            shutdown_on_exit=False,
            resource=Resource(
                {
                    "service.name": "retail-agent",
                    "openinference.project.name": project,
                }
            ),
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                safe_exporter,
                max_queue_size=256,
                max_export_batch_size=32,
                schedule_delay_millis=250,
                export_timeout_millis=1000,
            )
        )
        instrumentor = GoogleADKInstrumentor()
        instrumentor.instrument(
            tracer_provider=provider,
            config=TraceConfig(
                hide_inputs=True,
                hide_outputs=True,
                hide_input_messages=True,
                hide_output_messages=True,
                hide_llm_invocation_parameters=True,
                hide_llm_tools=True,
                hide_retrieval_documents=True,
            ),
        )
        _active = TracingSession(provider, safe_exporter, instrumentor, endpoint, project, mode)
        return _active


@contextmanager
def detached_span(name: str, **attributes: Any) -> Iterator[Any]:
    """Record an operation without leaking its context across an async yield."""
    provider = _active.provider if _active is not None else trace.NoOpTracerProvider()
    current = provider.get_tracer("retail_agent").start_span(name, attributes=attributes)
    try:
        yield current
    finally:
        if current.is_recording():
            current.end()


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    provider = _active.provider if _active is not None else trace.NoOpTracerProvider()
    with provider.get_tracer("retail_agent").start_as_current_span(
        name, attributes=attributes, record_exception=False, set_status_on_exception=False
    ) as current:
        yield current
