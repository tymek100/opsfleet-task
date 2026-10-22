"""Evidence-bound report language: model selection, deterministic facts and rendering.

This deliberately supports a small analytical vocabulary, not arbitrary prose entailment.
"""

import math
import re
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from retail_agent.models import Dimension, Evidence, Scalar


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
    target: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_serializer("start", "end")
    def serialize_date(self, value: date) -> str:
        # ADK 2.12's structured-response tool uses model_dump() before json.dumps().
        return value.isoformat()


class Narrative(Contract):
    facts: list[str] = Field(min_length=1, max_length=30)
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


def metric_catalog(evidence: list[Evidence]) -> dict[str, Metric]:
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
        for index, row in enumerate(item.rows):
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
        exclusions = {"start", "end", "limit", "rank_by"}
        if (
            old.request.end != new.request.start
            or old.scope != new.scope
            or old.definitions != new.definitions
            or old.request.model_dump(exclude=exclusions)
            != new.request.model_dump(exclude=exclusions)
        ):
            continue
        for name in ("revenue", "units", "orders", "customers"):
            baseline, current = number(old.rows[0].get(name)), number(new.rows[0].get(name))
            value = (
                round((current / baseline - 1) * 100, 4)
                if baseline is not None and baseline > 0 and current is not None
                else None
            )
            key = f"{new.id}.vs.{old.id}.{name}_change_pct"
            context = f"{new.scope}; {new.request.start} to {new.request.end} versus {old.request.start} to {old.request.end} UTC; totals, not daily rates"
            catalog[key] = Metric(key, f"{name}_change_pct", value, context, (new.id, old.id))
    return catalog


def action_window(question: str, evidence: list[Evidence]) -> tuple[date, date] | None:
    """Resolve explicit calendar quarters; otherwise use the quarter after evidence.

    Unsupported/ambiguous action periods fail closed instead of trusting model dates.
    """
    quarters = list(re.finditer(r"\bQ([1-4])(?:\s+(20\d{2}))?\b", question, re.I))
    years = {int(m.group(2)) for m in quarters if m.group(2)}
    candidates = [
        m
        for m in quarters
        if (
            re.search(
                r"(?:actions?|action items?|recommendations?|plan|targets?)\s+(?:for|in)\s*$",
                question[: m.start()],
                re.I,
            )
            or re.match(
                r"\s+(?:actions?|action items?|recommendations?|plan|targets?)\b",
                question[m.end() :],
                re.I,
            )
        )
    ]
    if len(candidates) == 1:
        target = candidates[0]
        q = int(target.group(1))
        year = (
            int(target.group(2))
            if target.group(2)
            else next(iter(years))
            if len(years) == 1
            else None
        )
        # An omitted year across a Q4 -> Q1 rollover is materially ambiguous.
        if not target.group(2) and any(int(m.group(1)) > q for m in quarters if m is not target):
            return None
        if year:
            return date(year, q * 3 - 2, 1), date(year + (q == 4), q * 3 + 1 if q < 4 else 1, 1)
    if not candidates and re.search(r"\bnext quarter\b", question, re.I) and evidence:
        end = max(e.request.end for e in evidence)
        if end.day == 1 and end.month in (1, 4, 7, 10):
            return end, date(
                end.year + (end.month == 10), end.month + 3 if end.month < 10 else 1, 1
            )
    return None


ACTION_METRICS = {
    "cross_sell_test": {"units_per_order"},
    "demand_investigation": {"revenue", "orders", "customers", "units"},
    "assortment_review": {"revenue", "units", "customers"},
    "retention_test": {"inactivity_share"},
}
ACTION_TEXT = {
    "cross_sell_test": (
        "Test optional complementary-product bundles against a control group; compare units per order and check profitability before rollout.",
        "Merchandising",
    ),
    "demand_investigation": (
        "Investigate demand using promotion, availability and calendar records; compare the selected measure before choosing an intervention.",
        "Operations and Analytics",
    ),
    "assortment_review": (
        "Review assortment using the cited sales measure; obtain cost and stock data before increasing inventory. Sales do not establish margin.",
        "Category Management",
    ),
    "retention_test": (
        "Test an authorized retention intervention against a control group; monitor the same inactivity definition and eligible population.",
        "Customer Retention",
    ),
}
HYPOTHESIS_TEXT = {
    "seasonality": "Seasonality could contribute; compare the same periods across multiple years before drawing a conclusion.",
    "promotion": "Promotional activity could contribute; obtain campaign timing and a comparison group to investigate.",
    "availability": "Product availability could contribute; obtain stockout and replenishment records to investigate.",
    "product_mix": "Product mix could contribute; compare item-level price and volume composition across the periods to investigate.",
}


def validate_narrative(narrative: Narrative, evidence: list[Evidence], question: str) -> list[str]:
    catalog = metric_catalog(evidence)
    ids = {e.id for e in evidence}
    issues: list[str] = []
    if any(key not in catalog for key in narrative.facts):
        issues.append("unknown_fact_metric")
    if any(not set(h.evidence_ids) <= ids for h in narrative.hypotheses):
        issues.append("unknown_hypothesis_evidence")
    if (
        re.search(r"\b(actions?|recommendations?|report)\b", question, re.I)
        and not narrative.actions
    ):
        issues.append("missing_actions")
    window = action_window(question, evidence)
    for action in narrative.actions:
        metric = catalog.get(action.metric_id)
        if metric is None or metric.name not in ACTION_METRICS[action.kind] or metric.value is None:
            issues.append("invalid_action_measure")
        if window is None or (action.start, action.end) != window:
            issues.append("action_period_mismatch_or_ambiguous")
        if (
            metric
            and metric.name == "inactivity_share"
            and action.target is not None
            and action.target > 1
        ):
            issues.append("fraction_target_out_of_range")
    return sorted(set(issues))


def render_narrative(narrative: Narrative, evidence: list[Evidence]) -> str:
    catalog = metric_catalog(evidence)
    parts = ["Verified findings"]
    parts += ["- " + catalog[key].statement() for key in narrative.facts]
    if narrative.hypotheses:
        parts.append(
            "\nUnverified hypotheses — these explanations have not been established by the cited observations."
        )
        parts += [
            "- "
            + HYPOTHESIS_TEXT[h.mechanism]
            + " Observations to investigate: "
            + " ".join(f"[{i}]" for i in h.evidence_ids)
            for h in narrative.hypotheses
        ]
    if narrative.actions:
        parts.append(
            "\nProposed actions — owners and targets are proposals, not forecasts or proven outcomes."
        )
        for action in narrative.actions:
            text, owner = ACTION_TEXT[action.kind]
            metric = catalog[action.metric_id]
            parts.append(
                f"- {action.start} to {action.end} UTC (end exclusive): {text} Proposed owner: {owner}. Baseline / success measure: {metric.statement()}."
                + (
                    f" Proposed target: {action.target:g} for {metric.name} in this action period; feasibility is unverified."
                    if action.target is not None
                    else " Establish a target after the investigation/test design."
                )
            )
    parts.append(
        "\nLimitations: authorized transaction data supports descriptive findings, not causes, profit margins or forecasts. Definitions and source periods follow; counts across groups may overlap."
    )
    for e in evidence:
        parts.append(f"[{e.id}] {e.definitions}")
    return "\n".join(parts)


def fallback_text(evidence: list[Evidence]) -> str:
    catalog = metric_catalog(evidence)
    lines = [
        "Report narrative could not be validated within this question's limits. Verified figures are shown below; unsupported explanations and actions were withheld."
    ]
    lines.extend("- " + metric.statement() for metric in list(catalog.values())[:12])
    if not catalog:
        lines.append("No matching data or eligible cohort; no values inferred.")
    return "\n".join(lines)
