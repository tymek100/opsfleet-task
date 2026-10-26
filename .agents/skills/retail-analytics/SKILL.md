---
name: retail-analytics
description: Define or review retail metrics, BigQuery SQL, analytical evidence, churn investigations, and Golden trios for TheLook. Use when numerical meaning or data scope matters, not for unrelated Python edits.
---

# Retail analytical correctness

Read [client Q&A](../../../docs/architecture.md#confirmed-scope-and-client-decisions) for confirmed rules; use [the assignment](../../../docs/technical_reasoning.md#assignment-coverage) for required capabilities. The [research plan](../../../docs/technical_reasoning.md#model-planning-workflow) contains proposed defaults and analytical pitfalls, not additional client decisions.

## Resolve the analytical contract

Establish the question, authorized brands, metric definition, UTC half-open time window, comparison period, result grain, and required evidence. Ask only when unresolved ambiguity materially affects the answer; use the client's permission to document sensible defaults. Include effective definitions in analytical answers and support overrides without changing access controls.

Inspect schema metadata when needed; do not retrieve raw customer PII merely to understand a table. The required dataset is `bigquery-public-data.thelook_ecommerce` with `orders`, `order_items`, `products`, and `users`.

## Avoid consequential metric mistakes

- Revenue uses eligible item `sale_price`, not product `retail_price`. Document cancellation/return and order/item status handling. Avoid double counting orders after one-to-many joins.
- For top sellers, produce separate rankings by revenue and distinct customers. Group by product ID, show names, and break ties deterministically. Repeated purchases do not create additional distinct customers; counts across products need not sum to a global customer count.
- Apply manager brand scope before spend, orders, and customer-history calculations. Shared customers and mixed-brand orders must not leak restricted spend or activity. CEO has all-brand analytics but remains subject to privacy.
- A 90-day inactivity definition requires an as-of date, eligible population, denominator, and purchase-status rules. Distinguish an inactivity share at month end from newly churned customers during a month. Label the selected interpretation; zero denominator is undefined.
- Compare complete months with comparable boundaries; report numerator, denominator, and percentage-point change. Verify a claimed spike before explaining it. Purchases after the as-of boundary cannot affect historical eligibility/history. Acknowledge later status updates and limits of point-in-time reconstruction.
- Geographic analysis must be aggregate-only. Do not return individual customer ID/state associations or reconstruct them through intermediate model-visible data.
- Distinguish measured contributions, associations, and hypotheses. Do not invent causal explanations from transaction logs.

## Reports and evidence

Clarify the year for ambiguous Q1 requests. Include headline, metric comparison, supported findings, limitations, and proposed actions with success measures. Label proposed targets/owners as proposals. Creating a report does not save it implicitly.

Carry scope, metric/definition version, time boundaries, safe result values, SQL hash, BigQuery job ID, and data freshness through the workflow. Use code to calculate and render numeric tables; narrative references should map to evidence. Test with changed data cases that expose wrong grain or joins, not exact SQL-string matching.

## Golden Knowledge

Define trios and seed illustrative examples; there is no supplied real bucket. Mark provenance, definitions, scope, schema/version compatibility, and review status. Do not present invented figures as live results or examples as analyst-approved without evidence. Retrieval is optional for the prototype. In production, filter by authorization, review new examples, and retire stale ones; reuse analytical methods and run fresh queries for current numbers.
