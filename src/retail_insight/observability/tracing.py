"""Explicit OpenTelemetry spans exported to the project's Application Insights.

Automatic graph/state instrumentation remains disabled. Only the existing
sanitized observation boundary may opt in to recording synthetic content.
"""

from __future__ import annotations

import json
import os
import re
import warnings
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Status, StatusCode

from retail_insight.integrations.azure.connector import AzureConnector, AzureSettings

CaptureMode = Literal["metadata", "synthetic"]
Observer = Callable[[dict[str, Any]], None]
_SECRET_KEYS = frozenset(
    {
        "token",
        "confirmation_token",
        "api_key",
        "gemini_api_key",
        "azure_openai_api_key",
        "azure_client_secret",
        "applicationinsights_connection_string",
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
        "agent",
        "reason",
        "allowance_usd",
        "deadline_seconds",
        "usage_settled",
    }
)


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


_active = None
_current: ContextVar[Span | None] = ContextVar("retail_trace_span", default=None)
_trace_fields: ContextVar[dict | None] = ContextVar("retail_trace_fields", default=None)


class CheckedExporter(SpanExporter):
    def __init__(self, delegate):
        self.delegate = delegate
        self.failures = 0

    def export(self, spans):
        try:
            result = self.delegate.export(spans)
        except Exception:
            result = SpanExportResult.FAILURE
        if result != SpanExportResult.SUCCESS:
            self.failures += 1
        return result

    def shutdown(self):
        self.delegate.shutdown()


@dataclass
class TracingSession:
    provider: Any
    exporter: CheckedExporter
    project: str
    mode: CaptureMode
    agent_id: str = "retail-insight"
    connector: Any = None
    prompt_versions: dict = field(default_factory=dict)
    failed_exports: int = 0
    secrets: tuple[str, ...] = ()

    @property
    def client(self):
        # The runners need a flush boundary, not an Azure project client.
        return self

    def register_prompts(self, references):
        self.prompt_versions.update(
            {p["sha256"]: p.get("version_id", p["sha256"]) for p in references}
        )

    def flush(self, timeout_seconds=2):
        ok = self.provider.force_flush(timeout_millis=int(timeout_seconds * 1000))
        self.failed_exports = max(self.failed_exports, self.exporter.failures)
        return bool(ok and not self.failed_exports)

    def close(self, timeout_seconds=2):
        global _active
        if _active is self:
            _active = None
        try:
            ok = self.flush(timeout_seconds)
            self.provider.shutdown()
            if self.connector:
                self.connector.close()
            return ok
        except Exception:
            self.failed_exports += 1
            return False


def configure_tracing(
    endpoint=None, *, project=None, mode="metadata", client=None, exporter=None, connector=None
):
    global _active
    if mode not in ("metadata", "synthetic"):
        raise ValueError("Capture mode must be metadata or synthetic")
    cfg = AzureSettings()
    # client is retained only as an injected test exporter, never for Azure auth.
    exporter = exporter or client
    local = exporter is not None
    connector = connector or (None if local else AzureConnector(cfg))
    provider = TracerProvider(
        span_limits=SpanLimits(max_attributes=2048, max_events=512),
        resource=Resource.create(
            {"service.name": "retail-insight", "gen_ai.agent.id": cfg.foundry_agent_id}
        ),
    )
    if exporter is None:
        assert connector is not None
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

        exporter = AzureMonitorTraceExporter(
            connection_string=connector.monitoring_connection(),
            disable_offline_storage=True,
            tracer_provider=provider,
            **({"credential": connector.credential()} if cfg.azure_monitor_entra_auth else {}),
        )
    checked = CheckedExporter(exporter)
    provider.add_span_processor(
        SimpleSpanProcessor(checked)
        if local
        else BatchSpanProcessor(checked, schedule_delay_millis=1000, export_timeout_millis=5000)
    )
    secrets = tuple(
        v
        for k, v in os.environ.items()
        if any(word in k.upper() for word in ("API_KEY", "CLIENT_SECRET", "CONNECTION_STRING"))
        and len(v) >= 8
    )
    _active = TracingSession(
        provider,
        checked,
        project or "retail-insight",
        mode,
        cfg.foundry_agent_id,
        connector,
        secrets=secrets,
    )
    return _active


def configure_from_env():
    if not AzureSettings().foundry_tracing:
        return None
    try:
        return configure_tracing(mode=os.getenv("TRACE_CONTENT_MODE", "metadata"))
    except Exception as exc:
        warnings.warn(
            f"Foundry tracing unavailable ({type(exc).__name__}). Check Azure login and Application Insights; chat remains available.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


def prompt_attributes(spec):
    return {"prompt_name": spec.name, "prompt_sha256": spec.sha256}


@contextmanager
def trace_context(**fields):
    if any(key not in {"run_id", "case_id", "step_id", "phase"} for key in fields):
        raise ValueError("Unknown trace context field")
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", str(v)) for v in fields.values()):
        raise ValueError("Invalid trace context value")
    token = _trace_fields.set({**(_trace_fields.get() or {}), **fields})
    try:
        yield
    finally:
        _trace_fields.reset(token)


def payloads(events, attributes, mode):
    inputs, outputs = {}, {}
    for e in events:
        if e.get("event") == "prompt_input" and "question" in e:
            inputs = {"question": e["question"]}
        if e.get("event") == "turn_result":
            outputs = e.get("result", {"status": attributes.get("retail.status")})
        if e.get("event") == "provider_request":
            inputs = {"request": e.get("request", {})}
        if e.get("event") == "provider_response":
            outputs = {"response": e.get("response", {})}
        if e.get("event") == "judge_input" and "request" in e:
            inputs = e["request"]
        if e.get("event") == "judge_result" and "response" in e:
            outputs = {
                "response": e["response"],
                "summary": e.get("summary"),
                "validation_error": e.get("validation_error"),
            }
    if mode == "synthetic":
        for key, destination in (("input.value", inputs), ("output.value", outputs)):
            with suppress(ValueError, TypeError):
                value = json.loads(attributes.get(key, "null"))
                if isinstance(value, dict):
                    destination.update(value)
    return inputs, outputs


def semantic_messages(inputs, outputs):
    """Public GenAI message attributes, never hidden model thoughts."""
    fields = {}
    request = inputs.get("request", {})
    messages = inputs.get("messages")
    if messages:
        fields["gen_ai.input.messages"] = [
            {
                "role": m.get("role", "user"),
                "parts": [{"type": "text", "content": m.get("content", "")}],
            }
            for m in messages
        ]
    elif request:
        fields["gen_ai.input.messages"] = [
            {
                "role": "assistant" if c.get("role") == "model" else c.get("role", "user"),
                "parts": [
                    {"type": "text", "content": p["text"]}
                    if p.get("text") is not None
                    else {"type": "tool_call", **p["function_call"]}
                    if p.get("function_call")
                    else {"type": "tool_call_response", **p["function_response"]}
                    for p in c.get("parts", [])
                    if p
                    and not p.get("thought")
                    and (
                        p.get("text") is not None
                        or p.get("function_call")
                        or p.get("function_response")
                    )
                ],
            }
            for c in request.get("contents", [])
        ]
        instruction = request.get("config", {}).get("system_instruction")
        if instruction:
            fields["gen_ai.system_instructions"] = [{"type": "text", "content": instruction}]
    elif inputs.get("question"):
        fields["gen_ai.input.messages"] = [
            {"role": "user", "parts": [{"type": "text", "content": inputs["question"]}]}
        ]
    response = outputs.get("response")
    if isinstance(response, dict):
        parts = (response.get("content") or {}).get("parts", [])
        text = "\n".join(
            p["text"] for p in parts if p and p.get("text") is not None and not p.get("thought")
        )
    else:
        text = response if isinstance(response, str) else outputs.get("markdown")
    if text:
        fields["gen_ai.output.messages"] = [
            {"role": "assistant", "parts": [{"type": "text", "content": text}]}
        ]
    return fields


class Span:
    def __init__(self, name, attributes, parent=None):
        self.name = name
        self.attributes = {**(_trace_fields.get() or {}), **attributes}
        self.status = Status()
        self.ended = False
        self.observations = []
        self.session = _active
        self.run = None
        if self.session:
            context = trace.set_span_in_context(parent.run) if parent and parent.run else None
            self.run = self.session.provider.get_tracer("retail_insight").start_span(
                name, context=context
            )

    def get_span_context(self):
        return self.run.get_span_context() if self.run else trace.INVALID_SPAN_CONTEXT

    def is_recording(self):
        return self.run is not None and not self.ended

    def set_attribute(self, name, value):
        self.attributes[name] = value

    def set_status(self, status):
        self.status = status

    def add_event(self, name, attributes):
        with suppress(ValueError, TypeError):
            self.observations.append(json.loads(attributes.get("retail.observation", "{}")))

    def end(self):
        if self.ended:
            return
        self.ended = True
        if self.run is None or self.session is None:
            return
        try:
            session = self.session
            events = [
                observation(e, mode=session.mode, secrets=session.secrets)
                for e in self.observations
            ]
            inputs, outputs = payloads(events, self.attributes, session.mode)
            attrs = dict(self.attributes)
            if session.mode == "metadata":
                attrs = {
                    k: v
                    for k, v in attrs.items()
                    if not k.startswith(
                        (
                            "input.",
                            "output.",
                            "llm.input",
                            "llm.output",
                            "llm.prompt_template",
                            "gen_ai.input",
                            "gen_ai.output",
                        )
                    )
                }
            attrs.update(
                {
                    "gen_ai.agent.id": session.agent_id,
                    "gen_ai.agent.name": self.attributes.get("agent", session.agent_id),
                    "retail.project": session.project,
                }
            )
            llm = attrs.get("openinference.span.kind") == "LLM"
            attrs["gen_ai.operation.name"] = (
                "chat"
                if llm
                else "execute_tool"
                if self.name.endswith(".tools")
                else "invoke_agent"
            )
            if llm:
                attrs["gen_ai.provider.name"] = "gcp.gemini"
                if "llm.model_name" in attrs:
                    attrs["gen_ai.request.model"] = attrs["llm.model_name"]
                for old, new in (
                    ("llm.token_count.prompt", "gen_ai.usage.input_tokens"),
                    ("llm.token_count.completion", "gen_ai.usage.output_tokens"),
                ):
                    if old in attrs:
                        attrs[new] = attrs[old]
            if "session.id" in attrs:
                attrs["gen_ai.conversation.id"] = attrs["session.id"]
            if session.mode == "synthetic":
                for key, value in semantic_messages(inputs, outputs).items():
                    encoded = json.dumps(
                        sanitize_capture(value, session.secrets), ensure_ascii=True
                    )
                    if len(encoded) <= 7500:
                        attrs[key] = encoded
                    else:
                        # Full sanitized documents are stored below in numbered parts.
                        attrs[key + ".omitted_for_size"] = True
            for key, value in (("input.value", inputs), ("output.value", outputs)):
                if value:
                    self._document(attrs, key, sanitize_capture(value, session.secrets))
            encoded_events = []
            for i, event in enumerate(events):
                key = f"retail.observation.{i}"
                self._document(attrs, key, event)
                encoded_events.append({"retail.observation": key, "retail.capture_reference": True})
            for key, value in list(attrs.items()):
                if isinstance(value, str) and len(value.encode()) > 8000:
                    self._document(attrs, key, value)
            for key, value in sanitize_capture(attrs, session.secrets).items():
                if value is not None:
                    self.run.set_attribute(
                        key,
                        value if isinstance(value, (str, bool, int, float)) else json.dumps(value),
                    )
            for event in encoded_events:
                self.run.add_event("retail.observation", event)
            self.run.set_status(self.status)
        except Exception:
            self.session.failed_exports += 1
        finally:
            self.run.end()

    @staticmethod
    def _document(attrs, key, value):
        encoded = json.dumps(value, ensure_ascii=True)
        if len(encoded) <= 7500:
            attrs[key] = encoded
            return
        parts = [encoded[i : i + 7500] for i in range(0, len(encoded), 7500)]
        prefix = key + ".parts"
        attrs[key] = json.dumps(
            {"capture_parts": prefix, "part_count": len(parts), "preview": encoded[:500]}
        )
        for i, part in enumerate(parts):
            attrs[f"{prefix}.{i}"] = part


def record_observation(record, mode):
    current = _current.get()
    if current is not None:
        current.observations.append(observation(record, mode=mode))


@contextmanager
def detached_span(name, **attributes):
    current = Span(name, attributes, _current.get())
    try:
        yield current
    except BaseException:
        current.set_status(Status(StatusCode.ERROR))
        raise
    finally:
        current.end()


@contextmanager
def span(name, **attributes):
    with detached_span(name, **attributes) as current:
        token = _current.set(current)
        try:
            yield current
        finally:
            _current.reset(token)
