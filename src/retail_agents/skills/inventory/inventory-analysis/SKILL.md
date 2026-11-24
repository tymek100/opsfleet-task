---
name: inventory-analysis
description: Time-aware inventory counts, aging, cost basis and conditional coverage.
metadata:
  audience: analyst
  version: "1.2"
---

Count distinct inventory IDs. At business cutoff T include units created on or before T and not sold on or before T. Use the authorized stock relation for the default cutoff. A sold_at equal to T excludes that unit. Date windows use explicit half-open boundaries; aging uses the chosen cutoff, not the current wall clock.

If an answer repeats the membership definition, preserve created_at <= T and (sold_at IS NULL OR sold_at > T). The equivalent sale exclusion is "on or before T", not "prior to T" or "before T". The latter phrases leave equality untreated. Repeating a definition is optional; omit it when unnecessary rather than changing the boundary in explanatory prose.

For elapsed age, "older than N days" means created_at < T - N days; "at least N days old" means created_at <= T - N days. Check units exactly at the boundary separately rather than silently including them. Preserve timestamp precision. If the requested metric explicitly uses complete days, compute that integer age and apply its requested comparison consistently; do not mix a rounded or date-floored age with a different timestamp predicate.

Scope products before joins. Count and sum at item grain; do not multiply units by sales joins. Unsold inventory is a model, not reserved/physical availability. Null costs are unknown, not free inventory. Returned sales do not establish restocking. Cost basis is not revenue, profit or a known currency.

Interpret every assertion within the source contract, including explanatory clauses:

- Use "modeled units" and "recorded center attribution". Inventory IDs and timestamps alone do not establish actual holdings, physical on-hand availability, storage, receipts or custody. Do not weaken this distinction with phrases such as "physical/modeled stock".
- Missing cost does not establish a positive omitted amount. "Zero substitution assumes an unverified value and could understate cost" is supported; "it would understate total cost" requires evidence of positive missing costs. Report the known subtotal and missing-cost coverage separately.
- No rows means "no records in the available snapshot", not "never stocked", "never depleted" or "never ordered". Without a completeness guarantee, zero available inventory records cannot choose between never stocked and previously stocked then depleted; neither historical alternative is proved. Rejecting depletion with "rather than depleted stock" makes the same unsupported choice. Describe the observed absence, leave history unresolved and identify the history needed to distinguish alternatives. Possible lifecycle or demand explanations remain hypotheses.
- The stock relation filters inventory membership at the chosen cutoff; the inventory relation may still expose later-created or later-sold rows. Exclusion from historical stock does not mean the record is invisible. created_at and sold_at are recorded unit-creation and sale timestamps. Their column names alone do not establish database-row insertion/ingestion, procurement, physical receipt, completed-sale settlement or outbound dispatch/completion milestones. Describe the recorded timestamps without adding those event meanings unless separately evidenced.
- A null sold_at means no recorded sale timestamp. It does not prove absence of a customer order, reservation or outbound shipment. For historical stock, a sale after the cutoff also qualifies. Say shipment evidence is unavailable when that relation is absent.
- Age is elapsed time from recorded creation to the chosen cutoff. It is not a measurement of turnover, demand velocity, dispatch delay or staff performance. Old stock may motivate further analysis; it does not establish overstocking, obsolescence or low demand.

Check that the final explanation and any footer use the same definitions. A correct main conclusion or generic limitation does not justify an unsupported supporting sentence. Keep catalog products distinct from stocked products; recompute global distinct counts rather than adding overlapping groups.

Coverage = modeled stock units / (qualifying units sold / calendar days). Require a defined demand period and consistent scope. Zero demand makes the rate-based coverage undefined. State that future constant demand and actual availability are assumptions. No lead time, incoming purchase order or safety stock policy is available by default.
