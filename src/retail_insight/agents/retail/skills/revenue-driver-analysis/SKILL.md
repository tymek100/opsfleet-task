---
name: revenue-driver-analysis
description: Investigate why revenue differs or changes, including prices, quantities, customers, order patterns and revenue concentration. Use when an explanation needs more than ranking membership.
metadata:
  audience: analyst
  version: "3"
---

# Revenue driver analysis

Select the measurements needed for the question; a simple factual comparison does not require every possible metric. See [the measurement guide](references/measurement-guide.md) when deciding which quantities support an interpretation. Load it with load_skill_resource only when the additional detail is useful.

## Establish the measurements

Use realized sale_price from qualifying item sales. Do not substitute catalogue retail_price or infer prices from product names. Units, orders and customers are separate measures. Confirm the source grain before counting units, and count order/customer IDs distinctly after item-level joins.

Revenue per customer is revenue divided by distinct customers. Revenue per order is revenue divided by distinct orders. Average realized unit selling price needs a matching quantity denominator. Neither one customer nor one order proves that only one unit was sold.

Concentration claims require a scoped, same-period total. Calculate the selected products' share of that total; do not call a top-N list most of the business without the denominator. Keep category-specific numerators paired with category-specific denominators.

The same scope requirement applies to driver language, not just explicit percentages. Measuring prices, quantities and customers for selected products does not show what primarily generated the whole brand's revenue. Match the population of the claimed driver/contribution to the population actually measured, or narrow the conclusion to that subset.

## Explain the evidence

Distinguish a measured contribution, an association and a causal explanation. A price-times-quantity decomposition can describe arithmetic contributions under stated definitions, but transaction totals alone do not establish customer motivations or the effect of a campaign. Shifts in the mix of products can change an overall average price even when individual product prices are unchanged.

If only revenue and distinct customers are available, discuss revenue per customer and reach. Higher/lower-priced and higher/lower-volume claims require actual price or quantity measurements. A customer can buy multiple units. An illustrative story introduced with can, suggests or likely still needs to be clearly identified as unverified if it is not established for these data.

Possible explanations may be useful when labelled hypotheses, with the evidence gap and alternatives made clear. Choose whether further queries are warranted or whether a narrower supported answer meets the request. Preserve selected populations from earlier turns, and do not treat a prior answer's approval as new evidence.

An increase in active customers is not a measurement of acquisition. New-to-brand status requires first qualifying purchases across all available authorized history; it cannot establish company-wide acquisition or prove why revenue changed. Similarly, absent sales do not establish absent demand, stockouts or seasonality. If those inputs are unavailable, state the limited finding and propose the missing checks without presenting a business story as fact.
