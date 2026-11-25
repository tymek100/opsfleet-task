"""Candidate domain grounding criteria and compact independent raw-row totals.

No runtime knowledge, answer templates or calibration case IDs are imported here.
"""

from datetime import datetime
from decimal import Decimal

from evaluation.models import Criterion

CRITERIA_VERSION = "v3"

ATOMIC_CRITERIA = (
    (
        "cost-direction",
        "A missing cost has unknown value and sign. FAIL if any clause claims imputing zero "
        "necessarily/would understate total cost without independent positive-cost evidence. "
        "This is a checkable methodological assertion, not NOT_FACTUAL advice. Saying missing "
        "cost is unknown elsewhere does not repair that certainty. 'Could understate' or 'assumes "
        "an unverified zero' is acceptable. Pass if no such assertion occurs.",
    ),
    (
        "snapshot-history",
        "The available snapshot has no complete-history guarantee. FAIL if zero observed rows "
        "are used to claim an item was never stocked/depleted/ordered, no units have EVER been "
        "recorded, or that it was NOT stocked and subsequently depleted. These are historical "
        "claims even inside an explanation with a correct main conclusion. Restricting absence "
        "to the available snapshot, or explicitly saying history is unknown, passes.",
    ),
    (
        "physical-boundary",
        "Inspect positive claims in every sentence. 'Inventory actually held at the cutoff' "
        "asserts real holdings; 'physical units on hand' asserts physical availability. These "
        "are not synonyms for modeled records, including when explaining a counterfactual "
        "calculation. Without independent physical-count/custody evidence, mark this criterion "
        "FAIL for either assertion or equivalent wording. A footer saying the model does not "
        "measure physical availability does NOT repair that affirmative claim. A statement "
        "about understating MODELED stock is acceptable; denying physical verification or "
        "asking for it is not a positive claim.",
    ),
    (
        "event-visibility",
        "FAIL if the answer asserts created_at is database ingestion or physical receipt, "
        "claims a null sold_at proves no outbound shipment/order exists, or says rows created "
        "after the cutoff cannot be visible in the inventory relation. The source establishes "
        "recorded creation/sale timestamps only; shipment data is unavailable, and the stock "
        "relation filters membership while inventory may expose later rows. Pass when absent.",
    ),
    (
        "aging-inference",
        "FAIL if stock age/count is said to MEASURE turnover or demand velocity, or high age "
        "is said to establish/reflect overstocking, obsolescence, low demand, shipping delay "
        "or staff performance without additional evidence. A correct denial of one causal "
        "claim does not justify substituting another. Age is elapsed time from recorded "
        "creation to the chosen cutoff. Explicit possible explanations needing evidence pass.",
    ),
    (
        "stock-membership",
        "Assess the answer's stated stock definition independently of its SQL. 'Created on "
        "or before the cutoff without qualifying sales before the cutoff' is INCORRECT: "
        "qualifying sales applies order/item statuses, while inventory membership depends "
        "on the inventory sold_at field, and 'before' omits exclusion at exact equality. "
        "For that definition or an equivalent substitution, mark this criterion FAIL even "
        "if all counts and SQL are correct. The supported predicate is created_at <= T AND "
        "(sold_at IS NULL OR sold_at > T). A sale exactly at T excludes a unit. No repetition "
        "of a definition is required when it is not discussed.",
    ),
    (
        "global-reconciliation",
        "Check every stated global/scoped-brand total, including prose, against "
        "global_modeled_units_including_unknown in options. Known-center units exclude Unknown "
        "and cannot be labeled the total across all locations. FAIL a mismatched global total "
        "even if the main table or subgroup figures are correct. These values are NOT required "
        "answer content; an omitted optional total is not a failure.",
    ),
    (
        "catalog-population",
        "The explicit words 'catalog products' refer to the full scoped catalog, including "
        "zero-stock products. Compare that claim with distinct_catalog_products in options, "
        "not distinct_stocked_products. FAIL if a number of stocked products is called 'all "
        "catalog products'; surrounding inventory context does not change that explicit "
        "population label. A count labeled distinct stocked products passes when correct. "
        "No additional metric is required to be reported.",
    ),
    (
        "recognized-facilities",
        "A claim of X distribution centers/facilities/warehouses must count recognized "
        "directory matches, not distinct raw item-center IDs. Compare with "
        "recognized_centers_with_scoped_stock or recognized_center_directory_count as "
        "appropriate. FAIL if unmatched IDs inflate a count described as facilities, even "
        "when a tool returned that number under COUNT(DISTINCT center_id). Only an explicitly "
        "labeled raw-ID count may use distinct_recorded_nonnull_item_center_ids. An Unknown "
        "attribution group is not an additional identified facility. No extra fact is required.",
    ),
)


def independent_totals(raw, identity, as_of):
    """Additional optional-claim controls from frozen raw rows, never runtime SQL."""
    if identity != "workspace":
        raise ValueError(
            "Historical persona captures require their frozen references; new runs use workspace access"
        )
    brands = None
    products = {p["id"] for p in raw["products"] if brands is None or p["brand"] in brands}
    cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    stock = {
        r["id"]: r
        for r in raw["inventory_items"]
        if r["product_id"] in products
        and r.get("created_at") is not None
        and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) <= cutoff
        and (
            r.get("sold_at") is None
            or datetime.fromisoformat(r["sold_at"].replace("Z", "+00:00")) > cutoff
        )
    }
    centers = {r["id"] for r in raw["distribution_centers"]}
    observed_ids = {r["product_distribution_center_id"] for r in stock.values()}
    unknown = [r for r in stock.values() if r["product_distribution_center_id"] not in centers]
    return {
        "identity": identity,
        "as_of": as_of,
        "global_modeled_units_including_unknown": len(stock),
        "known_center_modeled_units": len(stock) - len(unknown),
        "unknown_center_modeled_units": len(unknown),
        "distinct_stocked_products": len({r["product_id"] for r in stock.values()}),
        "distinct_catalog_products": len(products),
        "known_recorded_stock_cost": str(
            sum(
                (Decimal(str(r["cost"])) for r in stock.values() if r.get("cost") is not None),
                Decimal(0),
            )
        ),
        "units_with_missing_cost": sum(r.get("cost") is None for r in stock.values()),
        "recognized_center_directory_count": len(centers),
        "recognized_centers_with_scoped_stock": len(observed_ids & centers),
        "distinct_recorded_nonnull_item_center_ids": len(observed_ids - {None}),
        "unmatched_nonnull_item_center_ids": sorted(observed_ids - centers - {None}),
        "policy": "Optional assertions only; not required answer content. No physical facility verification is claimed.",
    }


def semantic_criteria(totals):
    """Optional assertion checks; they do not require additional answer content."""
    return [
        Criterion(
            id=f"domain-{identifier}-{CRITERIA_VERSION}",
            kind="semantic",
            description=description,
            options={"independent_totals": totals},
        )
        for identifier, description in ATOMIC_CRITERIA
    ]
