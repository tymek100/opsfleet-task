"""Bounded relational operations on authorized evidence, never on natural-language text."""

from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from retail_agent.models import (
    Answer,
    AppError,
    Dimension,
    Identity,
    ResultView,
    Scalar,
    ViewSelection,
)
from retail_agent.presentation import (
    LABELS,
    escape_cell,
    metric_value,
    period_label,
    source_description,
)
from retail_agent.quality import metric_catalog, required_facts
from retail_agent.queries import compile_query


class RowFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le"]
    value: str | Annotated[float, Field(allow_inf_nan=False)]


class ViewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[str] = Field(min_length=1, max_length=6)
    operation: Literal["select", "intersection", "difference", "union"]
    columns: list[str] = Field(min_length=1, max_length=12)
    filters: list[RowFilter] = Field(default_factory=lambda: list[RowFilter](), max_length=6)
    sort_by: str | None = None
    descending: bool = True
    offset: int = Field(
        default=0,
        ge=-300,
        le=300,
        description="Zero-based starting position after filtering/sorting, before limit. Negative positions count from the end. Out-of-range positions return no rows.",
    )
    limit: int | None = Field(default=None, ge=1, le=50)
    output: Literal["auto", "table", "count"] = "auto"


KEYS = {
    "product": "product_id",
    "customer": "user_id",
    "brand": "brand",
    "category": "category",
    "month": "month",
    "state": "state",
}


def view_columns(key: str, source_id: str) -> list[str]:
    """Shared schema for existing and planned result sources."""
    return (
        [key]
        + (["product_name"] if key == "product_id" else [])
        + [
            f"{source_id}.{m}"
            for m in (
                "revenue",
                "customers",
                "orders",
                "units",
                "revenue_per_order",
                "revenue_per_unit",
                "units_per_order",
                "position" if key == "month" else "rank",
            )
        ]
    )


def result_sources(answer: Answer | None, identity: Identity) -> dict[str, ResultView]:
    if answer is None:
        return {}
    catalog = metric_catalog(answer.evidence, answer.intent)
    facts = required_facts(answer.intent, answer.evidence) if answer.intent else []
    tables: dict[str, ResultView] = {}
    for item in answer.evidence:
        # Recheck trusted permissions; cached results are not an authorization bypass.
        compile_query(item.request, identity)
        key = KEYS.get(item.request.dimension.value)
        if item.request.kind != "sales" or key is None:
            continue
        rows: list[dict[str, Scalar]] = []
        columns = [key] + (["product_name"] if key == "product_id" else [])
        for i, original in enumerate(item.rows):
            row = {k: original.get(k) for k in columns}
            prefix = f"{item.id}.r{i}."
            row.update(
                {f"{item.id}.{m.name}": m.value for k, m in catalog.items() if k.startswith(prefix)}
            )
            row[f"{item.id}.position" if key == "month" else f"{item.id}.rank"] = i + 1
            rows.append(row)
        # Keep a useful schema even when the source ranking has no rows.
        fields = view_columns(key, item.id)
        displayed: list[str] = []
        if answer.intent and not answer.intent.actions:
            ranked = item.request.dimension in (
                Dimension.PRODUCT,
                Dimension.CUSTOMER,
                Dimension.BRAND,
            ) and not (item.request.product_ids or item.request.customer_id)
            displayed = (
                ([f"{item.id}.rank"] if ranked else [])
                + columns
                + list(
                    dict.fromkeys(
                        f"{item.id}.{catalog[fact].name}"
                        for fact in facts
                        if fact.startswith(f"{item.id}.r") and fact in catalog
                    )
                )
            )
        tables[item.id] = ResultView(
            key=key, columns=fields, rows=rows, displayed_columns=displayed, source_ids=[item.id]
        )
    if answer.view is not None:
        tables["result"] = answer.view
    return tables


def evaluate_view(plan: ViewPlan, sources: dict[str, ResultView]) -> ResultView:
    if any(s not in sources for s in plan.sources) or len(set(plan.sources)) != len(plan.sources):
        raise AppError("Select existing, distinct result sources.")
    selected = [sources[s] for s in plan.sources]
    key = selected[0].key
    if any(s.key != key for s in selected):
        raise AppError("Result operations require the same entity grain.")
    if (plan.operation == "select") != (len(selected) == 1):
        raise AppError("Select needs one source; set operations need at least two.")
    fields = list(dict.fromkeys(c for s in selected for c in s.columns))
    requested = (
        plan.columns + [f.column for f in plan.filters] + ([plan.sort_by] if plan.sort_by else [])
    )
    if any(c not in fields for c in requested) or len(set(plan.columns)) != len(plan.columns):
        raise AppError("Use only distinct columns available in the selected result sources.")
    indexes: list[dict[Scalar, dict[str, Scalar]]] = []
    for source in selected:
        index = {row[key]: row for row in source.rows}
        if None in index or len(index) != len(source.rows):
            raise AppError("Result source does not have unique, defined entity keys.")
        indexes.append(index)
    ids = set(indexes[0])
    for index in indexes[1:]:
        if plan.operation == "intersection":
            ids &= set(index)
        elif plan.operation == "difference":
            ids -= set(index)
        else:
            ids |= set(index)
    # Stable source order preserves original ranking and deterministic tie order.
    order = list(dict.fromkeys(k for index in indexes for k in index))
    rows: list[dict[str, Scalar]] = []
    for entity in order:
        if entity not in ids:
            continue
        row: dict[str, Scalar] = {}
        for index in indexes:
            for column, value in index.get(entity, {}).items():
                if column in row and row[column] != value:
                    raise AppError("Result sources contain conflicting values for the same field.")
                row[column] = value
        rows.append({c: row.get(c) for c in fields})
    for condition in plan.filters:

        def matches(row: dict[str, Scalar], condition: RowFilter = condition) -> bool:
            value = row[condition.column]
            target = condition.value
            if value is None:
                return False
            if isinstance(value, (int, float)) and isinstance(target, (int, float)):
                comparison = (float(value) > float(target)) - (float(value) < float(target))
            elif isinstance(value, str) and isinstance(target, str):
                comparison = (value > target) - (value < target)
            else:
                raise AppError("Filter value type does not match its column.")
            return {
                "eq": comparison == 0,
                "ne": comparison != 0,
                "gt": comparison > 0,
                "ge": comparison >= 0,
                "lt": comparison < 0,
                "le": comparison <= 0,
            }[condition.operator]

        rows = [r for r in rows if matches(r)]
    if plan.sort_by:
        column = plan.sort_by
        defined = [r for r in rows if r[column] is not None]
        missing = [r for r in rows if r[column] is None]
        rows = (
            sorted(defined, key=lambda r: cast(str | float, r[column]), reverse=plan.descending)
            + missing
        )
    derivation = [step for source in selected for step in source.derivation]
    derivation.append(
        f"I used {', '.join(escape_cell(s) for s in plan.sources)} "
        f"({', '.join(str(len(s.rows)) for s in selected)} rows) "
        f"and applied the {plan.operation} operation."
    )
    for condition in plan.filters:
        derivation.append(
            f"I filtered {escape_cell(condition.column)} using {condition.operator} "
            f"{escape_cell(condition.value)}."
        )
    if plan.sort_by:
        derivation.append(
            f"I sorted the {len(rows)} matching rows by "
            f"{LABELS.get(plan.sort_by.split('.')[-1], plan.sort_by.split('.')[-1])} "
            f"({'highest first' if plan.descending else 'lowest first'})."
        )
    if plan.offset or plan.limit:
        derivation.append(
            f"I selected rows starting at offset {plan.offset}"
            + (f", keeping up to {plan.limit} rows." if plan.limit else ".")
        )
    candidate_count = len(rows)
    rows = [] if abs(plan.offset) > len(rows) else rows[plan.offset :]
    if plan.limit:
        rows = rows[: plan.limit]
    source_ids = list(
        dict.fromkeys(
            source_id
            for source in selected
            for source_id in (
                source.source_ids or [c.split(".")[0] for c in source.columns if "." in c]
            )
        )
    )
    measures = [c for c in plan.columns if "." in c]
    return ResultView(
        key=key,
        columns=fields,
        rows=rows,
        displayed_columns=plan.columns,
        source_ids=source_ids,
        derivation=derivation,
        selection=ViewSelection(
            operation=plan.operation,
            candidate_count=candidate_count,
            sort_by=plan.sort_by,
            descending=plan.descending,
            offset=plan.offset,
            limit=plan.limit,
        ),
        concise=(
            plan.output == "auto"
            and len(rows) == 1
            and len(measures) <= 2
            and (len(source_ids) == 1 or not measures)
        ),
    )


def render_view(plan: ViewPlan, view: ResultView, answer: Answer) -> str:
    evidence = [e for e in answer.evidence if e.id in view.source_ids]
    if not evidence:
        evidence = [e for e in answer.evidence if e.id in plan.sources]
    if not evidence:
        evidence = answer.evidence
    lines = ["Verified findings", ""]
    scopes = list(dict.fromkeys(f"{escape_cell(e.scope)} · {period_label(e)}" for e in evidence))
    lines += [*scopes, ""]
    singular, noun = {
        "product_id": ("product", "products"),
        "user_id": ("customer", "customers"),
        "brand": ("brand", "brands"),
        "category": ("category", "categories"),
        "month": ("month", "months"),
        "state": ("state", "states"),
    }[view.key]
    if plan.output == "count":
        count = len(view.rows)
        subject, verb = (singular, "matches") if count == 1 else (noun, "match")
        lines += [f"**{count} {subject} {verb} within the shown results.**", ""]
    elif not view.rows:
        lines += [f"No matching {noun} in the shown results.", ""]
    else:

        def label(column: str) -> str:
            source, _, name = column.rpartition(".")
            title = LABELS.get(name, name.replace("_", " ").capitalize())
            if sum(c.split(".")[-1] == name for c in plan.columns) > 1:
                item = next((e for e in evidence if e.id == source), None)
                if item:
                    title += f" ({source_description(item)})"
            return title

        lines += [
            "| " + " | ".join(label(c) for c in plan.columns) + " |",
            "| " + " | ".join("---" for _ in plan.columns) + " |",
        ]
        for row in view.rows:
            cells: list[str] = []
            for column in plan.columns:
                value = row.get(column)
                cells.append(
                    metric_value(column.split(".")[-1], value)
                    if "." in column and isinstance(value, (int, float))
                    else escape_cell(value)
                )
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)
