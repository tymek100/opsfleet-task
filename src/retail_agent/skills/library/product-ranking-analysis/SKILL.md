---
name: product-ranking-analysis
description: Compare product rankings, top-N selections, customer reach, ranking overlap and boundary ties. Use for interpreting leaders or follow-ups about products in earlier lists.
metadata:
  audience: analyst
  version: "2"
---

# Product ranking analysis

Adapt the investigation to the requested metric, population, period and format. Existing complete evidence may answer a follow-up without a new warehouse query.

## Define and compare the rankings

Group products by product ID while retaining a useful product name. Revenue is the sum of eligible item sale_price; customer reach counts distinct customer IDs. Distinct customers are not orders or units. Use the same authorized population and time boundaries for a meaningful comparison.

Describe the chosen status rule accurately. The default sales relation excludes Cancelled/Returned at both order and item levels; it does not require Complete status. Do not call this population completed sales unless the query actually applies that narrower status condition.

For top N, return N items when enough exist. Use a stable tie-break, such as ascending product ID, and describe the actual selection rule briefly when it matters. RANK cutoffs can return more than N rows. Include all boundary ties only if that is the requested interpretation; disclose a genuine short list when fewer products qualify.

For overlap, compare product IDs in the actual selected lists. Preserve those lists on follow-ups; changing a tie-break can change membership. Non-overlap under a tie-break does not establish a clean separation between all products with similar performance. Avoid presenting tied products as materially different solely because one is outside the cutoff.

## Interpret only supported differences

A ranking establishes relative positions and membership. Product categories or names alone do not establish price levels, unit volumes, motives or causes. Revenue from one customer can include several units across several orders. Revenue per customer may be calculated from matching aggregates, but it is not unit selling price.

If an explanation needs missing price, quantity or population-total measurements, consider revenue-driver-analysis. Obtain them when useful, or give a narrower supported comparison and briefly state the limitation. A top-N list does not establish how concentrated total brand revenue is without the matching whole-brand total.

When quantities are measured, revenue divided by units supports average realized unit selling price. Call it that: item prices do not establish whole-order transaction values or basket totals. Keep descriptive arithmetic distinct from customer motivations or causal drivers.

Choose compact prose or useful tables according to the user request. Show only relevant columns. Do not reproduce internal evidence records or imply the displayed list explains a cause.

For compact ranking tables, prioritize product names and the requested ranking metric; add ranks or identifiers only when they help. Fields obtained for verification or a possible follow-up do not all need to be printed. Avoid adding units, the other ranking metric, an unsolicited overlap section or an extended methodology section to a request for two compact lists. Keep any necessary scope, status and tie caveats brief and shared across the tables. These are presentation choices, not a fixed answer template.
