---
name: cross-domain-analysis
description: Delegate and reconcile sales, inventory and distribution evidence.
metadata:
  audience: analyst
  version: "2"
---

# Cross-domain analysis

Choose specialists for the required evidence. Preserve scope, snapshot and business cutoff; forward relevant evidence and clarify incompatible definitions. Narratives and prior review approval are not substitutes for source observations.

## Combine measurements

Join sales and modeled stock by product or compatible category definitions after independent aggregation. Preserve categories present on only one side. Keep the historical sales period separate from the inventory cutoff. Revenue is not demand units.

Use one authoritative table at the required grain, or disjoint detail reconciled to an independent total. Never add a product total to its center details. Distinct customers/products across overlapping groups are not additive. Missing and unmatched center IDs must both enter Unknown with costs on the same population.

Qualifying sales are not necessarily fulfilled/completed demand. Hypothetical coverage divides modeled stock by qualifying units per calendar day over a specified period. Zero demand makes it undefined. State constant-demand and availability assumptions; historical sales are not measured current demand.

A stock-to-historical-sales ratio does not establish current turnover, usable supply, shortage, surplus or lost sales. Subtracting past sales from stock cannot measure lost sales. Recorded inventory cost measures cost concentration, not actual cash tied up. For a shortlist, use measured criteria and propose the missing checks without diagnosing an operational problem. Missing either comparison input requires a concise partial result.

## Preserve source meaning

- Stock membership uses created_at <= T and (sold_at IS NULL OR sold_at > T). Inventory can still expose sold/later-created records. Creation/sale timestamps are not verified receipt, ingestion, procurement or dispatch events.
- Age is elapsed time from unit creation. "Older than N days" excludes equality; "at least" includes it. Complete-day age floors elapsed days and differs at sub-day boundaries. Preserve exact predicates when paraphrasing or omit repeated definitions.
- Raw center IDs, recognized centers with stock and directory entries are different populations. Failed matches do not prove invalid IDs or nonexistent facilities. Current attribution is not historical assignment or movement.
- No rows do not prove complete historical absence. Missing cost does not establish a positive omitted amount. A top-N subset cannot establish a whole-population driver or cause.
- A specialist's chosen query window does not define source coverage. Check schema/capabilities before declaring a field or history unavailable.

## Capabilities and conclusions

Facility directories provide IDs, names and coordinates, not operating status, hours or capacity. Maps may be advertised but unconfigured; retain known unavailability on follow-ups. Propose routing/weather work only if available or explicitly conditional on later setup. Live observations do not establish historical causes.

Missing prices, lead times, reservations and transfer constraints limit operational conclusions. Modeled units are not physical holdings, and sales ranks alone cannot rank inventory risks. A conditional phrase or later caveat cannot repair an unsupported diagnosis, including in headings. Reject an inference without asserting its opposite. The final combined answer requires its own review; no agent here executes purchases or transfers.
