> Historical plan or validation record. The current implementation is documented in [architecture.md](../architecture.md); ADK, A2A and Phoenix instructions below are superseded.

# Sales and inventory comparison regression

Question: “Compare our Q1 2026 sales with current inventory. Which categories deserve a closer look?”

## Observed failure

The saved coordinator conversation `3f073c8ca1d247cd95714c32b74a5804` attempted retail and inventory delegation together. Before delegation it had spent $0.028476 from its $1 allowance. Retail reserved $0.75 and the completion review reserved $0.168576, leaving $0.052948 temporarily available. Inventory was immediately rejected by the old $0.15 admission threshold, although the retail call was still running and could release unused allowance.

The run completed in 63.743 seconds with $0.214804 accounted and $0.785196 unused. The coordinator accepted the transient rejection as a final limitation, produced a 26-category sales-only report, and inferred inventory-risk rankings without inventory evidence. The runtime reviewer approved all five checks. The warehouse source was Google's public `bigquery-public-data.thelook_ecommerce` sample.

## Changes

- Delegation waits for active child usage to settle when its reservation temporarily prevents admission. It then recalculates available cost and time. The two-child concurrency ceiling and original prompt cap remain enforced.
- Child grants include room for their review and investigation. Errors, missing usage and cancellation retain unverified cost reservations. Waiting stops at the parent's work deadline, preserving time for final review.
- Exact-remainder reservations compare against available funds directly. Re-adding a valid grant to spent and protected amounts could round just above the cap and falsely report exhaustion; the regression covers several caps and prompt sizes without allowing an additional charge.
- Traces distinguish waiting, dispatch, settlement and actual cost/time limits. The reviewer receives this execution metadata alongside the candidate and evidence.
- Coordinator guidance requires both sides of a comparison or an explicitly partial answer. Historical sales remain a benchmark, not a current demand forecast. Sales-only counts cannot establish inventory turnover, surplus, stockout exposure or holding-cost risk.
- The review rubric checks these unsupported diagnoses, including headings and conditional claims. A disclaimer does not validate a risk ranking.
- Review admission and its protected cost include the actual role instructions and response schema. The configured serialization allowance no longer has to cover the entire prompt. If the complete request is still too large, the analyst receives actionable revision feedback rather than an immediate terminal context-limit outcome.

## Verification

Offline regressions exercise simultaneous calls at $1 and $2, settlement and reuse, unknown/invalid usage, transport errors, cancellation, queue deadlines and delegation metadata reaching the real ADK review loop. Large-review tests verify complete evidence delivery and actionable revision when the full request cannot fit. The full offline suite passed 645 tests, with five external-service tests deselected. Ruff and the project-wide Pyright check passed.

The first live run verified the budget repair: inventory waited at 7.047 seconds, received its allowance at 36.751 seconds after retail settled, and completed at 70.383 seconds. The complete run took 107.702 seconds and accounted for $0.506429. Both domains returned evidence, but the answer still incorrectly described modeled stock as physical inventory, recorded cost as tied-up capital, and a historical ratio as current velocity. The reviewer accepted those claims, so coordinator guidance and the review rubric were refined before the final run.

Final live controls use the actual coordinator review guidance. They reject the original sales-only answer for incomplete coverage and unsupported risk ranking, reject the first rerun's three unsupported interpretations, and accept a concise, supported partial answer. These are development regressions, not independent held-out calibration. The reviewer still accepts the long original examples' presentation; a broad verbosity guarantee is not established.

The second live run retrieved both datasets but stopped with `review_context_size` after 99.218 seconds and $0.455731 accounted. The payload fit its evidence limit, but the complete request exceeded the old limit that assumed the role prompt and schema fit inside a 12 KB allowance. This reproduced the separate admission bug fixed above. The saved conversation retains its gathered evidence for the recovery check.

Live verification uses the existing configured Gemini service and public TheLook aggregates. An initial recovery attempt exposed the exact-remainder rounding failure before any specialist dispatch; it accounted for $0.029848. Diagnostic costs before the final recovery total $1.148848. The next request repeats the comparison with an explicit instruction to reuse the results already gathered, capped at $0.85 so all checks remain below the requested $2 total. The application's normal prompt cap remains $1.

Final recovery: approved in 39.63 seconds, with $0.205542 accounted. It reused the saved sales and inventory results, produced a six-category comparison, and framed subsequent investigations as proposed checks. It kept modeled stock distinct from physical inventory and Q1 sales distinct from current demand. The response remains longer than ideal; this check does not establish universal brevity or hallucination prevention. Recovery explicitly requested reuse of existing evidence; it was not another fresh full warehouse run.

Independent Decimal/set checks over all 26 captured categories verified the join population, sales and stock totals, stock-to-sales and cost-to-revenue ratios, and the selected three-category concentration figures. This checks arithmetic against observed tool results, not an independent warehouse snapshot. The successful trace is `79477ef29786af25ba979933fa10647d` in the existing `retail-multi-agent` Phoenix project.

Total accounted live diagnostic cost: **$1.354390**, below the $2 limit. All services are redeployed with the fixes. Local diagnostic artifacts, including the final `answer.md` and `arithmetic-check.json`, are in `.artifacts/sales-inventory-regression/`; these are excluded from Git. Historical stored answers are retained.
