---
name: product-ranking-analysis
description: Compare product rankings, top-N selections, customer reach, ranking overlap and boundary ties. Use for interpreting leaders or follow-ups about products in earlier lists.
metadata:
  audience: analyst
  version: "6"
---

# Product ranking analysis

Adapt the investigation to the requested metric, population, period and format. Existing complete evidence may answer a follow-up without a new warehouse query.

## Define and compare the rankings

Group products by product ID while retaining a useful product name. Revenue is the sum of eligible item sale_price; customer reach counts distinct customer IDs. Distinct customers are not orders or units. Use the same authorized population and time boundaries for a meaningful comparison.

Describe the chosen status rule accurately. The default sales relation excludes Cancelled/Returned at both order and item levels; it does not require Complete status. Do not call this population completed sales unless the query actually applies that narrower status condition.

For top N, return N items when enough exist. Use a stable tie-break, such as ascending product ID, and describe the actual selection rule briefly when it matters. RANK cutoffs can return more than N rows. Include all boundary ties only if that is the requested interpretation; disclose a genuine short list when fewer products qualify.

For overlap, compare product IDs in the actual selected lists. Preserve those lists on follow-ups; changing a tie-break can change membership. Non-overlap under a tie-break does not establish a clean separation between all products with similar performance. Avoid presenting tied products as materially different solely because one is outside the cutoff.

Exclusion from a top-N list gives no exact value for another metric. With boundary ties, an omitted product may equal the cutoff, so "not selected" cannot become "strictly fewer customers" or "below the customer-reach tier". A union of revenue-only rows and customer-count-only rows does not supply both measures for every product. Compare measured values for the relevant products, or explain only list membership and the limitation. Do not infer cross-metric counts from rank positions.

## Interpret only supported differences

A ranking establishes relative positions and membership. Product categories or names alone do not establish price levels, unit volumes, motives or causes. Revenue from one customer can include several units across several orders. Revenue per customer may be calculated from matching aggregates, but it is not unit selling price.

If an explanation needs missing price, quantity or population-total measurements, consider revenue-driver-analysis. Obtain them when useful, or give a narrower supported comparison and briefly state the limitation. A top-N list does not establish how concentrated total brand revenue is without the matching whole-brand total.

When quantities are measured, revenue divided by units supports average realized unit selling price. Call it that: item prices do not establish whole-order transaction values or basket totals. Keep descriptive arithmetic distinct from customer motivations or causal drivers.

Measured price/quantity differences between selected leaders describe those products only. They do not establish that overall brand revenue was primarily driven by prices rather than customer volume. A top-products query is a selected subset even when it contains several metrics; it needs matching whole-brand evidence before supporting a whole-brand contribution claim. Without that evidence, keep the explanation explicitly about the selected lists.

Choose compact prose or useful tables according to the user request. Show only relevant columns. Do not reproduce internal evidence records or imply the displayed list explains a cause.

If the source currency is unknown, print bare amounts and a brief shared note. Writing "currency unspecified, shown as $" still invents a currency; a disclaimer does not make that symbol valid. An explicit user-specified currency or conversion assumption may be used for a clearly labelled hypothetical calculation.

Zero sales do not establish zero demand or justify discontinuation without availability, exposure and margin evidence. Later purchases establish later activity, not why an earlier gap occurred. Seasonality, stockouts and replenishment are possible investigations, not measured explanations. For a short recommendation, state the supported conclusion and the most useful missing checks without an unsolicited catalogue-wide report.

Do not justify a recommendation with unmeasured prevalence claims such as "zero-sales quarters often reflect stockouts". Propose checking stock availability instead. A currently cancelled transaction establishes a recorded cancelled transaction, not customer motivation or a measured level of shopper interest.

For an explicitly compact ranking, show product names and the requested metric; include a rank column only if useful. Omit unrequested product IDs when names distinguish the products. Keep IDs in the query/evidence for grouping, stable tie-breaking and follow-ups without necessarily printing them. Include IDs when the user asks for them or duplicate names need disambiguation. Fields obtained for verification or a possible follow-up do not all need to be printed.

State the brand and period once. Consolidate material sales exclusions, unknown currency and tie selection into a brief shared note, ideally one sentence. Do not repeat scope in the introduction, both table headings and a separate notes section. Do not repeat product names, IDs or values already in the tables, or enumerate the whole tie distribution. A short statement that a cutoff is tied can be useful; additional queries solely to decorate a tie footnote are unnecessary.

Avoid units, the other ranking metric, unsolicited overlap analysis and extended methodology in a request for two compact lists. User requests for identifiers, full methodology, all ties or audit details take precedence over these compact defaults. Keep genuine ambiguities or limitations visible. Choose the final wording and table structure to fit the question; these defaults are not a universal answer template.
