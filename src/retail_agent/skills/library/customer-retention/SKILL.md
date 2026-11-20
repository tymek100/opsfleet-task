---
name: customer-retention
description: Analyze acquisition cohorts, repeat purchasing, retention, churn or inactivity. Use when customer history, time eligibility or cohort denominators determine the answer.
metadata:
  audience: analyst
  version: "1"
---

# Customer retention

Resolve the metric, as-of boundary and eligible population before interpreting a rate. Clarify materially missing years or periods; use a sensible disclosed definition when the request permits one.

## Cohorts and history

Apply authorized brand scope to the full history used for acquisition, repeat-purchase and inactivity calculations. A customer's purchase from another brand must not alter a brand-scoped cohort. Mixed-brand orders need the same care.

Acquisition normally refers to the first qualifying purchase in scoped history, not the first purchase visible after filtering to the requested reporting period. Define whether repeat means multiple orders, separate purchase dates or purchases in a later period; multiple items in one order are not automatically repeat purchases.

## Inactivity and eligibility

For a rolling inactivity threshold, specify the observation date, qualifying purchase rule, eligible population and denominator. Distinguish inactive customers at month end from customers who newly crossed the threshold during that month. Purchases after the observation boundary cannot affect historical status.

Eligibility can change merely because time passes. No new purchases does not mean no new customers became eligible: earlier purchasers can age into a cohort or inactivity threshold. Compare actual eligible populations at each observation date.

Current order/item status fields cannot reconstruct historical status changes. Explain that limitation when a point-in-time interpretation depends on it.

## Compare and report

Use distinct customer IDs at the requested grain. Customer counts across overlapping cohorts or groups are not additive; obtain a distinct union count for an overall total. A zero eligible denominator produces an undefined rate, not zero percent. Show a useful numerator and denominator when the rate's interpretation depends on them.

Check a claimed churn or inactivity spike before explaining it. Compare compatible populations and complete time windows, distinguish percentage-point change from percentage change, and label causal explanations as unverified unless supported by appropriate evidence.
