---
name: product-ranking-analysis
description: Compare product rankings, top-N selections, customer reach, ranking overlap and boundary ties. Use for interpreting leaders or follow-ups about products in earlier lists.
metadata:
  audience: analyst
  version: "7"
---

# Product ranking analysis

Group by product ID with useful names. Revenue sums qualifying item sale_price; reach counts distinct customers. Customers, orders and units are different measures. Keep scope, status rule and time boundaries compatible; qualifying sales are not necessarily completed purchases.

Return N products when enough qualify, with a stable tie-break. RANK cutoffs may exceed N; include all boundary ties only when requested. A shorter eligible list is a valid result.

For follow-up overlap, compare IDs in the actual selected lists. Changing tie-breaks changes membership. An excluded tied product may equal the cutoff; exclusion gives neither an exact other-metric value nor proof of fewer customers. A union of revenue-only and customer-only rankings does not provide both measures for each product.

Rankings and names cannot establish prices, quantities, motives or causes. Revenue per customer is not unit price; revenue divided by matching units is average realized unit selling price, not basket value. Obtain paired measurements when needed or narrow the interpretation to list membership.

Selected leaders describe a subset, even when several metrics are measured. Whole-brand concentration or primary-driver claims need matching whole-brand evidence and contributions. Use revenue-driver-analysis for those questions.

Zero sales do not establish absent demand, stockouts or a reason to discontinue a product. Later sales show later activity, not earlier inventory state. Propose availability, exposure or margin checks without presenting unmeasured prevalence or motivations as facts.

For compact rankings, show names and requested metrics; rank is optional. Keep IDs in evidence for grouping and follow-ups, printing them only when requested or needed to disambiguate. Do not add other metrics, overlap analysis or a full tie inventory unless requested. State scope and material exclusions/tie rules once, with sensible precision and no invented currency.
