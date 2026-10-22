"""Render numeric evidence directly, independently of model prose."""

from retail_agent.models import Answer
from retail_agent.reports import Preview


def render_answer(answer: Answer) -> str:
    parts = [answer.text]
    for item in answer.evidence:
        parts += [
            f"\n[{item.id}] Scope: {item.scope}",
            f"Period: {item.request.start} → {item.request.end} (UTC, end exclusive)",
            item.definitions,
        ]
        if item.rows:
            columns = list(item.rows[0])
            parts += [" | ".join(columns), " | ".join("---" for _ in columns)]
            for row in item.rows:
                parts.append(
                    " | ".join("undefined" if row.get(k) is None else str(row[k]) for k in columns)
                )
        else:
            parts.append("No matching data (or no eligible cohort). No values inferred.")
        parts.append(f"Job: {item.job_id}; SQL hash: {item.sql_hash}; queried: {item.queried_at}")
    parts.append(
        f"\nTrace: {answer.trace_id}; conservative reserved cost: ${answer.estimated_cost_usd:.4f}"
    )
    return "\n".join(parts)


def render_preview(preview: Preview) -> str:
    if not preview.reports:
        return "No matching reports. Nothing deleted."
    lines = ["PERMANENT DELETION PREVIEW — nothing deleted yet:"]
    lines += [f"{r.id} | {r.title} | conversation {r.conversation}" for r in preview.reports]
    lines += [
        "Expires in five minutes. Only these exact reports will be deleted.",
        f"Type /confirm {preview.token} to permanently delete, or /cancel.",
    ]
    return "\n".join(lines)
