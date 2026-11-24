"""Accept equivalent printed disjoint partitions without inventing an answer excerpt."""

import re
from decimal import Decimal

from evaluation.graders.checks import numeric_scores, value_matches, verdict
from evaluation.models import Criterion, Fact

PARTITION_CRITERION = "equivalent-disjoint-partitions"
TOPICS = {"center_all", "center_top", "center_other", "product_top_centers", "unknown_center"}


def with_partitions(snapshot, identity, reference):
    """Reference metadata describes permitted layouts; it does not prescribe output form."""
    result = reference.model_copy(deep=True)
    if any(c.id == PARTITION_CRITERION for c in result.criteria):
        return result
    known = {r["id"] for r in snapshot.raw["distribution_centers"]}
    stock = snapshot.stock(identity)
    groups = []
    for target in result.facts:
        if target.source_key not in TOPICS or "Unknown" not in target.entity:
            continue
        is_cost = "cost" in target.metric
        if not is_cost and target.metric != "modeled unsold units":
            continue  # Distinct products across centers are not additive.
        product = re.search(r"\bproduct (\d+)\b", target.entity)
        unknown = [
            r
            for r in stock
            if r.get("product_distribution_center_id") not in known
            and (not product or int(r["product_id"]) == int(product[1]))
        ]
        parts = []
        for center in sorted(
            {r.get("product_distribution_center_id") for r in unknown},
            key=lambda x: (x is not None, x or 0),
        ):
            rows = [r for r in unknown if r.get("product_distribution_center_id") == center]
            value = (
                sum(
                    (Decimal(str(r["cost"])) for r in rows if r.get("cost") is not None), Decimal(0)
                )
                if is_cost
                else len(rows)
            )
            label = (
                "NULL / missing inventory center ID"
                if center is None
                else f"unmatched inventory center ID {center}"
            )
            parts.append(
                target.model_copy(
                    update={
                        "id": f"{target.id}__{'null' if center is None else 'unmapped_' + str(center)}",
                        "entity": f"{target.entity}; ONLY {label}, excluding other Unknown subgroups",
                        "value": str(value),
                        "source_key": "optional_disjoint_partition_component",
                    }
                ).model_dump(mode="json")
            )
        if parts:
            target.entity += (
                " (COMBINED missing and all unmatched inventory center IDs, not a single subgroup)"
            )
            groups.append(
                {
                    "target_id": target.id,
                    "components": parts,
                    "definition": "Disjoint raw inventory-center IDs; totals are additive for units and known cost. Separate printed subgroups are permitted instead of a printed combined total.",
                }
            )
    if groups:
        result.criteria.append(
            Criterion(
                id=PARTITION_CRITERION,
                kind="numeric",
                description="Accept a correct printed combined Unknown total or every correct disjoint Unknown component. Additional optional extraction bindings are not required answer content.",
                options={"groups": groups},
            )
        )
    return result


def groups(reference):
    return next(
        (c.options["groups"] for c in reference.criteria if c.id == PARTITION_CRITERION), []
    )


def extraction_reference(reference):
    """Add optional bindings only to the extraction request; required-fact counts stay fixed."""
    result = reference.model_copy(deep=True)
    for group in groups(reference):
        result.facts.extend(Fact.model_validate(f) for f in group["components"])
    return result


def numeric_partition_scores(reference, judgment):
    selected = {g["target_id"]: g for g in groups(reference)}
    ordinary = reference.model_copy(
        update={"facts": [f for f in reference.facts if f.id not in selected]}
    )
    scores = numeric_scores(ordinary, judgment)
    extracted = {f.id: f for f in judgment.facts}
    for target in reference.facts:
        if target.id not in selected:
            continue
        components = [Fact.model_validate(f) for f in selected[target.id]["components"]]
        if target.value is None or any(part.value is None for part in components):
            raise ValueError(
                "An additive partition requires non-null independently calculated values"
            )
        component_total = sum(
            (Decimal(part.value) for part in components if part.value is not None), Decimal(0)
        )
        total = extracted.get(target.id)
        seen = [(part, extracted.get(part.id)) for part in components]
        parts_correct = all(
            item is not None and value_matches(part, item.value, item.span) for part, item in seen
        )
        if total is not None:
            valid = value_matches(target, total.value, total.span)
            reason = f"Printed combined total: expected {target.value}, extracted {total.value}."
        else:
            valid = parts_correct and component_total == Decimal(target.value)
            reason = (
                f"Combined {target.value} verified from complete, explicitly quoted disjoint components."
                if valid
                else "No correct printed combined total or complete correct disjoint partition was extracted."
            )
        scores.append(
            verdict(
                "numeric_fact",
                valid,
                f"{target.entity}; {target.metric}: {reason}",
                criterion_id=target.id,
            )
        )
        for part, item in seen:
            if item is not None:
                scores.append(
                    verdict(
                        "numeric_partition_component",
                        value_matches(part, item.value, item.span),
                        f"Optional printed component {part.entity}: expected {part.value}, extracted {item.value}.",
                        criterion_id=part.id,
                    )
                )
    return scores
