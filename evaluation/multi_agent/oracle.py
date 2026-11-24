"""Raw-row Decimal/set references, independent of runtime SQL and agent responses."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from evaluation.models import Criterion, Fact, TurnReference

from .partitions import with_partitions
from .semantic_contracts import independent_totals, semantic_criteria

AS_OF = "2026-04-01T00:00:00+00:00"


def instant(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result


def number(value):
    return Decimal(str(value))


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class Snapshot:
    def __init__(self, raw: dict, *, as_of=AS_OF, snapshot_at=None):
        # A captured source is immutable for a run; detach from caller-owned rows.
        self.raw, self.as_of = deepcopy(raw), instant(as_of)
        self.snapshot_at = snapshot_at
        self.sha256 = checksum(raw)
        self.capture_cost_usd = 0.0
        self.capture_billing: list[dict] = []
        self._background_cache: dict[str, dict] = {}

    @classmethod
    def load(cls, path: Path, **kwargs):
        return cls(json.loads(path.read_text()), **kwargs)

    def scoped(self, identity):
        brands = {"alice": {"Calvin Klein"}, "bob": {"Levi's"}, "ceo": None}[identity]
        products = {
            int(r["id"]): r for r in self.raw["products"] if brands is None or r["brand"] in brands
        }
        inventory = {
            int(r["id"]): r for r in self.raw["inventory_items"] if int(r["product_id"]) in products
        }
        return products, list(inventory.values())

    def stock(self, identity, *, at=None):
        at = instant(at) if at is not None else self.as_of
        return [
            r
            for r in self.scoped(identity)[1]
            if r.get("created_at") is not None
            and instant(r["created_at"]) <= at
            and (r.get("sold_at") is None or instant(r["sold_at"]) > at)
        ]

    def sales(self, identity):
        products, _ = self.scoped(identity)
        orders = {int(r["order_id"]): r for r in self.raw.get("orders", [])}
        start = self.as_of - timedelta(days=30)
        return [
            r
            for r in self.raw.get("order_items", [])
            if int(r["product_id"]) in products
            and r["status"] not in {"Cancelled", "Returned"}
            and int(r["order_id"]) in orders
            and orders[int(r["order_id"])]["status"] not in {"Cancelled", "Returned"}
            and start <= instant(r["created_at"]) < self.as_of
        ]

    def calculate(self, topic, identity="alice"):
        products, inventory = self.scoped(identity)
        stock = self.stock(identity)
        centers = {int(r["id"]): r for r in self.raw["distribution_centers"]}
        scope = (
            "all brands"
            if identity == "ceo"
            else "Calvin Klein"
            if identity == "alice"
            else "Levi's"
        )
        values = []

        def add(metric, value, entity=scope, unit="count", tolerance="0"):
            values.append(
                Fact(
                    id=f"f{len(values) + 1}",
                    value=str(value) if value is not None else None,
                    value_type="null"
                    if value is None
                    else "text"
                    if isinstance(value, str)
                    else "number",
                    source_key=topic,
                    metric=metric,
                    entity=entity,
                    period=self.as_of.isoformat(),
                    scope=scope,
                    unit=unit,
                    tolerance=number(tolerance),
                )
            )

        def totals(rows, entity=scope):
            add("modeled unsold units", len(rows), entity)
            add(
                "recorded cost of units with non-null cost",
                sum((number(r["cost"]) for r in rows if r.get("cost") is not None), Decimal(0)),
                entity,
                "source currency unspecified",
                "0.01",
            )

        groups = defaultdict(list)
        if topic in {"stock_totals", "scope_totals", "stock_units_cost"}:
            totals(stock)
            if topic != "stock_units_cost":
                add("distinct stocked products", len({r["product_id"] for r in stock}))
        elif topic in {"category_top", "category_other", "category_all"}:
            for r in stock:
                groups[products[int(r["product_id"])]["category"]].append(r)
            ranked = sorted(groups, key=lambda k: (-len(groups[k]), k))
            selected = ranked[:3] if topic != "category_all" else ranked
            for key in selected:
                add("modeled unsold units", len(groups[key]), key)
            if topic == "category_other":
                add("modeled unsold units", sum(len(groups[k]) for k in ranked[3:]), "Other")
                add("modeled unsold units", len(stock), "Total")
        elif topic in {"product_top", "product_top_cost", "product_top_centers"}:
            for r in stock:
                groups[int(r["product_id"])].append(r)
            for pid in sorted(groups, key=lambda k: (-len(groups[k]), k))[:3]:
                entity = f"product {pid} ({products[pid]['name']})"
                if topic == "product_top_cost":
                    add(
                        "recorded cost of stocked units",
                        sum(
                            (number(r["cost"]) for r in groups[pid] if r.get("cost") is not None),
                            Decimal(0),
                        ),
                        entity,
                        "source currency unspecified",
                        "0.01",
                    )
                elif topic == "product_top_centers":
                    allocated = defaultdict(int)
                    for r in groups[pid]:
                        allocated[
                            r.get("product_distribution_center_id")
                            if r.get("product_distribution_center_id") in centers
                            else None
                        ] += 1
                    for center, count in sorted(allocated.items(), key=lambda p: str(p[0])):
                        add(
                            "modeled unsold units",
                            count,
                            f"{entity}; {centers[center]['name'] if center is not None else 'Unknown'}",
                        )
                else:
                    add("modeled unsold units", len(groups[pid]), entity)
        elif topic in {"aged", "aged_share"}:
            aged = [r for r in stock if (self.as_of - instant(r["created_at"])).days > 90]
            if topic == "aged":
                totals(aged, "stock older than 90 complete days")
            else:
                add(
                    "aged share of all modeled unsold units",
                    Decimal(len(aged)) * 100 / len(stock) if stock else None,
                    unit="percent",
                    tolerance="0.01",
                )
        elif topic == "missing_cost":
            add(
                "stocked units with missing recorded cost",
                sum(r.get("cost") is None for r in stock),
            )
            add(
                "known recorded stock cost",
                sum((number(r["cost"]) for r in stock if r.get("cost") is not None), Decimal(0)),
                unit="source currency unspecified",
                tolerance="0.01",
            )
        elif topic in {"prior_stock", "stock_change"}:
            previous = self.stock(identity, at=self.as_of - timedelta(days=30))
            if topic == "prior_stock":
                add("modeled unsold units 30 days before cutoff", len(previous))
                add("modeled unsold units at cutoff", len(stock))
            else:
                add("net change in modeled unsold units", len(stock) - len(previous))
        elif topic == "sold_later":
            add(
                "stocked units with recorded sale after cutoff",
                sum(
                    r.get("sold_at") is not None and instant(r["sold_at"]) > self.as_of
                    for r in stock
                ),
            )
        elif topic == "future_created":
            add(
                "inventory rows created after cutoff, excluded from stock",
                sum(
                    r.get("created_at") is not None and instant(r["created_at"]) > self.as_of
                    for r in inventory
                ),
            )
        elif topic == "zero_stock":
            add(
                "catalog products with zero modeled unsold units",
                len(set(products) - {int(r["product_id"]) for r in stock}),
            )
        elif topic == "attribution_conflicts":
            add(
                "stocked units whose item center differs from current product catalog center",
                sum(
                    r.get("product_distribution_center_id") is not None
                    and products[int(r["product_id"])].get("distribution_center_id") is not None
                    and r.get("product_distribution_center_id")
                    != products[int(r["product_id"])].get("distribution_center_id")
                    for r in stock
                ),
            )
        elif topic == "oldest":
            add(
                "oldest modeled unsold unit age",
                max(((self.as_of - instant(r["created_at"])).days for r in stock), default=None),
                unit="complete days",
            )
        elif topic == "sold_boundary":
            add(
                "rows sold exactly at cutoff, excluded from stock",
                sum(
                    r.get("sold_at") is not None and instant(r["sold_at"]) == self.as_of
                    for r in inventory
                ),
            )
        elif topic in {
            "center_all",
            "center_top",
            "center_other",
            "center_products",
            "center_age",
            "unknown_center",
            "center_count",
        }:
            for r in stock:
                key = r.get("product_distribution_center_id")
                groups[key if key in centers else None].append(r)
            ranked = sorted(
                groups, key=lambda k: (-len(groups[k]), k if k is not None else float("inf"))
            )
            if topic == "unknown_center":
                totals(groups[None], "Unknown center")
            elif topic == "center_count":
                add("known centers holding scoped stock", len([k for k in groups if k is not None]))
            else:
                for key in ranked[:3] if topic in {"center_top", "center_other"} else ranked:
                    label = centers[key]["name"] if key is not None else "Unknown"
                    if topic == "center_products":
                        add(
                            "distinct stocked products",
                            len({r["product_id"] for r in groups[key]}),
                            label,
                        )
                    elif topic == "center_age":
                        add(
                            "modeled unsold units older than 90 complete days",
                            sum(
                                (self.as_of - instant(r["created_at"])).days > 90
                                for r in groups[key]
                            ),
                            label,
                        )
                    else:
                        add("modeled unsold units", len(groups[key]), label)
                if topic == "center_other":
                    add("modeled unsold units", sum(len(groups[k]) for k in ranked[3:]), "Other")
                if topic in {"center_all", "center_other", "center_products"}:
                    add(
                        "distinct stocked products"
                        if topic == "center_products"
                        else "modeled unsold units",
                        len({r["product_id"] for r in stock})
                        if topic == "center_products"
                        else len(stock),
                        "Global total",
                    )
        elif topic in {"sales_total", "sales_stock", "sales_top", "coverage", "no_sales_stock"}:
            sales = self.sales(identity)
            sold = defaultdict(list)
            for r in sales:
                sold[int(r["product_id"])].append(r)
            if topic == "sales_total":
                add("qualifying units over 30 complete days", len(sales))
                add(
                    "qualifying revenue over 30 complete days",
                    sum((number(r["sale_price"]) for r in sales), Decimal(0)),
                    unit="source currency unspecified",
                    tolerance="0.01",
                )
            elif topic == "sales_stock":
                add("qualifying units over 30 complete days", len(sales))
                add("modeled unsold units", len(stock))
            elif topic == "no_sales_stock":
                rows = [r for r in stock if int(r["product_id"]) not in sold]
                add(
                    "stocked products with no qualifying purchases in 30 days",
                    len({r["product_id"] for r in rows}),
                )
                totals(rows, "products with no qualifying purchases in 30 days")
            else:
                for pid in sorted(sold, key=lambda k: (-len(sold[k]), k))[:3]:
                    entity = f"product {pid} ({products[pid]['name']})"
                    units = sum(int(r["product_id"]) == pid for r in stock)
                    if topic == "coverage":
                        add(
                            "conditional coverage using 30-day qualifying unit demand",
                            number(units) * 30 / len(sold[pid]),
                            entity,
                            "days",
                            "0.01",
                        )
                    else:
                        add("qualifying units over 30 complete days", len(sold[pid]), entity)
                        add("modeled unsold units", units, entity)
        elif topic != "behavior":
            raise ValueError(f"Unknown oracle topic: {topic}")
        return values


def reference(snapshot, scenario, turn):
    topics = scenario["topics"][turn - 1]
    facts = []
    for topic in topics:
        for item in snapshot.calculate(topic, scenario.get("identity", "alice")):
            facts.append(item.model_copy(update={"id": f"f{len(facts) + 1}"}))
    criteria = [
        Criterion(id=f"criterion-{i + 1}", kind="semantic", description=text)
        for i, text in enumerate(scenario["checks"][turn - 1])
    ]
    criteria.extend(
        [
            Criterion(
                id="optional-claim-truth",
                kind="semantic",
                description="Any additional numerical claims about stock, recorded cost or qualifying 30-day sales must agree with the independently computed background facts in options. These optional facts are NOT required to be mentioned. An observed tool result does not justify a numerical assertion that contradicts these raw-row references. Match entity, metric, scope and time; do not conflate quantities from different periods.",
                options={
                    "independent_facts": background(snapshot, scenario.get("identity", "alice")),
                    "policy": "Optional assertions only; absence is not a failure.",
                },
            ),
            Criterion(
                id="modeled-stock-boundary",
                kind="semantic",
                description="If discussing inventory, distinguish modeled unsold units from confirmed physical, usable or available-to-promise stock. Do not assert availability, reservations, warehouse capacity or shipment feasibility from inventory rows alone. A concise clear qualification is sufficient; do not require irrelevant caveats when inventory is not discussed.",
            ),
        ]
    )
    criteria.extend(
        semantic_criteria(
            independent_totals(
                snapshot.raw, scenario.get("identity", "alice"), snapshot.as_of.isoformat()
            )
        )
    )
    prose = "; ".join(
        f"{f.entity}: {f.metric} = {f.value if f.value is not None else 'undefined'} ({f.unit})"
        for f in facts
    )
    if prose:
        prose += ". "
    prose += " ".join(scenario["checks"][turn - 1])
    result = TurnReference(
        facts=facts,
        criteria=criteria,
        reference_answer=prose,
        allowed_outcomes=scenario.get("outcomes", [["answer"], ["answer"]])[turn - 1],
        reference_procedure="Independent Decimal/set aggregation over frozen raw table rows. Do not compare exact prose.",
    )
    return with_partitions(snapshot, scenario.get("identity", "alice"), result)


def background(snapshot, identity):
    """Independent optional-claim truth, never required output and never agent context."""
    if identity not in snapshot._background_cache:
        snapshot._background_cache[identity] = _calculate_background(snapshot, identity)
    # Reference consumers may select optional context; that must not mutate the
    # next case's independent truth or another identity's source context.
    return deepcopy(snapshot._background_cache[identity])


def _calculate_background(snapshot, identity):
    products, _ = snapshot.scoped(identity)
    stock = snapshot.stock(identity)
    sales = snapshot.sales(identity)
    centers = {int(r["id"]): r for r in snapshot.raw["distribution_centers"]}
    stock_by_product = defaultdict(list)
    sales_by_product = defaultdict(list)
    for row in stock:
        stock_by_product[int(row["product_id"])].append(row)
    for row in sales:
        sales_by_product[int(row["product_id"])].append(row)

    def stock_values(rows):
        return {
            "modeled_unsold_units": len(rows),
            "distinct_stocked_products": len({r["product_id"] for r in rows}),
            "known_recorded_stock_cost": str(
                sum((number(r["cost"]) for r in rows if r.get("cost") is not None), Decimal(0))
            ),
            "stock_units_with_unknown_cost": sum(r.get("cost") is None for r in rows),
        }

    product_rows = []
    for pid, product in sorted(products.items()):
        selected = stock_by_product[pid]
        purchased = sales_by_product[pid]
        product_rows.append(
            {
                "product_id": pid,
                "product_name": product["name"],
                **stock_values(selected),
                "qualifying_units_30_days": len(purchased),
                "qualifying_revenue_30_days": str(
                    sum((number(r["sale_price"]) for r in purchased), Decimal(0))
                ),
            }
        )
    center_rows = []
    for center in [*sorted(centers), None]:
        selected = [
            r
            for r in stock
            if (
                r.get("product_distribution_center_id")
                if r.get("product_distribution_center_id") in centers
                else None
            )
            == center
        ]
        center_rows.append(
            {
                "center_id": center,
                "center_name": centers[center]["name"] if center is not None else "Unknown",
                **stock_values(selected),
            }
        )
    category_rows = []
    for category in sorted({r["category"] for r in products.values()}):
        selected = [r for r in stock if products[int(r["product_id"])]["category"] == category]
        category_rows.append({"category": category, **stock_values(selected)})
    return {
        "as_of": snapshot.as_of.isoformat(),
        "sales_period_start": (snapshot.as_of - timedelta(days=30)).isoformat(),
        "sales_period_end_exclusive": snapshot.as_of.isoformat(),
        "stock_rule": "created_at <= as_of AND (sold_at IS NULL OR sold_at > as_of); distinct inventory IDs; physical usability unobserved",
        "sales_rule": "Exclude Cancelled/Returned at both order and item level. Count qualifying item rows, not unique customers or orders.",
        "identity": identity,
        "brands": sorted({p["brand"] for p in products.values()}),
        "total": {
            **stock_values(stock),
            "qualifying_units_30_days": len(sales),
            "qualifying_revenue_30_days": str(
                sum((number(r["sale_price"]) for r in sales), Decimal(0))
            ),
        },
        "products": product_rows,
        "item_centers": center_rows,
        "categories": category_rows,
    }
