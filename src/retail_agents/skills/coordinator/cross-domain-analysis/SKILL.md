---
name: cross-domain-analysis
description: Delegate and reconcile sales, inventory and distribution evidence.
metadata:
  audience: analyst
  version: "1.3"
---

Choose specialists according to needed capabilities and observed gaps. Preserve identity, scope, snapshot and business cutoff. Forward evidence only when relevant; narratives are not substitutes for underlying rows. Ask a focused follow-up if evidence definitions or grain differ.

For sales/stock comparisons join product identifiers and compatible time definitions. Revenue is not demand units. Divide units by all calendar days in the stated demand window. Report zero-demand coverage as undefined and forecasts as conditional. Avoid summing distinct customer/product counts across overlapping groups.

Never UNION or sum a product total with that same product's center detail, missing-center detail or another overlapping subtotal. A total already includes its qualifying detail rows. Use one authoritative table at the required grain, or aggregate disjoint detail rows and reconcile to the independent total. A plausible query result is not sufficient evidence if the query duplicated its input population. Do not relabel modeled unsold inventory as stock physically available to promise.

A top-N list does not describe the full population or establish a cause. Reconcile parts to totals before explaining contributions. Missing capacity, prices, supplier lead times or Maps results are explicit limitations. Never claim to execute transfers or purchases. The final combined answer requires its own review even if every specialist was approved.

Do not label qualifying sales as fulfilled, delivered or completed demand unless the actual status filter establishes that narrower population. An aggregate stock-to-sales ratio does not prove adequate supply, rule out product-level stockouts or measure lost sales. Modeled unsold units are not necessarily usable supply or future units available for sale. Hypothetical coverage assumes the stated demand rate and ignores unobserved reservations and operational constraints; preserve those qualifications beside the claim.

Reject a candidate's unsupported physical, historical or causal assertion even if a later footer adds a correct caveat. For example, "stock proves available supply" followed by "physical availability is unknown" remains contradictory. Prefer the short supported answer over speculative explanations or extra figures.

Check a delegated result's boundary against the user's words before reusing it. "Older than N days" excludes records exactly N days old; "at least N days" includes them. Retain timestamp precision and the chosen cutoff rather than silently substituting calendar-date comparisons. Recorded creation time does not establish a procurement, receipt or ingestion date.

Describe Maps availability using the configured tool and its actual response. An unavailable key or a live observation does not establish what every Google Maps product can or cannot provide historically. Current routing or weather cannot by itself explain an earlier sales or stock change.

Keep relation and join semantics precise. The inventory relation can expose sold or future-created rows even when stock at the chosen cutoff excludes them. A center ID with no directory match is an unmatched attribution, not proof of an erroneous key or a nonexistent or inactive facility. A current recorded center assignment does not reconstruct historical assignment or stock movement merely because a stock cutoff is historical.

Runtime review is a fallible quality check. Its approval does not confirm that SQL, calculations or operational conclusions are correct. Describe actual checks and evidence, and acknowledge their limits; never cite approval as validation of the answer itself.

Reject an unsupported inference without asserting its opposite. A stock-to-sales comparison establishes neither shortage nor surplus, and subtracting a past sales flow from a stock snapshot cannot measure lost sales. Headings and short labels such as "Surplus" are claims too. Say which conclusion is undetermined instead of replacing it with an alternative diagnosis or an unrequested coverage forecast.

Do not confuse the scope of an investigation with source capability. A specialist's 30-day query does not establish that longer sales or order history is unavailable. Distinguish missing source fields from unqueried data and request schema/capability clarification when it matters to the conclusion.

Preserve the complete requested population when delegating and reviewing SQL. Missing center IDs and non-null IDs without a directory match are different disjoint groups. If the question asks for unknown attribution, include both and reconcile them; filtering only IS NULL does not cover unmatched IDs. Keep unit counts and their known-cost subtotal on the same population.

Preserve exact predicates when describing earlier results on a follow-up: created_at < boundary excludes equality and cannot become "on or before". Prefer omitting an unnecessary repeated definition over an inaccurate paraphrase. Explain stock age as elapsed time from recorded creation to the chosen cutoff; business explanations involving intake, replenishment or sales velocity need separate evidence and must not replace that measured definition.

An advertised tool does not establish that its external provider is configured or that it returned usable data. Preserve known unavailable-service status on follow-ups. When proposing work using only currently available data, omit unavailable routing/weather inputs or explicitly make them conditional on later configuration and a successful call. Keep any inventory inputs labeled modeled units; do not shorten them to physical or on-hand stock.

An age explicitly measured in complete days is the floored elapsed-day count. For integer N, complete_days > N is not equivalent to elapsed_time > N days: a unit aged N days and twelve hours has only N complete days. State and preserve the requested metric, including sub-day boundaries. Inventory aging uses unit creation, not a catalog-product timestamp. Facility directory fields do not include operating status, opening hours or capacity; verify capabilities before proposing them.
