---
name: distribution-analysis
description: Center attribution, reconciliation and geographic evidence limits.
metadata:
  audience: analyst
  version: "1.3"
---

Attribute units using the inventory record's center, not an assumed product default. Preserve unmatched or null centers in an unknown group. Center units and item costs can reconcile to totals; distinct products cannot be summed across overlapping center sets. An empty center is different from a center omitted by scope filtering.

Distinguish source capability from the chosen relation. Inventory exposes all authorized recorded units, including sold and later-created records; stock filters modeled membership at the cutoff. Products and centers are directories. Never describe this entire service or its records as only unsold stock because an earlier query used stock. The absence of supplier-order or movement-history fields is a separate, specific limitation.

Stock membership at cutoff T is created_at <= T and (sold_at is null or sold_at > T), counting distinct inventory IDs. A sale exactly at T excludes the unit. This definition does not use retail order/item qualifying-sales statuses. A null sale timestamp provides no shipment evidence. Inventory timestamps do not certify physical receipt, database ingestion, custody or available-to-promise stock.

For elapsed age, "older than N days" requires created_at < T - N days; "at least N days" uses <=. Preserve timestamp precision and inspect equality separately. If the requested age metric is complete integer days, calculate that metric and apply its comparison consistently rather than mixing integer/date truncation with an elapsed-time threshold.

Validate the population of every number, including optional prose totals. Known-center totals exclude Unknown and are not global totals. For top-N plus Other, retain the selected groups and include every remaining group, including Unknown, exactly once. Reconcile their units and known costs with an independent global aggregate. Distinguish distinct stocked products from all catalog products: a product with zero stock belongs only to the latter population. An observed count cannot change meaning merely by changing its label.

Distinct inventory center IDs are not a count of recognized facilities: an unmatched ID may increase that count without identifying a center in the directory. Count recognized centers from the centers relation or an explicit successful match; report unmatched IDs separately as Unknown. Do not infer additional facilities, names or operating warehouses from unmatched identifiers.

Check the source expression before naming a center metric. COUNT(DISTINCT inventory_center_id) returns distinct non-null recorded item-center IDs, including unmatched values; its label must preserve that population. After joining scoped stock to the center directory, COUNT(DISTINCT c.center_id) counts recognized centers represented in that stock, while a count over the directory alone can include centers without scoped stock. These are different metrics. Never translate a raw-ID count into a facility count in a parenthesis, caveat or optional summary. Directory recognition itself does not verify a physically operating warehouse.

A failed join proves only that a recorded ID has no match in the available directory. It does not prove the ID is erroneous, that no facility exists or operates, or why attribution is missing. Historical stock membership from creation/sale timestamps does not turn the recorded item-center field into historical assignment or movement evidence; those claims require appropriate assignment history.

Stock age measures elapsed time from recorded creation, not inventory turnover, demand velocity, processing speed or late-shipment rate. Do not say high age "reflects overstocking", "means low demand" or "shows obsolescence" without additional evidence; these are hypotheses to investigate. Turnover requires an explicit flow measure, period and suitable inventory denominator. Shipment timeliness requires promised and actual shipment events. A statement rejecting one unsupported conclusion must not replace it with another.

Describe centers as recorded item attribution, not verified storage or physical custody. Empty snapshot results do not prove complete historical absence. Missing cost remains unknown: zero substitution is an unverified assumption, not proof of a specific error direction. Generic caveats do not repair stronger unsupported claims in the body.

Facility coordinates are public synthetic dataset attributes. A Maps road route is not straight-line distance, a truck route, warehouse capacity or delivery commitment. Use actual returned units and attribution links. Weather observations refer to their timestamps; current observations do not explain past delays. Without configured Maps, say the route/weather information is unavailable.

Describe Maps limitations only for the enabled tools and data actually returned in this run. Missing historical evidence from those tools does not establish that every Google Maps product lacks historical capabilities.

Stock transfers require capacity, constraints and explicit authorization through an actual write capability. This agent has no such capability. Present conditional recommendations and identify missing inputs instead of claiming execution.
