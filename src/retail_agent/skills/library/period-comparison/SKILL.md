---
name: period-comparison
description: Compare revenue or other metrics across months, quarters or other periods, including partial periods, percentage changes and zero baselines.
metadata:
  audience: analyst
  version: "1"
---

# Period comparison

Make the periods comparable before interpreting a difference. Use UTC half-open boundaries, with the start included and the end excluded, and resolve a materially missing year. Label calendar periods clearly; do not compare an incomplete current period with a full previous period without disclosing or adjusting the difference.

Keep the metric definition, status policy, entity grain, authorized scope and selected population consistent. Qualifying sales exclude Cancelled and Returned at both item and order levels; they are not necessarily Complete-only. User-requested status overrides need an explicit definition over the permitted relations.

Absolute change is later minus earlier. Percentage change divides that difference by the earlier value; a zero baseline makes this rate undefined. For proportions, percentage-point change is the difference between percentages, while percentage change measures the relative change in the proportion. Label the quantity actually calculated.

Do not sum monthly distinct customers or orders to obtain a quarter total when IDs can occur in multiple months. Calculate the union-level distinct count, or omit an unrequested total. Distinguish an empty result from a measured zero, and do not invent activity where there is no eligible population.

Verify that a claimed increase or decline exists before explaining it. A measured change alone does not establish its cause. Load revenue-driver-analysis when price, quantity or customer patterns are material to the requested interpretation; otherwise a concise supported observation may be enough.

Choose a table only when it makes the comparison clearer or the user requests it. Use matching precision, concise units and plain arithmetic; do not invent a currency symbol or append unrequested totals.
