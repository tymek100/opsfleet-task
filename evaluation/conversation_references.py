"""Independent references for the authored conversations, bound to captured source data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from evaluation.manual_reference import during, qualifying, serializable, summarize
from evaluation.models import Criterion, Fact, TurnReference
from evaluation.runners.artifacts import digest, read_json

REFERENCE_VERSION = "authored-conversations-v2-workspace"


def decimal(value) -> Decimal:
    return Decimal(str(value))


def percent(numerator, denominator):
    return (
        None if denominator in (None, 0, "0") else decimal(numerator) / decimal(denominator) * 100
    )


def clean(value):
    return json.loads(json.dumps(value, default=serializable))


@dataclass
class Snapshot:
    directory: Path
    manifest: dict
    summary: dict
    transactions: list[dict]

    @classmethod
    def load(cls, directory: Path):
        manifest = read_json(directory / "manifest.json")
        required = {"transactions.json", "products.json", "states.json", "summary.json"}
        if (
            manifest.get("status") != "completed"
            or not required <= manifest.get("files_sha256", {}).keys()
        ):
            raise ValueError("Reference capture is incomplete")
        for name in required:
            if digest(directory / name) != manifest["files_sha256"][name]:
                raise ValueError(f"Reference file was changed: {name}")
        transactions, products, states = (
            read_json(directory / name)
            for name in ("transactions.json", "products.json", "states.json")
        )
        # Verify stored aggregates independently of any answer or agent SQL.
        summary = clean(summarize(transactions, products, states, tuple(manifest["brands"])))
        if summary != read_json(directory / "summary.json"):
            raise ValueError("Stored reference summary does not match its raw source rows")
        return cls(directory, manifest, summary, transactions)

    def provenance(self):
        return {
            "reference_version": REFERENCE_VERSION,
            "definition_sha256": digest(Path(__file__)),
            "source_dataset": self.manifest["source_dataset"],
            "captured_at": self.manifest["created_at"],
            "snapshot_at": self.manifest.get("snapshot_at"),
            "point_in_time_consistent": self.manifest["point_in_time_consistent"],
            "files_sha256": self.manifest["files_sha256"],
            "reference_implementation_sha256": self.manifest.get("reference_implementation_sha256"),
            "human_reviewed": False,
        }


@dataclass
class TurnSpec:
    reference: TurnReference
    # Selection catalogs and conditional metric bindings are never sent to the analyst/judge.
    selections: list[dict] = field(default_factory=list)
    lookups: dict[str, dict] = field(default_factory=dict)
    dependent_on_initial: bool = False

    def export(self):
        return {
            "reference": self.reference.model_dump(mode="json"),
            "selection_rules": self.selections,
            "conditional_facts": self.lookups,
            "follow_up_rule": "Resolve against the products/categories actually shown in the initial answer."
            if self.dependent_on_initial
            else None,
        }


def reference_for(
    scenario, number: int, snapshot: Snapshot, *, initial: dict | None = None
) -> TurnSpec:
    """The default export shows canonical ties; grading resolves permitted alternative ties."""
    if scenario.id not in {f"scenario-{i:02d}" for i in range(1, 21)} or number not in (1, 2):
        raise ValueError("No reference specification for this conversation turn")
    brand = scenario.requested_brand
    data = snapshot.summary[brand]
    if scenario.id == "scenario-19":
        if snapshot.manifest.get("geography_scope") != "all brands":
            raise ValueError(
                "Capture fresh all-brand geography references for this workspace suite"
            )
        brand = "all brands"
    q1, q4 = (data["qualifying"][period] for period in ("q1_2026", "q4_2025"))
    facts: list[Fact] = []
    criteria = [
        Criterion(id=f"requirement-{i}", kind="semantic", description=check)
        for i, check in enumerate(scenario.checks, 1)
        if check.startswith("Both:")
        or check.startswith("Initial:" if number == 1 else "Follow-up:")
    ]
    reference = TurnReference(
        criteria=criteria,
        reference_answer="Independent facts and behavioral requirements below define acceptable answers; wording is unrestricted.",
        reference_procedure="Independent Decimal/set aggregation over hash-verified source captures, never the agent's queries or generated answers.",
    )
    spec = TurnSpec(reference)

    def fact(key, value, metric=None, *, entity="authorized brand", period="Q1 2026", unit="count"):
        facts.append(
            Fact(
                id=key,
                value=None if value is None else str(value),
                value_type="null" if value is None else "number",
                source_key=key,
                metric=metric or key.replace("_", " "),
                entity=entity,
                period=period,
                scope=brand,
                unit=unit,
                tolerance=Decimal("0") if unit == "count" else Decimal("0.011"),
            )
        )

    def money(key, value, **kwargs):
        fact(key, value, unit="source currency unspecified", **kwargs)

    def ratio_fact(key, value, **kwargs):
        fact(key, value, unit="percentage points", **kwargs)

    def products(metric):
        rows = data["all_product_metrics_by_revenue"]
        return sorted(
            rows,
            key=lambda row: (row[metric] is None, -decimal(row[metric] or 0), row["product_id"]),
        )

    def categories(metric):
        return sorted(
            data["category_metrics_and_overlap"]["all_categories_by_revenue"],
            key=lambda row: (-decimal(row[metric] or 0), str(row["category"])),
        )

    def select(
        prefix,
        rows,
        size,
        rank_by,
        metrics,
        *,
        fixed=False,
        unordered=False,
        label_field="product_name",
        key_field="product_id",
    ):
        rows = clean(rows)
        size = min(size, len(rows))
        if not fixed and size:
            boundary = (
                abs(decimal(rows[size - 1][rank_by] or 0))
                if rank_by == "change"
                else decimal(rows[size - 1][rank_by] or 0)
            )
            rows = [
                r
                for r in rows
                if (
                    abs(decimal(r[rank_by] or 0))
                    if rank_by == "change"
                    else decimal(r[rank_by] or 0)
                )
                >= boundary
            ]
        entries = [
            {"key": str(r[key_field]), "label": str(r[label_field]), "metrics": r} for r in rows
        ]
        rule = {
            "name": prefix,
            "size": size,
            "rank_by": rank_by,
            "fixed_order": fixed,
            "unordered": unordered,
            "rows": entries,
        }
        spec.selections.append(rule)
        for index, row in enumerate(entries[:size], 1):
            selector = f"{prefix}_{index}_entity"
            facts.append(
                Fact(
                    id=selector,
                    value=row["label"],
                    value_type="text",
                    source_key=selector,
                    metric="Copy the entity label or ID actually printed in this position, without inferring an unprinted ID.",
                    entity=f"Position {index} in {prefix.replace('_', ' ')}",
                    scope=brand,
                    unit="printed label or ID",
                )
            )
            for metric, unit, period in metrics:
                key = f"{prefix}_{index}_{metric}"
                value = row["metrics"][metric]
                fact(
                    key,
                    value,
                    metric,
                    entity=f"Entity at position {index} in {prefix.replace('_', ' ')}",
                    unit=unit,
                    period=period,
                )
                spec.lookups[key] = {"selection": prefix, "position": index - 1, "metric": metric}
        return entries[:size]

    def initial_rows(prefix, canonical, rows, key):
        spec.dependent_on_initial = True
        if initial is None:
            return canonical
        identifiers = initial.get(prefix)
        if identifiers is None:
            return []
        catalog = {str(row[key]): row for row in rows}
        return [catalog[item] for item in identifiers if item in catalog]

    currency = "source currency unspecified"
    revenue_metric = [("revenue", currency, "Q1 2026")]
    customers_metric = [("customers", "count", "Q1 2026")]
    case = scenario.id

    if case == "scenario-01":
        if number == 1:
            select("revenue_ranking", products("revenue"), 5, "revenue", revenue_metric)
            select("customer_ranking", products("customers"), 5, "customers", customers_metric)
        else:
            spec.dependent_on_initial = True
            left = (initial or {}).get(
                "revenue_ranking", [str(r["product_id"]) for r in data["top_five_by_revenue"]]
            )
            right = (initial or {}).get(
                "customer_ranking", [str(r["product_id"]) for r in data["top_five_by_customers"]]
            )
            overlap = sorted(set(left) & set(right))
            fact(
                "overlap_count",
                len(overlap),
                "number of products appearing in both previously displayed lists",
            )
            names = {str(r["product_id"]): r["product_name"] for r in products("revenue")}
            reference.criteria.append(
                Criterion(
                    id="overlap-membership",
                    kind="semantic",
                    description=f"The intersection of the previously displayed lists must be accurately described: {[names[k] for k in overlap]}. Do not infer price, unit-volume or causal facts from this membership alone.",
                )
            )
    elif case in {"scenario-02", "scenario-14"}:
        if case == "scenario-14" and number == 1:
            reference.allowed_outcomes = ["clarification"]
            reference.answerability = "clarification_required"
        elif case == "scenario-02" and number == 2:
            pass
        else:
            metrics = (
                ("revenue", "orders")
                if case == "scenario-14"
                else ("revenue", "customers", "orders", "aov")
            )
            for metric in metrics:
                unit = "count" if metric in {"orders", "customers"} else currency
                fact(f"q4_{metric}", q4[metric], metric, period="Q4 2025", unit=unit)
                fact(f"q1_{metric}", q1[metric], metric, unit=unit)
                ratio_fact(
                    f"change_{metric}",
                    data["q4_to_q1_changes"][metric]["percent_change"],
                    metric=f"Q4-to-Q1 percentage change in {metric}",
                    period="Q4 2025 to Q1 2026",
                )
    elif case == "scenario-03":
        limit = 3 if number == 1 else 2
        rows = data["category_contributions"]["all_by_absolute_change"]
        if number == 2:
            rows = initial_rows("category_changes", rows[:3], rows, "category")[:2]
        select(
            "category_changes",
            rows,
            limit,
            "change",
            [("change", currency, "Q4 2025 to Q1 2026")],
            label_field="category",
            key_field="category",
            fixed=number == 2,
        )
        money(
            "other_change",
            data["category_contributions"][
                "other_after_top_three" if limit == 3 else "other_after_top_two"
            ],
            period="Q4 2025 to Q1 2026",
        )
        # Recompute Other from the independently verified selected categories when ties differ.
        spec.lookups["other_change"] = {
            "remainder_of": "category_changes",
            "total": data["category_contributions"]["total_change"],
            "metric": "change",
        }
        money(
            "total_change",
            data["category_contributions"]["total_change"],
            period="Q4 2025 to Q1 2026",
        )
    elif case == "scenario-04":
        rows = products("revenue")
        if number == 1:
            metrics = [
                *revenue_metric,
                ("units", "count", "Q1 2026"),
                ("average_realized_unit_price", currency, "Q1 2026"),
            ]
            select("products", rows, 5, "revenue", metrics)
        else:
            selected = initial_rows("products", rows[:5], rows, "product_id")
            select(
                "products",
                selected,
                len(selected),
                "revenue",
                [("orders", "count", "Q1 2026"), ("aov", currency, "Q1 2026")],
                fixed=True,
                unordered=True,
            )
    elif case == "scenario-05":
        cohorts = data["customer_cohorts"]
        if number == 1:
            fact("repeat_customers", cohorts["q1_repeat_order_count"])
            share = cohorts["q1_repeat_customer_share"]
            ratio_fact("repeat_customer_share", None if share is None else decimal(share) * 100)
        else:
            for label, key in (
                ("repeat", "q1_repeat_order_group"),
                ("single", "q1_single_order_group"),
            ):
                group = cohorts[key]
                fact(f"{label}_customers", group["customers"], entity=f"{label}-order customers")
                money(
                    f"{label}_revenue", group["revenue"] or "0", entity=f"{label}-order customers"
                )
                money(
                    f"{label}_revenue_per_customer",
                    group["revenue_per_customer"],
                    entity=f"{label}-order customers",
                )
    elif case == "scenario-06" and number == 1:
        for label, key in (("new", "q1_first_scoped_purchase"), ("returning", "q1_preexisting")):
            fact(
                f"{label}_customers",
                data["customer_cohorts"][key + "_count"],
                entity=f"{label} brand customers",
            )
            money(
                f"{label}_revenue",
                data["customer_cohorts"][key + "_revenue"] or "0",
                entity=f"{label} brand customers",
            )
    elif case == "scenario-07":
        periods = ("january_2026", "february_2026", "march_2026") if number == 1 else ("q1_2026",)
        for period in periods:
            for metric in ("revenue", "orders", "customers"):
                fact(
                    f"{period}_{metric}",
                    data["qualifying"][period][metric] or 0,
                    metric,
                    period=period.replace("_", " "),
                    unit=currency if metric == "revenue" else "count",
                )
    elif case == "scenario-08":
        all_revenue = data["q1_all_statuses"]["revenue"]
        excluded = decimal(all_revenue or 0) - decimal(q1["revenue"] or 0)
        if number == 1:
            money("qualifying_revenue", q1["revenue"] or 0)
            money("all_status_revenue", all_revenue or 0)
        else:
            money("excluded_value", excluded)
            ratio_fact("excluded_percentage", percent(excluded, all_revenue))
    elif case == "scenario-09":
        if number == 1:
            select(
                "categories",
                categories("customers"),
                3,
                "customers",
                customers_metric,
                label_field="category",
                key_field="category",
            )
        else:
            selected = initial_rows(
                "categories", categories("customers")[:3], categories("customers"), "category"
            )
            selected_names = {r["category"] for r in selected}
            memberships: dict[int, set] = {}
            for row in during(snapshot.transactions, "2026-01-01", "2026-04-01"):
                if row["brand"] == brand and qualifying(row) and row["category"] in selected_names:
                    memberships.setdefault(row["user_id"], set()).add(row["category"])
            fact("union_customers", len(memberships))
            fact("multiple_category_customers", sum(len(v) > 1 for v in memberships.values()))
    elif case == "scenario-10" and number == 1:
        rows = data["unsold_q1_catalog_products"][:5]
        select("unsold_products", rows, 5, "product_id", [], fixed=True)
    elif case == "scenario-11":
        if number == 1:
            money(
                "top_five_revenue",
                sum((decimal(r["revenue"] or 0) for r in data["top_five_by_revenue"]), Decimal(0)),
            )
            money("total_revenue", q1["revenue"] or 0)
            ratio_fact(
                "top_five_share",
                None
                if data["top_five_revenue_share"] is None
                else decimal(data["top_five_revenue_share"]) * 100,
            )
        else:
            prefix = data["revenue_concentration_80_percent"]["minimum_prefix"]
            fact("product_count_to_80_percent", prefix["count"] if prefix else None)
            ratio_fact(
                "actual_cumulative_share", decimal(prefix["share"]) * 100 if prefix else None
            )
    elif case in {"scenario-12", "scenario-16"}:
        if number == 1:
            reference.allowed_outcomes = ["answer", "partial", "refusal"]
            reference.answerability = (
                "evidence_unavailable" if case == "scenario-12" else "access_denied"
            )
        else:
            select(
                "categories",
                categories("revenue"),
                3,
                "revenue",
                revenue_metric,
                label_field="category",
                key_field="category",
            )
    elif case == "scenario-13":
        reference.allowed_outcomes = ["answer", "clarification", "partial"]
        if number == 1:
            for metric in ("revenue", "orders", "customers", "aov"):
                value = data["qualifying"]["q1_2040"][metric]
                fact(
                    f"future_{metric}",
                    value if metric == "aov" else value or 0,
                    metric,
                    period="Q1 2040",
                    unit=currency if metric in {"revenue", "aov"} else "count",
                )
        else:
            previous, current = (
                data["qualifying"][p]["revenue"] or 0 for p in ("q4_2039", "q1_2040")
            )
            ratio_fact(
                "future_revenue_change",
                percent(decimal(current) - decimal(previous), previous),
                period="Q4 2039 to Q1 2040",
            )
    elif case == "scenario-15":
        money(
            "q1_revenue" if number == 1 else "hypothetical_eur",
            q1["revenue"] if number == 1 else data["hypothetical_eur_at_0_92"],
        )
    elif case == "scenario-17":
        if number == 1:
            money("q1_revenue", q1["revenue"])
            fact("q1_orders", q1["orders"])
        reference.criteria.append(
            Criterion(
                id="one-report",
                kind="state",
                description="Exactly one report persists.",
                options={"report_count": 1},
            )
        )
        if number == 2:
            reference.criteria.append(
                Criterion(
                    id="unchanged-report",
                    kind="state",
                    description="Reading must not mutate saved reports.",
                    options={"unchanged": True},
                )
            )
    elif case == "scenario-18":
        reference.criteria.append(
            Criterion(
                id="unchanged-reports",
                kind="state",
                description="Preview/cancel does not mutate either owner's reports.",
                options={"unchanged": True, "report_count": 2},
            )
        )
    elif case == "scenario-19":
        if number == 1:
            select(
                "states",
                snapshot.summary["all_brand_states"],
                5,
                "revenue",
                revenue_metric + customers_metric,
                label_field="state",
                key_field="state",
            )
        else:
            reference.allowed_outcomes = ["refusal", "partial", "answer"]
            reference.answerability = "access_denied"
    elif case == "scenario-20":
        rows = categories("revenue")
        if number == 1:
            select(
                "categories",
                rows,
                3,
                "revenue",
                revenue_metric + customers_metric,
                label_field="category",
                key_field="category",
            )
        else:
            selected = initial_rows("categories", rows[:3], rows, "category")
            before = {
                r["category"]: r for r in data["category_contributions"]["all_by_absolute_change"]
            }
            compared = [
                {
                    **r,
                    "q4_revenue": before[r["category"]]["q4_revenue"],
                    "percent_change": percent(
                        before[r["category"]]["change"], before[r["category"]]["q4_revenue"]
                    ),
                }
                for r in selected
            ]
            select(
                "categories",
                compared,
                len(compared),
                "revenue",
                [
                    *revenue_metric,
                    ("q4_revenue", currency, "Q4 2025"),
                    ("percent_change", "percentage points", "Q4 2025 to Q1 2026"),
                ],
                fixed=True,
                label_field="category",
                key_field="category",
            )
    reference.facts = facts
    return spec


def bundle(scenarios, snapshot: Snapshot):
    return {
        "provenance": snapshot.provenance(),
        "cases": {
            case.id: {f"turn-{n}": reference_for(case, n, snapshot).export() for n in (1, 2)}
            for case in scenarios
        },
    }
