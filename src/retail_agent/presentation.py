"""Business-facing tables built only from verified metric values and evidence."""

import re
from datetime import timedelta

from retail_agent.models import Dimension, Evidence, Scalar

LABELS = {
    "user_id": "Customer ID",
    "product_id": "Product ID",
    "product_name": "Product",
    "month": "Month",
    "brand": "Brand",
    "category": "Category",
    "state": "State",
    "revenue": "Revenue",
    "orders": "Orders",
    "customers": "Distinct customers",
    "units": "Units sold",
    "units_per_order": "Units per order",
    "revenue_per_unit": "Revenue per unit",
    "revenue_per_order": "Revenue per order",
}
GROUPS = {
    Dimension.CUSTOMER: ("user_id",),
    Dimension.PRODUCT: ("product_id", "product_name"),
    Dimension.MONTH: ("month",),
    Dimension.BRAND: ("brand",),
    Dimension.CATEGORY: ("category",),
    Dimension.STATE: ("state",),
}


def escape_cell(value: Scalar) -> str:
    """Prevent catalog text from turning into links, formatting or table rows."""
    text = " ".join(str(value).split()) if value is not None else "Not available"
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~-])", r"\\\1", text)


def period_label(item: Evidence) -> str:
    start, end = item.request.start, item.request.end - timedelta(days=1)
    return f"{start:%d %b %Y} to {end:%d %b %Y} (UTC)"


def table_findings(item: Evidence, values: dict[str, float | int | None]) -> str:
    """Render selected verified row metrics; SQL rank order is preserved."""
    selected: dict[int, dict[str, float | int | None]] = {}
    for key, value in values.items():
        match = re.fullmatch(re.escape(item.id) + r"\.r(\d+)\.(\w+)", key)
        if match:
            selected.setdefault(int(match[1]), {})[match[2]] = value
    if not selected:
        return ""
    dimension = item.request.dimension
    metrics = list(dict.fromkeys(name for row in selected.values() for name in row))
    groups = [key for key in GROUPS[dimension] if any(key in row for row in item.rows)]
    ranked = dimension in (Dimension.CUSTOMER, Dimension.PRODUCT, Dimension.BRAND) and not (
        item.request.customer_id or item.request.product_ids
    )
    measure = (
        "total spend"
        if dimension == Dimension.CUSTOMER and item.request.rank_by == "revenue"
        else LABELS[item.request.rank_by].lower()
    )
    if dimension == Dimension.MONTH:
        title = "Monthly performance"
    elif item.request.customer_id:
        title = "Customer spending"
    elif item.request.product_ids:
        title = "Product comparison"
    elif ranked:
        noun = {
            Dimension.CUSTOMER: "customers",
            Dimension.PRODUCT: "products",
            Dimension.BRAND: "brands",
        }[dimension]
        title = f"Top {len(selected)} {noun} by {measure}"
    else:
        title = f"Performance by {dimension.value}"
    labels = [
        (
            "Total spend"
            if dimension == Dimension.CUSTOMER and key == "revenue"
            else LABELS.get(key, key.replace("_", " ").capitalize())
        )
        for key in metrics
    ]
    headers = (["Rank"] if ranked else []) + [LABELS[key] for key in groups] + labels
    lines = [
        f"### {title}",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for index, row_values in sorted(selected.items()):
        cells = ([str(index + 1)] if ranked else []) + [
            escape_cell(item.rows[index].get(key)) for key in groups
        ]
        for name in metrics:
            value = row_values.get(name)
            if value is None:
                cells.append("Not available")
            elif name.startswith("revenue") or name == "units_per_order":
                cells.append(f"{value:,.2f}")
            else:
                cells.append(f"{value:,}")
        lines.append("| " + " | ".join(cells) + " |")
    if ranked and dimension == Dimension.CUSTOMER and item.request.rank_by == "revenue":
        spends = [row.get("revenue") for row in selected.values()]
        defined = [value for value in spends if value is not None]
        if defined:
            lines += ["", f"Highest spending shown: {max(defined):,.2f}."]
        if all(row.get("orders") == 1 for row in selected.values()):
            lines += ["", "Each customer in this ranking placed one qualifying order."]
    lines += ["", f"Source: [{item.id}]."]
    return "\n".join(lines)


def period_name(item: Evidence) -> str:
    start, end = item.request.start, item.request.end
    if (
        start.day == end.day == 1
        and start.month in (1, 4, 7, 10)
        and (end.year - start.year) * 12 + end.month - start.month == 3
    ):
        return f"Q{(start.month + 2) // 3} {start.year}"
    return period_label(item)


def movement(label: str, percent: float | int | None) -> str:
    if percent is None:
        return f"{label} percentage change is undefined with the available data"
    if percent == 0:
        return f"{label} was unchanged"
    direction = "rose" if percent > 0 else "fell"
    amount = f"{abs(percent):.2f}%" if abs(percent) >= 0.005 else "less than 0.01%"
    return f"{label} {direction} {amount}"


def comparison_findings(
    old: Evidence,
    new: Evidence,
    values: dict[str, float | int | None],
    names: list[str],
) -> str:
    """Compare compatible totals using already computed catalog metrics, not model prose."""
    prefix = f"{new.id}.vs.{old.id}"
    total_change = values.get(f"{prefix}.revenue_change_pct")
    daily_change = values.get(f"{prefix}.revenue_per_day_change_pct")
    old_name, new_name = period_name(old), period_name(new)
    summary = movement("Revenue", total_change)
    if "revenue_per_day" in names:
        summary += ", while " + movement("average daily revenue", daily_change)
    lines = [
        summary + ".",
        "",
        f"**{escape_cell(old.scope)}** · {old_name} versus {new_name} · UTC",
        "",
    ]
    if old.request.brands and ", ".join(old.request.brands) != old.scope:
        lines += ["Selected brands: " + ", ".join(escape_cell(b) for b in old.request.brands), ""]
    # Retain narrower filters even when the broad authorized scope is the same.
    if old.request.product_ids:
        lines += ["Selected product IDs: " + ", ".join(map(str, old.request.product_ids)), ""]
    if old.request.customer_id:
        lines += [f"Customer ID: {old.request.customer_id}", ""]
    lines += [f"| Metric | {old_name} | {new_name} | Change |", "| --- | --- | --- | --- |"]
    labels = {**LABELS, "days": "Calendar days", "revenue_per_day": "Average daily revenue"}
    for name in names:
        a, b = values.get(f"{old.id}.r0.{name}"), values.get(f"{new.id}.r0.{name}")
        money = name.startswith("revenue")
        cells = [
            "Not available" if v is None else f"{v:,.2f}" if money else f"{v:,}" for v in (a, b)
        ]
        if a is None or b is None:
            change = "Not available"
        else:
            delta = b - a
            change = f"{delta:+,.2f}" if money else f"{delta:+,}"
        percent_key = f"{prefix}.{name}_change_pct"
        if percent_key in values:
            percent = values[percent_key]
            change += " (percentage undefined)" if percent is None else f" ({percent:+.2f}%)"
        lines.append("| " + " | ".join([labels[name], *cells, change]) + " |")
    old_days, new_days = (
        (old.request.end - old.request.start).days,
        (new.request.end - new.request.start).days,
    )
    lines += ["", f"{new_name} had {new_days} days versus {old_days} in {old_name}."]
    if "revenue_per_day" in names:
        if total_change is not None and daily_change is not None:
            if total_change < 0 <= daily_change:
                trend = "increased" if daily_change > 0 else "was unchanged"
                lines += [f"Despite lower total revenue, average daily revenue {trend}."]
            elif total_change > 0 >= daily_change:
                trend = "decreased" if daily_change < 0 else "was unchanged"
                lines += [f"Despite higher total revenue, average daily revenue {trend}."]
        lines += ["Daily averages include every calendar day, including days without sales."]
    counts = ("units", "orders", "customers")
    if all(
        name in names
        and values.get(f"{old.id}.r0.{name}") is not None
        and values.get(f"{new.id}.r0.{name}") is not None
        for name in counts
    ) and all(
        float(values[f"{new.id}.r0.{name}"] or 0) > float(values[f"{old.id}.r0.{name}"] or 0)
        for name in counts
    ):
        lines += ["Units sold, orders and customer counts all increased."]
    lines += ["", f"Sources: [{old.id}], [{new.id}]."]
    return "\n".join(lines)


def metric_value(name: str, value: float | int | None) -> str:
    """Consistent business units for tables, references and action baselines."""
    if value is None:
        return "Not available"
    if name == "inactivity_share":
        return f"{value * 100:.4f}%"
    if name.endswith("_pct"):
        return f"{value:+.2f}%"
    if name == "percentage_point_change":
        return f"{value:+.4f} percentage points"
    if name in (
        "revenue",
        "revenue_per_day",
        "revenue_per_unit",
        "revenue_per_order",
        "units_per_order",
        "revenue_change",
        "volume_contribution",
        "unit_value_contribution",
    ):
        return f"{value:,.2f}"
    return f"{value:,}"


def empty_sales(item: Evidence) -> bool:
    return item.request.kind == "sales" and (
        not item.rows or all(row.get("units") == 0 for row in item.rows)
    )


def churn_findings(item: Evidence) -> str:
    """Display the population alongside the share so rounding cannot hide a change."""
    lines = [f"**{escape_cell(item.scope)}** · Customer inactivity · UTC", ""]
    if not item.rows:
        return "\n".join(
            [
                *lines,
                "| As of (UTC) | Eligible customers | Inactive customers | Inactivity share |",
                "| --- | --- | --- | --- |",
                f"| {item.request.start} | 0 | 0 | Undefined |",
                f"| {item.request.end} | 0 | 0 | Undefined |",
                "",
                "No eligible customer cohort was found. With a zero denominator, the inactivity share is undefined, not 0%. A change cannot be calculated.",
                f"Source: [{item.id}].",
            ]
        )
    for cohort in sorted({str(row.get("cohort", "all")) for row in item.rows}):
        rows = sorted(
            (r for r in item.rows if str(r.get("cohort", "all")) == cohort),
            key=lambda r: str(r.get("period", "")),
        )
        if cohort != "all":
            lines += [f"### {escape_cell(cohort)}", ""]
        lines += [
            "| As of (UTC) | Eligible customers | Inactive customers | Inactivity share |",
            "| --- | --- | --- | --- |",
        ]
        for row in rows:
            share = row.get("inactivity_share")
            lines.append(
                "| "
                + " | ".join(
                    [
                        escape_cell(row.get("period")),
                        escape_cell(row.get("eligible_customers")),
                        escape_cell(row.get("inactive_customers")),
                        metric_value(
                            "inactivity_share", share if isinstance(share, (float, int)) else None
                        ),
                    ]
                )
                + " |"
            )
        if len(rows) != 2:
            lines += ["", "Both snapshots are needed to assess a change."]
            continue
        old, new = rows
        a, b = old.get("inactivity_share"), new.get("inactivity_share")
        if isinstance(a, (float, int)) and isinstance(b, (float, int)):
            change = (b - a) * 100
            digits = 6 if 0 < abs(change) < 0.0001 else 4
            direction = (
                "increased" if change > 0 else "decreased" if change < 0 else "was unchanged"
            )
            lines += [
                "",
                f"Inactivity {direction}; change: {change:+.{digits}f} percentage points.",
            ]
            if change > 0:
                lines += ["An increase alone does not establish a spike or explain its cause."]
            else:
                lines += ["These snapshots do not show an increase in inactivity."]
            old_n, new_n = old.get("eligible_customers"), new.get("eligible_customers")
            old_i, new_i = old.get("inactive_customers"), new.get("inactive_customers")
            if (
                isinstance(old_n, int)
                and isinstance(new_n, int)
                and isinstance(old_i, int)
                and isinstance(new_i, int)
            ):
                active_old, active_new = old_n - old_i, new_n - new_i
                lines += [
                    f"Eligible customers: {old_n:,} → {new_n:,}; inactive customers: {old_i:,} → {new_i:,}."
                ]
                if active_old == active_new and old_n != new_n and change != 0:
                    lines += [
                        f"Eligible active customers stayed at {active_new:,}. The share changed as the eligible population changed, without a change in the active count."
                    ]
        else:
            lines += ["", "A change cannot be calculated without eligible customers at both dates."]
    lines += [
        "",
        "This is an inactivity share, not a count of newly lost customers.",
        f"Source: [{item.id}].",
    ]
    return "\n".join(lines)
