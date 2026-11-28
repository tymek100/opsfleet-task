---
name: distribution-analysis
description: Center attribution, reconciliation and geographic evidence limits.
metadata:
  audience: analyst
  version: "2"
---

# Distribution analysis

Attribute units to the inventory item's center. Preserve null and unmatched IDs in Unknown; those are disjoint groups and both belong in unknown attribution. An unmatched ID does not establish an erroneous identifier or nonexistent/nonoperating facility.

Keep these counts distinct:

| Expression/population | Meaning |
| --- | --- |
| COUNT(DISTINCT inventory_center_id) | Non-null recorded IDs, including unmatched ones |
| Distinct successfully joined center IDs in scoped stock | Recognized centers represented in that stock |
| Center directory count | Recognized entries, possibly including centers without scoped stock |

Directory recognition is not proof of operating status or physical custody. Empty centers differ from centers excluded by scope. Current recorded assignment does not reconstruct historical assignments or movement.

Inventory contains all authorized recorded units; stock filters modeled membership. At cutoff T, include created_at <= T and (sold_at IS NULL OR sold_at > T), counting distinct inventory IDs. A sale exactly at T excludes the unit. Retail status filters are a separate sales definition. Null sold_at does not establish shipment status.

Age uses recorded unit creation, not receipt, ingestion or catalog dates. "Older than N days" uses < T - N days; "at least" uses <=. Preserve timestamp precision. Complete-day thresholds require floored elapsed days, not a different elapsed-time predicate. Age alone measures neither turnover, demand, overstocking nor shipment delays.

Reconcile units and known costs, including Unknown, against a global aggregate. For top N plus Other, include each remaining group once. Distinct stocked products differ from catalog products and cannot be added across overlapping center groups. Missing costs stay unknown; absent snapshot rows do not establish complete historical absence.

## Maps and operations

Dataset facility coordinates are synthetic attributes. Use returned Maps units, timestamps and attribution links. Driving routes are not straight-line distances, truck routes, capacity or delivery commitments. Live weather cannot explain past delays.

An advertised tool does not prove its provider is configured. If Maps is unavailable, state the specific tool limitation; do not generalize it to every Maps product. Transfers need capacity, operational constraints and a write capability that this agent lacks. Propose checks without claiming execution or physical availability.
