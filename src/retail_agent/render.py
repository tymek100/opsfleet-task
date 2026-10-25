"""Render numeric evidence directly, independently of model prose."""

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from retail_agent.models import Answer
from retail_agent.quality import revenue_driver_details
from retail_agent.reports import Preview


def render_answer(answer: Answer, *, details: bool = False) -> str:
    parts = [answer.text]
    if (
        answer.evidence
        and answer.quality_status != "validated"
        and answer.intent
        and answer.intent.period
    ):
        period = answer.intent.period
        scope = answer.evidence[0].scope if answer.evidence else ""
        parts.append(f"Scope: {scope}; period: {period.start} to {period.end} UTC (end exclusive).")
    if answer.evidence:
        definitions: list[str] = []
        for item in answer.evidence:
            definition = (
                "Only completed orders and items are included."
                if item.request.completed_only
                else "Cancelled and returned orders/items are excluded."
            )
            if item.request.kind == "churn":
                definition += f" Inactivity means no qualifying purchase in {item.request.inactivity_days} days, among customers whose first qualifying purchase was more than that long ago."
            if item.request.dimension.value == "state":
                definition += " States with fewer than five customers are hidden."
            if definition not in definitions:
                definitions.append(definition)
        parts.extend(definitions)
    parts.extend("Warning: " + warning for warning in answer.warnings)
    if not details:
        if answer.evidence:
            parts.append("Use /details for calculation rules and query diagnostics.")
        return "\n\n".join(parts)
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
    drivers = revenue_driver_details(answer.evidence, answer.intent)
    if drivers:
        parts.append(drivers)
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


def display_answer(console: Console, answer: Answer, *, details: bool = False) -> None:
    """Executive summary by default; actual Rich tables in the detail view."""
    rendered = render_answer(answer)
    console.print()
    heading, _, body = rendered.partition("\n")
    if answer.quality_status == "validated" and heading == "Verified findings":
        console.print(heading, style="bold cyan", markup=False, highlight=False)
        console.print()
        console.print(Markdown(body.lstrip("\n")))
    else:
        console.print(Markdown(rendered))
    if not details:
        return
    for item in answer.evidence:
        console.print(
            f"[{item.id}] Scope: {item.scope}; {item.request.start} to {item.request.end} UTC (end exclusive)"
        )
        console.print(item.definitions)
        if item.rows:
            table = Table(show_lines=False)
            columns = list(item.rows[0])
            for column in columns:
                table.add_column(column.replace("_", " "))
            for row in item.rows:
                table.add_row(
                    *(str(row.get(c)) if row.get(c) is not None else "undefined" for c in columns)
                )
            console.print(table)
        else:
            console.print("No matching data or eligible cohort.")
        console.print(f"Job: {item.job_id}; SQL hash: {item.sql_hash}; queried: {item.queried_at}")
    drivers = revenue_driver_details(answer.evidence, answer.intent)
    if drivers:
        console.print(Markdown(drivers))
    console.print(f"Trace: {answer.trace_id}; reserved cost: ${answer.estimated_cost_usd:.4f}")
