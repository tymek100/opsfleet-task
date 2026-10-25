"""Compile a bounded analytical language; never execute model-supplied SQL."""

import hashlib
from dataclasses import dataclass
from datetime import date

import sqlglot
from sqlglot import exp

from retail_agent.models import AccessDeniedError, Analysis, AppError, Dimension, Identity

DATASET = "bigquery-public-data.thelook_ecommerce"
SALES_DEFINITION = (
    "v1: revenue=sum(item sale_price); units=item rows; customers=distinct user_id; "
    "orders=distinct order_id. Both order and item status exclude Cancelled/Returned. "
    "Dates use order_items.created_at, UTC [start,end). Current status, not historical snapshots."
)


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    parameters: dict[str, str | int | bool | date | list[str] | list[int]]
    definitions: str
    output_columns: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()[:16]


def compile_query(request: Analysis, identity: Identity) -> CompiledQuery:
    if not identity.ceo and not identity.brands:
        raise AccessDeniedError(
            "No brands are assigned to your account. Contact your administrator."
        )
    if not identity.ceo and any(b not in identity.brands for b in request.brands):
        raise AccessDeniedError(
            f"That brand is outside your assigned scope. You can analyze {identity.scope} only. "
            "Ask about an authorized brand or contact your administrator for access."
        )
    params: dict[str, str | int | bool | date | list[str] | list[int]] = {
        "all_brands": identity.ceo,
        "allowed_brands": list(identity.brands),
        "start": request.start,
        "end": request.end,
        "inactivity_days": request.inactivity_days,
    }
    filters = ["(@all_brands OR p.brand IN UNNEST(@allowed_brands))"]
    if request.brands:
        params["filter_brands"] = request.brands
        filters.append("p.brand IN UNNEST(@filter_brands)")
    if request.product_ids:
        params["product_ids"] = request.product_ids
        filters.append("p.id IN UNNEST(@product_ids)")
    if request.customer_id:
        params["customer_id"] = request.customer_id
        filters.append("oi.user_id = @customer_id")
    if request.completed_only:
        filters.append("oi.status = 'Complete' AND o.status = 'Complete'")
    else:
        filters.append(
            "oi.status NOT IN ('Cancelled', 'Returned') "
            "AND o.status NOT IN ('Cancelled', 'Returned')"
        )
    # Geography joins are absent from customer rankings and all other query paths.
    geography = request.dimension == Dimension.STATE
    state_select = ", u.state AS state" if geography else ""
    state_join = f"JOIN `{DATASET}.users` u ON u.id = oi.user_id" if geography else ""
    base = f"""WITH scoped AS (
      SELECT oi.id AS item_id, oi.order_id, oi.user_id, oi.product_id,
             oi.sale_price, oi.created_at AS purchased_at,
             p.brand, p.category, p.name AS product_name {state_select}
      FROM `{DATASET}.order_items` oi
      JOIN `{DATASET}.orders` o ON o.order_id = oi.order_id AND o.user_id = oi.user_id
      JOIN `{DATASET}.products` p ON p.id = oi.product_id
      {state_join}
      WHERE {" AND ".join(filters)}
    )"""
    definition = SALES_DEFINITION + (
        " Override: Complete status only." if request.completed_only else ""
    )
    if request.kind == "churn":
        # Two point-in-time snapshots. Population: first purchase at least N days ago.
        # Existing customer inactivity share, NOT a monthly loss/incidence rate.
        group = "brand" if request.dimension == Dimension.BRAND else "'all'"
        sql = (
            base
            + f""", boundaries AS (
          SELECT @start AS as_of UNION ALL SELECT @end AS as_of
        ), histories AS (
          SELECT as_of, {group} AS cohort, user_id,
                 MIN(DATE(purchased_at)) AS first_purchase,
                 MAX(DATE(purchased_at)) AS last_purchase
          FROM scoped CROSS JOIN boundaries
          WHERE DATE(purchased_at) < as_of
          GROUP BY as_of, cohort, user_id
        ), summary AS (
        SELECT CAST(as_of AS STRING) AS period, cohort,
          COUNT(*) AS eligible_customers,
          COUNTIF(last_purchase < DATE_SUB(as_of, INTERVAL @inactivity_days DAY)) AS inactive_customers,
          SAFE_DIVIDE(COUNTIF(last_purchase < DATE_SUB(as_of, INTERVAL @inactivity_days DAY)),
                      COUNT(*)) AS inactivity_share
        FROM histories
        WHERE first_purchase < DATE_SUB(as_of, INTERVAL @inactivity_days DAY)
        GROUP BY period, cohort
        ), selected AS (
          SELECT cohort FROM summary GROUP BY cohort
          ORDER BY MAX(eligible_customers) DESC, cohort LIMIT 50
        )
        SELECT summary.* FROM summary JOIN selected USING (cohort)
        ORDER BY cohort, period LIMIT 100"""
        )
        columns = (
            "period",
            "cohort",
            "eligible_customers",
            "inactive_customers",
            "inactivity_share",
        )
        definition += (
            f" Churn proxy: {request.inactivity_days}-day inactivity share at start/end "
            "(exclusive as-of). Eligible = first authorized purchase before as-of minus N days; "
            "inactive = last purchase before that cutoff. Empty denominator is undefined. "
            "Not newly churned customers in a month. Brand breakdown capped at 50 largest eligible cohorts, preserving both snapshots."
        )
    else:
        dimensions: dict[Dimension, tuple[str, str, tuple[str, ...]]] = {
            Dimension.TOTAL: ("'all' AS label", "", ("label",)),
            Dimension.PRODUCT: (
                "product_id, product_name",
                "GROUP BY product_id, product_name",
                ("product_id", "product_name"),
            ),
            Dimension.BRAND: ("brand", "GROUP BY brand", ("brand",)),
            Dimension.CATEGORY: ("category", "GROUP BY category", ("category",)),
            Dimension.MONTH: (
                "FORMAT_DATE('%Y-%m', DATE(purchased_at)) AS month",
                "GROUP BY month",
                ("month",),
            ),
            Dimension.STATE: (
                "state",
                "GROUP BY state HAVING COUNT(DISTINCT user_id) >= 5",
                ("state",),
            ),
            Dimension.CUSTOMER: ("user_id", "GROUP BY user_id", ("user_id",)),
        }
        select, grouping, keys = dimensions[request.dimension]
        ordering = (
            "month"
            if request.dimension == Dimension.MONTH
            else f"{request.rank_by} DESC, {', '.join(keys)}"
        )
        sql = (
            base
            + f""" SELECT {select}, ROUND(SUM(sale_price), 2) AS revenue,
           COUNT(*) AS units, COUNT(DISTINCT user_id) AS customers,
           COUNT(DISTINCT order_id) AS orders, CAST(MAX(purchased_at) AS STRING) AS latest_purchase
        FROM scoped WHERE DATE(purchased_at) >= @start AND DATE(purchased_at) < @end
        {grouping} ORDER BY {ordering} LIMIT {request.limit}"""
        )
        columns = (*keys, "revenue", "units", "customers", "orders", "latest_purchase")
        if geography:
            definition += (
                " State cohorts under five customers suppressed; no customer/product ID filters."
            )
    statements = sqlglot.parse(sql, read="bigquery")
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise AppError("Internal query compilation failed.")
    return CompiledQuery(sql, params, definition, columns)
