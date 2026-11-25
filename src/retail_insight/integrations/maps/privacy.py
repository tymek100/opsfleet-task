"""Remove marked provider content from persistence and observability payloads.

This operates on structured evidence, not arbitrary prose. A caller must also
disable model-message capture for any invocation containing ephemeral evidence.
Derived answer prose needs the same whole-turn persistence policy.
"""

from __future__ import annotations

from typing import Any

_SAFE_FIELDS = frozenset(
    {
        "id",
        "artifact_id",
        "task_id",
        "source_task_id",
        "source_agent",
        "source_evidence_id",
        "status",
        "provider",
        "tool",
        "retrieved_at",
        "queried_at",
        "scope",
        "parents",
        "as_of",
        "snapshot_at",
        "schema_version",
        "metric_version",
        "content_hash",
    }
)


def contains_maps(value: Any) -> bool:
    """Detect structured ephemeral evidence before configuring trace capture."""
    if isinstance(value, dict):
        if (
            value.get("storage_policy") == "ephemeral-provider-content"
            or value.get("contains_ephemeral_evidence") is True
        ):
            return True
        return any(contains_maps(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_maps(child) for child in value)
    return False


def scrub_maps(value: Any) -> Any:
    """Return a copy with marked Maps payloads replaced by provenance-only records.

    Raw text, route facts, addresses, attribution URLs and request arguments are
    intentionally omitted from marked records. IDs remain for trace correlation.
    Never use a redacted record as factual evidence on a subsequent turn.
    """
    if isinstance(value, dict):
        if value.get("storage_policy") == "ephemeral-provider-content":
            return {
                **{key: scrub_maps(child) for key, child in value.items() if key in _SAFE_FIELDS},
                "storage_policy": "ephemeral-provider-content",
                "trace_content": False,
                "content_redacted": True,
                "message": "Google Maps content was available only during execution; re-query for current facts.",
            }
        return {key: scrub_maps(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub_maps(child) for child in value]
    return value


def persistent_result(value: dict) -> dict:
    """Preserve operation metadata, but not answers derived from ephemeral content."""
    if not contains_maps(value):
        return value
    return {
        **scrub_maps(value),
        "markdown": "This answer used ephemeral Google Maps content and was not stored. Request a fresh route or weather lookup.",
        "observations": [],
        "trace": [],
        "content_redacted": True,
    }
