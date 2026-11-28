"""In-memory OpenTelemetry exporter; exercise real SDK spans without network."""

import json
from types import SimpleNamespace

from opentelemetry.sdk.trace.export import SpanExportResult


def document(attrs, key):
    value = json.loads(attrs.get(key, "{}"))
    if isinstance(value, dict) and value.get("capture_parts"):
        prefix = value["capture_parts"]
        return json.loads("".join(attrs[f"{prefix}.{i}"] for i in range(value["part_count"])))
    return value


class MemoryClient:
    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

    def get_finished_spans(self):
        return [CapturedRun(s) for s in self.spans]


class CapturedRun:
    def __init__(self, span):
        self.span = span
        self.name, self.end_time = span.name, span.end_time
        self.attributes = dict(span.attributes or {})
        self.inputs, self.outputs = (
            document(self.attributes, "input.value"),
            document(self.attributes, "output.value"),
        )
        self.status, self.context = span.status, span.context
        self.events = []
        for e in span.events:
            attrs = dict(e.attributes or {})
            if "retail.observation" in attrs:
                value = (
                    document(self.attributes, attrs["retail.observation"])
                    if attrs.get("retail.capture_reference")
                    else json.loads(attrs["retail.observation"])
                )
                attrs["retail.observation"] = json.dumps(value)
            self.events.append(SimpleNamespace(name=e.name, attributes=attrs))

    def to_json(self):
        return self.span.to_json()
