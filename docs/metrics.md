# Metric definitions, version 1

Definitions are proposed defaults accepted by the client, not preexisting company policy. Every evidence block states the effective definition and scope. Calendar periods use UTC and half-open `[start, end)` boundaries; Q1 is January 1 through April 1. Ask for the year if absent.

| Metric | Definition |
|---|---|
| Revenue | Sum of `order_items.sale_price`, rounded to two decimal places after summing; both order and item status exclude Cancelled/Returned. This is a sales-value proxy, not accounting-recognized revenue or net profit. |
| Units | Eligible item rows, not order count. |
| Customers | Distinct `order_items.user_id` among eligible items. Repeated purchases do not add customers; counts across products cannot be summed to a global customer total. |
| Orders | Distinct order IDs among eligible items. Mixed-brand orders contribute only authorized items and count once within a result group. |
| Ranking | Separate top lists for requested metrics. Descending metric with deterministic dimension-key tie breakers. |
| Monthly sales | Eligible purchase timestamps grouped into UTC calendar months. Missing months mean no matching rows; the app does not fabricate observations. |
| Customer spend | Same scoped eligible items, grouped by internal user ID; no customer names or geography. |
| State | State from users, aggregated over authorized eligible items with at least five distinct customers. No customer/product-ID filter, no customer ID in output. |
| Churn proxy | N-day inactivity share at an exclusive as-of date, with N=90 unless explicitly overridden. Eligible customers first purchased before `as_of - N days`; inactive customers last purchased before that cutoff. All history is scoped to authorized brands before calculating first/last dates. |

Churn compares two snapshots at the requested start/end boundaries. Purchases on or after an as-of boundary cannot affect its history. A purchase exactly N days before as-of is treated as active; eligibility requires strictly earlier first purchase. State the boundary convention explicitly. If there is no eligible population, the share is undefined, not zero. A request for “last month” compares the first day of last month to the first day of this month.

This metric is **not a monthly rate of newly lost customers**. Its denominator changes as customers become seasoned, so a rising share may reflect both numerator and population changes. Always show eligible and inactive counts, compare percentage points, and verify that a supposed spike exists before explaining it. The default display uses four decimal places for inactivity percentages and percentage-point changes so small movements are visible; changes below 0.0001 percentage points use six places. When the eligible active count is unchanged but population size changes, the answer explicitly distinguishes those effects. Brand breakdowns are associations, not causal proof. Definitive causes would require additional evidence such as marketing, stock, competitor, service or experiment data.

Overrides: explicitly request Complete status only or an inactivity window such as “180 days.” They change definitions, never access permissions. The agent rejects unrequested Complete-only or inactivity-duration changes. Other definitions should be clarified or described as unsupported rather than implemented by arbitrary SQL.

Current source status is used for historical periods. Later cancellations/returns may change a rerun; the public dataset does not provide a complete historical status ledger for point-in-time reconstruction. Item creation time may differ from order creation/settlement time. Currency is assumed consistent with the dataset; tax, shipping, discounts and exchange conversion are not separately modeled. Revenue sums use source FLOAT values, so this prototype is not a financial ledger.

Brand churn breakdowns select at most 50 cohorts by their maximum eligible population across the two snapshots (then cohort name), returning both available snapshots per cohort. Missing baselines are labelled undefined. The application calculates the percentage-point change and direction independently of model prose.

## Comparing calendar periods

The primary period is evaluated relative to the explicitly selected baseline, regardless of chronological order or gaps. Absolute change is `primary - baseline`; percentage change is `(primary - baseline) / baseline × 100%`. Both periods must use identical scope, filters and metric definitions. A zero or unknown baseline makes percentage change undefined, but a known zero baseline still permits an absolute difference.

Raw SQL `SUM` over an empty sales population is NULL. When units, orders and customers are all zero, the derived revenue is zero; raw evidence remains unchanged. Missing revenue on a nonempty population remains unknown. An empty query establishes no qualifying sales in the dataset, not the absence of historical business activity outside it.

Calendar-day averages include days with no transactions. Daily-rate comparisons are separate from total changes and appear when requested. Q4 2025 has 92 days; Q1 2026 has 90. A comparison may evaluate the earlier period against the later one if that is the user's chosen baseline.

Repeated quarter references such as “Q4 2025 and Q1 2026 ... from Q4 to Q1” reuse the explicitly established year when unambiguous. If the same quarter is associated with multiple years, an unqualified reference still requires clarification.
