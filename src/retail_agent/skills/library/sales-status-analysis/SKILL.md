---
name: sales-status-analysis
description: Compare qualifying and all-status sales, exclusions, cancellations and returns; distinguish current status-value shares from refund, payment and fulfillment measures.
metadata:
  audience: analyst
  version: "2"
---

# Sales status analysis

Define the population before calculating a rate. The sales relation excludes Cancelled and Returned at both item and order levels; transactions retains all current statuses. Excluding a row when either status is disallowed avoids counting the same excluded item twice. Use the same brand and purchase-time boundaries in compared totals.

The available measures are item sale prices and current status labels. They do not establish cash collection, recognized accounting revenue, actual refunded amounts, refund dates, completed delivery or customer motivations. Qualifying sales can include Processing and Shipped records. Do not call qualifying plus returned value "delivered merchandise" or infer that cancellations occurred before fulfillment.

An excluded-value share is excluded sale-price value divided by all-status sale-price value. A share currently marked Returned is a status-value share, not a refund rate. Report that supported interpretation when useful and identify the missing refund/payment events instead of inventing a replacement refund metric. Any user-defined proxy needs an explicit label and denominator; it must not silently become an observed financial event rate.

Current statuses cannot reconstruct status transitions or an earlier status snapshot. A purchase-period filter selects when items were created, not when refunds or returns occurred. Reasons such as dissatisfaction, stockouts or delivery problems remain unverified hypotheses unless separately measured.

Avoid adding unsupported prevalence or timing claims such as "cancellations typically occur before fulfillment or settlement" as a justification. The observed status fields do not establish that chronology; the missing refund/payment events already explain why a status-value share is not a refund measure.

Answer the requested comparison concisely. A direct question about whether a label is valid usually needs the measured value and a short explanation, not a new accounting framework or an unsolicited status table.
