---
name: revenue-driver-analysis
description: Investigate why revenue differs or changes, including prices, quantities, customers, order patterns and revenue concentration. Use when an explanation needs more than ranking membership.
metadata:
  audience: analyst
  version: "4"
---

# Revenue driver analysis

Select measurements for the question rather than collecting every metric. Read [the measurement guide](references/measurement-guide.md) through load_skill_resource when useful.

Use qualifying item sale_price, not catalog retail_price or inferred prices. Confirm row grain before counting units; count order/customer IDs distinctly after joins. Revenue per customer, revenue per order and realized unit price require their respective matching denominators. One customer or order can include multiple units.

Concentration and driver claims must match the measured population. Selected products need the same-period whole-population total to establish a share; category numerators need category denominators. Measurements for selected leaders do not establish the primary driver of the whole brand.

Separate arithmetic contribution, association and cause. A stated price/quantity decomposition describes arithmetic effects, while product mix can change aggregate average prices without changes to individual prices. Neither proves motivations or campaign effects.

Revenue plus distinct customers supports revenue per customer and reach, not unit-price or volume claims. Obtain missing measurements or narrow the answer. Label useful hypotheses as unverified with their evidence gap; a hedge alone does not make a story supported.

Active-customer growth is not acquisition. New-to-brand status requires first qualifying purchases across available scoped history and does not establish company-wide acquisition. Absent sales do not prove absent demand, stockouts or seasonality. Preserve follow-up populations and do not treat prior approval as evidence.
