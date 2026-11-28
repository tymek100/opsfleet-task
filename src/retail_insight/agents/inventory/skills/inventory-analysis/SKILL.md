---
name: inventory-analysis
description: Time-aware inventory counts, aging, cost basis and conditional coverage.
metadata:
  audience: analyst
  version: "2"
---

# Inventory analysis

Count distinct inventory IDs at item grain and scope products before joining. At cutoff T, modeled stock membership is created_at <= T and (sold_at IS NULL OR sold_at > T). A sale exactly at T excludes the unit. Prefer stock for the default cutoff; inventory may expose sold and later-created records. If restating the predicate, preserve equality exactly or omit the repeated definition.

Age is elapsed time from recorded unit creation to the chosen cutoff. "Older than N days" uses created_at < T - N days; "at least N days" uses <=. Preserve timestamp precision. Complete-day age floors elapsed days: complete_days > N differs from elapsed_time > N days. Do not substitute catalog-product timestamps.

## Interpret the records

- Modeled units and recorded center attribution are not verified physical holdings, receipts, custody, reservations or available-to-promise stock. Product catalog and item-center attribution can differ.
- Creation/sale timestamps do not certify database insertion, procurement, receipt, settlement or dispatch. A null sold_at provides no shipment evidence; a later sale also qualifies for historical stock.
- Cost is recorded cost basis, not revenue, profit or a known currency. Missing costs are unknown, not zero or necessarily positive: report the known subtotal and missing coverage. Zero substitution could understate value but does not prove an error's direction.
- No available rows does not distinguish never stocked from stocked then depleted. Leave history unresolved without complete historical evidence. Returned sales do not establish restocking.
- Age does not measure turnover, demand velocity, dispatch delay, staff performance or surplus. Propose further checks rather than asserting causes.

Keep stocked products distinct from the catalog. Recompute global distinct counts; overlapping groups and sales joins must not multiply units. A correct footer does not repair a stronger unsupported assertion in the body.

Coverage = modeled units / (qualifying units sold / calendar days). Require a defined period and matching scope. Zero demand makes rate-based coverage undefined. Future constant demand and physical availability are assumptions; supplier lead times, incoming orders and safety-stock policy are not supplied by default.
