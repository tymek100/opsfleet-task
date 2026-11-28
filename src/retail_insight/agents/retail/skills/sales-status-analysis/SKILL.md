---
name: sales-status-analysis
description: Compare qualifying and all-status sales, exclusions, cancellations and returns; distinguish current status-value shares from refund, payment and fulfillment measures.
metadata:
  audience: analyst
  version: "3"
---

# Sales status analysis

The sales relation excludes Cancelled/Returned at BOTH item and order levels; transactions retains all current statuses. Exclude an item once when either status disqualifies it. Compare matching brand and purchase-time boundaries.

Available sale prices and current statuses do not establish collected cash, accounting revenue, refunds, delivered merchandise or customer motivation. Qualifying rows can include Processing/Shipped, so qualifying plus returned value is not necessarily delivered value.

Excluded-value share = excluded sale-price value / all-status sale-price value. Returned sale-price share is a status-value share, not a refund rate. A user-defined proxy needs an explicit label and denominator; missing refund/payment events cannot be replaced with an asserted financial measure.

Current labels cannot reconstruct status transitions, cancellation chronology or earlier status snapshots. A purchase-period filter does not select refund/return dates. Dissatisfaction, stockouts and delivery problems remain hypotheses without separate evidence.

Answer the requested comparison or label correction directly. State the missing evidence instead of inventing a new accounting framework or adding an unrelated status table.
