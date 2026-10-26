"""Evidence-bound report language: model selection, deterministic facts and rendering.

This deliberately supports a small analytical vocabulary, not arbitrary prose entailment.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from retail_agent.intent import completion_issues
from retail_agent.models import Dimension, Evidence, Intent, Scalar
from retail_agent.presentation import (
    churn_findings,
    comparison_findings,
    empty_sales,
    escape_cell,
    metric_value,
    period_label,
    table_findings,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hypothesis(Contract):
    mechanism: Literal["seasonality", "promotion", "availability", "product_mix"]
    evidence_ids: list[str] = Field(min_length=1, max_length=4)


class ProposedAction(Contract):
    kind: Literal["cross_sell_test", "demand_investigation", "assortment_review", "retention_test"]
    metric_id: str
    start: date
    end: date
    target: None = Field(
        default=None,
        description="Always null: this contract has no justified numeric target source.",
    )

    @field_serializer("start", "end")
    def serialize_date(self, value: date) -> str:
        # ADK 2.12's structured-response tool uses model_dump() before json.dumps().
        return value.isoformat()


class Narrative(Contract):
    facts: list[str] = Field(max_length=6000)
    hypotheses: list[Hypothesis] = Field(default_factory=lambda: list[Hypothesis](), max_length=3)
    actions: list[ProposedAction] = Field(
        default_factory=lambda: list[ProposedAction](), max_length=4
    )


@dataclass(frozen=True)
class Metric:
    id: str
    name: str
    value: float | int | None
    context: str
    evidence_ids: tuple[str, ...]

    def statement(self) -> str:
        value = (
            "undefined (no eligible denominator/data)"
            if self.value is None
            else f"{self.value:,.4f}".rstrip("0").rstrip(".")
        )
        label = METRICS.get(
            self.name, self.name.replace("_change_pct", " change (%)").replace("_", " ")
        )
        return f"{self.context}: {label} = {value} " + " ".join(f"[{i}]" for i in self.evidence_ids)


METRICS = {
    "revenue": "revenue",
    "days": "days in period",
    "revenue_per_day": "average daily revenue",
    "revenue_change": "revenue difference",
    "revenue_per_day_change_pct": "average daily revenue change (%)",
    "units": "units sold",
    "orders": "distinct orders",
    "customers": "distinct customers",
    "eligible_customers": "eligible customers",
    "inactive_customers": "inactive customers",
    "inactivity_share": "inactivity share (fraction, not monthly churn incidence)",
}
RATIOS = {
    "units_per_order": ("units", "orders"),
    "revenue_per_unit": ("revenue", "units"),
    "revenue_per_order": ("revenue", "orders"),
}


def number(value: Scalar) -> float | int | None:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def ratio(numerator: Scalar, denominator: Scalar) -> float | None:
    n, d = number(numerator), number(denominator)
    return round(n / d, 6) if n is not None and d is not None and d > 0 else None


def metric_catalog(evidence: list[Evidence], intent: Intent | None = None) -> dict[str, Metric]:
    catalog: dict[str, Metric] = {}
    for item in evidence:
        period = f"{item.request.start} to {item.request.end} UTC (end exclusive)"
        filters = "; ".join(
            text
            for text in (
                "brands: " + ", ".join(item.request.brands) if item.request.brands else "",
                "product IDs: " + ", ".join(map(str, item.request.product_ids))
                if item.request.product_ids
                else "",
                f"customer ID: {item.request.customer_id}" if item.request.customer_id else "",
            )
            if text
        )
        for index, original_row in enumerate(item.rows):
            row = dict(original_row)
            # SQL SUM(empty set) is NULL. Counts prove an empty population, unlike
            # missing prices on nonempty sales. Preserve raw evidence unchanged.
            if (
                item.request.kind == "sales"
                and row.get("revenue") is None
                and all(row.get(name) == 0 for name in ("units", "orders", "customers"))
            ):
                row["revenue"] = 0

            group = ", ".join(
                f"{k}: {row[k]}"
                for k in (
                    "product_id",
                    "product_name",
                    "brand",
                    "category",
                    "month",
                    "state",
                    "user_id",
                    "cohort",
                    "period",
                )
                if k in row
            )
            context = (
                f"{item.scope}; {period}"
                + (f"; {filters}" if filters else "")
                + (f"; {group}" if group else "")
            )
            values = {key: number(row[key]) for key in METRICS if key in row}
            if item.request.kind == "sales":
                values.update(
                    {
                        name: ratio(row.get(n), row.get(d))
                        for name, (n, d) in RATIOS.items()
                        if n in row and d in row
                    }
                )
            if item.request.kind == "sales" and item.request.dimension == Dimension.TOTAL:
                days = (item.request.end - item.request.start).days
                values["days"] = days
                values["revenue_per_day"] = ratio(row.get("revenue"), days)
            for name, value in values.items():
                key = f"{item.id}.r{index}.{name}"
                catalog[key] = Metric(key, name, value, context, (item.id,))
        for index, comparison in enumerate(item.comparisons):
            key = f"{item.id}.c{index}.percentage_point_change"
            context = f"{item.scope}; {period}; cohort {comparison['cohort']}; inactivity share {comparison['direction']}"
            catalog[key] = Metric(
                key,
                "percentage_point_change",
                number(comparison.get("percentage_point_change")),
                context,
                (item.id,),
            )
    # Compare totals only when filters, scope and metric definitions are identical.
    totals = [
        e
        for e in evidence
        if e.request.kind == "sales" and e.request.dimension == Dimension.TOTAL and len(e.rows) == 1
    ]
    for left, right in combinations(totals, 2):
        old, new = sorted((left, right), key=lambda e: e.request.start)
        if intent and intent.period and intent.comparison:
            pair = {(e.request.start, e.request.end): e for e in (left, right)}
            current = pair.get((intent.period.start, intent.period.end))
            baseline = pair.get((intent.comparison.start, intent.comparison.end))
            if current is None or baseline is None:
                continue
            old, new = baseline, current
        exclusions = {"start", "end", "limit", "rank_by"}
        if (
            old.scope != new.scope
            or old.definitions != new.definitions
            or old.request.model_dump(exclude=exclusions)
            != new.request.model_dump(exclude=exclusions)
        ):
            continue
        for name in ("revenue", "units", "orders", "customers"):
            baseline, current = (
                catalog[f"{old.id}.r0.{name}"].value if f"{old.id}.r0.{name}" in catalog else None,
                catalog[f"{new.id}.r0.{name}"].value if f"{new.id}.r0.{name}" in catalog else None,
            )
            value = (
                round((current / baseline - 1) * 100, 4)
                if baseline is not None and baseline > 0 and current is not None
                else None
            )
            key = f"{new.id}.vs.{old.id}.{name}_change_pct"
            context = f"{new.scope}; {new.request.start} to {new.request.end} versus {old.request.start} to {old.request.end} UTC; totals, not daily rates"
            catalog[key] = Metric(key, f"{name}_change_pct", value, context, (new.id, old.id))
        old_units, new_units = number(old.rows[0].get("units")), number(new.rows[0].get("units"))
        old_revenue, new_revenue = (
            catalog[f"{old.id}.r0.revenue"].value if f"{old.id}.r0.revenue" in catalog else None,
            catalog[f"{new.id}.r0.revenue"].value if f"{new.id}.r0.revenue" in catalog else None,
        )
        old_days = (old.request.end - old.request.start).days
        new_days = (new.request.end - new.request.start).days
        difference = (
            round(new_revenue - old_revenue, 2)
            if old_revenue is not None and new_revenue is not None
            else None
        )
        daily_change = (
            round(((new_revenue / new_days) / (old_revenue / old_days) - 1) * 100, 4)
            if old_revenue is not None and old_revenue > 0 and new_revenue is not None
            else None
        )
        for name, value in (
            ("revenue_change", difference),
            ("revenue_per_day_change_pct", daily_change),
        ):
            key = f"{new.id}.vs.{old.id}.{name}"
            catalog[key] = Metric(
                key,
                name,
                value,
                f"{new.scope}; {new.request.start} to {new.request.end} versus {old.request.start} to {old.request.end} UTC; {new_days} versus {old_days} calendar days",
                (new.id, old.id),
            )
        if old_units and new_units and old_revenue is not None and new_revenue is not None:
            volume = round((new_units - old_units) * old_revenue / old_units, 2)
            unit_value = round(new_revenue - old_revenue - volume, 2)
            for name, amount in (
                ("volume_contribution", volume),
                ("unit_value_contribution", unit_value),
            ):
                key = f"{new.id}.vs.{old.id}.{name}"
                catalog[key] = Metric(
                    key,
                    name,
                    amount,
                    f"{new.scope}; {old.request.start} to {old.request.end} to {new.request.start} to {new.request.end}; arithmetic revenue decomposition, not causal attribution",
                    (new.id, old.id),
                )
    return catalog


ACTION_METRICS = {
    "cross_sell_test": {"units_per_order"},
    "demand_investigation": {"revenue", "orders", "customers", "units"},
    "assortment_review": {"revenue", "units", "customers"},
    "retention_test": {"inactivity_share"},
}
ACTION_TEXT = {
    "cross_sell_test": (
        "Test optional complementary-product bundles against a control group; compare units per order and check profitability before rollout.",
    ),
    "demand_investigation": (
        "Investigate demand using promotion, availability and calendar records; compare the selected measure before choosing an intervention.",
    ),
    "assortment_review": (
        "Review assortment using the cited sales measure; obtain cost and stock data before increasing inventory. Sales do not establish margin.",
    ),
    "retention_test": (
        "Test an authorized retention intervention against a control group; monitor the same inactivity definition and eligible population.",
    ),
}
HYPOTHESIS_TEXT = {
    "seasonality": "Compare the highlighted months with the same calendar months in earlier years before attributing the pattern to seasonality.",
    "promotion": "Compare campaign dates and discounts for the highlighted results with a suitable comparison group before attributing the pattern to promotions.",
    "availability": "Check stock levels and stockout dates for the highlighted results before attributing the pattern to availability.",
    "product_mix": "Compare product-level sales and prices across the cited periods before attributing the pattern to a change in product mix.",
}


def action_observation(metric: Metric, evidence: list[Evidence]) -> str:
    """Describe a selected baseline or monthly range from verified values, without causal claims."""
    item = next(e for e in evidence if e.id in metric.evidence_ids)
    if item.request.dimension == Dimension.MONTH:
        monthly = [(row, number(row.get(metric.name))) for row in item.rows]
        defined = [(row, value) for row, value in monthly if value is not None]
        if len(defined) >= 2:
            low = min(defined, key=lambda pair: pair[1])
            high = max(defined, key=lambda pair: pair[1])
            label = METRICS.get(metric.name, metric.name.replace("_", " "))
            if low[1] == high[1]:
                return f"Monthly {label} was {metric_value(metric.name, low[1])} in every shown month. [{item.id}]"
            return (
                f"Monthly {label} ranged from {metric_value(metric.name, low[1])} in "
                f"{escape_cell(low[0].get('month'))} to {metric_value(metric.name, high[1])} in "
                f"{escape_cell(high[0].get('month'))}. [{item.id}]"
            )
    return metric.statement()


def validate_narrative(
    narrative: Narrative, evidence: list[Evidence], intent: Intent | None = None
) -> list[str]:
    catalog = metric_catalog(evidence, intent)
    ids = {e.id for e in evidence}
    issues: list[str] = []
    if not narrative.facts and any(item.rows for item in evidence):
        issues.append("missing_fact_metrics")
    if any(key not in catalog for key in narrative.facts):
        issues.append("unknown_fact_metric")
    if any(not set(h.evidence_ids) <= ids for h in narrative.hypotheses):
        issues.append("unknown_hypothesis_evidence")
    for hypothesis in narrative.hypotheses:
        cited = [e for e in evidence if e.id in hypothesis.evidence_ids]
        if (
            hypothesis.mechanism == "product_mix"
            and cited
            and (
                any(e.request.product_ids or e.request.customer_id for e in cited)
                or all(e.request.dimension == Dimension.PRODUCT for e in cited)
            )
        ):
            issues.append("incompatible_product_mix_hypothesis")
    actions_required = intent.actions if intent else False
    if actions_required and not narrative.actions:
        issues.append("missing_actions")
    if intent and not intent.actions and narrative.actions:
        issues.append("unrequested_actions")
    if intent:
        issues.extend(completion_issues(intent, evidence, narrative.facts))
    window = (
        (intent.action_period.start, intent.action_period.end)
        if intent and intent.action_period
        else None
    )
    for action in narrative.actions:
        metric = catalog.get(action.metric_id)
        if metric is None or metric.name not in ACTION_METRICS[action.kind] or metric.value is None:
            issues.append("invalid_action_measure")
        if window is None or (action.start, action.end) != window:
            issues.append("action_period_mismatch_or_ambiguous")
        monthly = [
            e for e in evidence if e.request.dimension == Dimension.MONTH and not empty_sales(e)
        ]
        if (
            action.kind == "demand_investigation"
            and monthly
            and metric
            and not any(e.id in metric.evidence_ids for e in monthly)
        ):
            issues.append("demand_action_requires_monthly_evidence")
    return sorted(set(issues))


def required_facts(intent: Intent, evidence: list[Evidence]) -> list[str]:
    """Select requested measures from verified evidence, without another model decision."""
    catalog = metric_catalog(evidence, intent)
    facts: list[str] = []
    for item in evidence:
        requirements = (
            intent.requirements
            if intent.period
            and item.request.start == intent.period.start
            and item.request.end == intent.period.end
            else intent.comparison_requirements
        )
        for req in requirements:
            if req.dimension != item.request.dimension:
                continue
            if (
                req.dimension not in (Dimension.TOTAL, Dimension.MONTH)
                and intent.kind == "sales"
                and item.request.rank_by != req.metric
            ):
                continue
            count = (
                len(item.rows)
                if req.dimension == Dimension.MONTH or intent.kind == "churn"
                else min(req.minimum_rows, len(item.rows))
            )
            names = list(dict.fromkeys([req.metric, *req.measures]))
            if intent.kind == "churn":
                names += ["eligible_customers", "inactive_customers"]
            facts += [f"{item.id}.r{i}.{name}" for i in range(count) for name in names]
        if item.request.kind == "churn":
            facts += [
                f"{item.id}.c{i}.percentage_point_change" for i in range(len(item.comparisons))
            ]
    facts += [
        key
        for key, metric in catalog.items()
        if ".vs." in key and metric.name in intent.comparison_metrics
    ]
    return list(dict.fromkeys(key for key in facts if key in catalog))


def render_narrative(
    narrative: Narrative, evidence: list[Evidence], intent: Intent | None = None
) -> str:
    catalog = metric_catalog(evidence, intent)
    parts = ["Verified findings"]
    displayed: set[str] = set()
    for item in evidence:
        if item.request.kind == "churn":
            parts += ["", churn_findings(item)]
            displayed.update(key for key in catalog if key.startswith(item.id + "."))
    sales = [item for item in evidence if item.request.kind == "sales"]
    # Required outputs lead the answer; auxiliary queries stay available in /details.
    if intent and intent.requirements:
        sales = [
            item
            for item in sales
            if any(
                item.request.dimension == req.dimension
                and (
                    req.dimension
                    not in (
                        Dimension.PRODUCT,
                        Dimension.CUSTOMER,
                        Dimension.BRAND,
                        Dimension.CATEGORY,
                        Dimension.STATE,
                    )
                    or item.request.rank_by == req.metric
                )
                for req in intent.requirements
            )
        ]
    sales.sort(
        key=lambda item: (
            bool(intent and intent.period and item.request.start != intent.period.start),
            item.request.start,
            item.request.end,
            item.scope,
        )
    )
    requested_sales = tuple(sales)
    if intent and intent.period and intent.comparison:
        totals = [
            item
            for item in sales
            if item.request.dimension == Dimension.TOTAL
            and (item.request.start, item.request.end)
            in (
                (intent.period.start, intent.period.end),
                (intent.comparison.start, intent.comparison.end),
            )
        ]
        if len(totals) == 2:
            new = next(
                item
                for item in totals
                if (item.request.start, item.request.end)
                == (intent.period.start, intent.period.end)
            )
            old = next(
                item
                for item in totals
                if (item.request.start, item.request.end)
                == (intent.comparison.start, intent.comparison.end)
            )
            prefix = f"{new.id}.vs.{old.id}"
            if f"{prefix}.revenue_change" in catalog:
                names = [
                    name
                    for name in (
                        "revenue",
                        "units",
                        "orders",
                        "customers",
                        "days",
                        "revenue_per_day",
                    )
                    if any(f"{item.id}.r0.{name}" in narrative.facts for item in totals)
                ]
                parts += [
                    "",
                    comparison_findings(
                        old, new, {key: metric.value for key, metric in catalog.items()}, names
                    ),
                ]
                displayed.update(
                    key
                    for key in narrative.facts
                    if any(key == f"{item.id}.r0.{name}" for item in totals for name in names)
                    or key in {f"{prefix}.{name}_change_pct" for name in names}
                    or key == f"{prefix}.revenue_change"
                )
                sales = [item for item in sales if item not in totals]
    contexts: set[tuple[str, object, object]] = set()
    for item in sales:
        keys = [key for key in narrative.facts if key.startswith(item.id + ".r")]
        if not keys and not empty_sales(item):
            continue
        context = (item.scope, item.request.start, item.request.end)
        if context not in contexts:
            parts += ["", f"**{escape_cell(item.scope)}** · {period_label(item)}", ""]
            contexts.add(context)
        if item.request.brands and ", ".join(item.request.brands) != item.scope:
            parts.append(
                "Selected brands: " + ", ".join(escape_cell(b) for b in item.request.brands)
            )
        if item.request.product_ids:
            parts.append("Selected product IDs: " + ", ".join(map(str, item.request.product_ids)))
        if item.request.customer_id:
            parts.append(f"Selected customer ID: {item.request.customer_id}")
        if empty_sales(item):
            parts += [
                "No qualifying sales were found for this brand scope and period.",
                f"Source: [{item.id}].",
            ]
            displayed.update(keys)
            continue
        if item.request.dimension == Dimension.TOTAL:
            parts.append("### Overall performance")
            parts += [
                f"- {METRICS.get(catalog[key].name, catalog[key].name.replace('_', ' '))} = {metric_value(catalog[key].name, catalog[key].value)} "
                + " ".join(f"[{e}]" for e in catalog[key].evidence_ids)
                for key in keys
            ]
        else:
            # Use the same selected columns for each selected row. A model omitting
            # an optional cell must not make an available source value look missing.
            row_prefixes = list(dict.fromkeys(key.rsplit(".", 1)[0] for key in keys))
            names = list(dict.fromkeys(catalog[key].name for key in keys))
            table_values = {
                f"{prefix}.{name}": catalog[f"{prefix}.{name}"].value
                for prefix in row_prefixes
                for name in names
                if f"{prefix}.{name}" in catalog
            }
            parts.append(table_findings(item, table_values))
        displayed.update(keys)
    previous_context = ""
    for key in narrative.facts:
        if key in displayed or catalog[key].name in (
            "volume_contribution",
            "unit_value_contribution",
        ):
            continue
        # Hide unrequested sales row blocks, not comparisons or churn findings.
        if intent and any(
            key.startswith(item.id + ".r") and item not in requested_sales
            for item in evidence
            if item.request.kind == "sales"
        ):
            continue
        metric = catalog[key]
        if metric.context != previous_context:
            parts.append("\n" + metric.context)
            previous_context = metric.context
        parts.append("- " + metric.statement().removeprefix(metric.context + ": "))
    if narrative.hypotheses and not narrative.actions:
        parts.append("\n### What to check")
        parts += [
            "- " + HYPOTHESIS_TEXT[h.mechanism] + " " + " ".join(f"[{i}]" for i in h.evidence_ids)
            for h in narrative.hypotheses
        ]
    if narrative.actions:
        parts.append("\n### Suggested next steps")
        for action in narrative.actions:
            (text,) = ACTION_TEXT[action.kind]
            metric = catalog[action.metric_id]
            linked = [
                h for h in narrative.hypotheses if set(h.evidence_ids) & set(metric.evidence_ids)
            ]
            if action.kind == "demand_investigation" and linked:
                text = " ".join(HYPOTHESIS_TEXT[h.mechanism] for h in linked)
            period = f"{action.start:%d %b %Y} to {action.end - timedelta(days=1):%d %b %Y} (UTC)"
            parts += [
                f"- **{period}:** {action_observation(metric, evidence)} {text}",
            ]
    if narrative.hypotheses or narrative.actions:
        parts.append(
            "\nThese are investigation or test proposals. The data does not establish causes or justify a numeric target."
        )
    return "\n".join(parts)


def fallback_text(evidence: list[Evidence], intent: Intent | None = None) -> str:
    """Keep all returned periods/rows readable even when narrative validation fails."""
    catalog = metric_catalog(evidence, intent)
    lines = [
        "Report narrative could not be validated within this question's limits. Verified figures are shown below; unsupported explanations and actions were withheld."
    ]
    for item in evidence:
        if item.request.kind == "churn":
            lines += ["", churn_findings(item)]
            continue
        lines += ["", f"**{escape_cell(item.scope)}** · {period_label(item)}"]
        if item.request.customer_id:
            lines.append(f"Customer ID: {item.request.customer_id}")
        if item.request.product_ids:
            lines.append("Selected product IDs: " + ", ".join(map(str, item.request.product_ids)))
        if item.request.brands:
            lines.append(
                "Selected brands: " + ", ".join(escape_cell(b) for b in item.request.brands)
            )
        if empty_sales(item):
            lines += [
                "No qualifying sales were found for this brand scope and period.",
                f"Source: [{item.id}].",
            ]
            continue
        names = list(
            dict.fromkeys(
                [
                    req.metric
                    for req in intent.requirements
                    if req.dimension == item.request.dimension
                ]
                if intent
                else []
            )
        ) or [item.request.rank_by]
        if item.request.dimension == Dimension.TOTAL:
            for name in names:
                metric = catalog.get(f"{item.id}.r0.{name}")
                if metric:
                    lines.append(
                        f"- {METRICS.get(name, name)} = {metric_value(name, metric.value)} [{item.id}]"
                    )
        else:
            values = {
                key: metric.value
                for key, metric in catalog.items()
                if key.startswith(item.id + ".r") and metric.name in names
            }
            lines += [table_findings(item, values)]
    if not evidence:
        lines.append("No matching data or eligible cohort; no values inferred.")
    return "\n".join(lines)


def revenue_driver_details(evidence: list[Evidence], intent: Intent | None = None) -> str:
    insights = [
        metric
        for metric in metric_catalog(evidence, intent).values()
        if metric.name in ("volume_contribution", "unit_value_contribution")
    ]
    if not insights:
        return ""
    return "\n".join(
        [
            "Calculated revenue drivers (arithmetic attribution, not proven causes)",
            "Unit value can reflect product mix as well as prices.",
            *["- " + metric.statement() for metric in insights],
        ]
    )
