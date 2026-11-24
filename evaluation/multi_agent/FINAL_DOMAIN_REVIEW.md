# Final focused domain review

Run: `a2a-20261124T201011Z-0d2b1640`.
Scope: inventory scenarios 05, 09 and 12 plus distribution scenario 14; eight answers.
Status: **all eight inspected: 7 PASS, 1 FAIL, 0 execution errors**. Inventory: six PASS. Distribution: one PASS, one FAIL. Automatic grades report eight PASS. This is assistant-conducted manual inspection, not human calibration or a holdout result.

Read each exact final answer, actual question, prior context, schema/skill observations and relevant query evidence. Compare requested and additional numbers with the frozen raw rows and independent references. Apply the same strict semantic rubric as the baseline and first candidate. The raw source is identical across those runs; observed inventory skill version is 1.2. Original responses and automatic grades remain unchanged.

| Agent | Scenario | Turn | Manual verdict | Finding |
|---|---|---|---|---|
| Inventory | scenario-05 | 1 | PASS | Correct five missing-cost units, 27 known-cost units, 32 modeled units and 565.25 known subtotal. Preserves the exact created_at <= cutoff and null/strictly-later sold_at predicate, fixing the first candidate's equality omission. Unknown cost sign, unspecified currency and modeled-stock limits remain explicit. |
| Inventory | scenario-05 | 2 | PASS | Rejects zero substitution without asserting a guaranteed direction of error. Correctly reuses 27 known/five missing/32 total and 565.25 as a partial known subtotal, with precise cutoff semantics and no complete valuation or physical-availability claim. |
| Inventory | scenario-09 | 1 | PASS | Correct one zero-stock product 715 among seven catalog products; remaining six have two to ten units. Query independently counts stock and all available inventory records with distinct IDs. Explicitly leaves never-stocked versus previously-depleted history unresolved, and preserves the sale-at-cutoff exclusion. |
| Inventory | scenario-09 | 2 | PASS | Explicitly states that zero available records cannot establish whether the product was never stocked or previously depleted, fixing the persistent historical overreach. Identifies missing demand, availability and history evidence without asserting actual lost sales. Suggested traffic signals would need corroboration rather than independently proving a lost sale. |
| Inventory | scenario-12 | 1 | PASS | Correctly reports absent purchase-order and scheduled-incoming-shipment data and identifies the procurement source required. Does not invent suppliers, arrival dates or unnecessary stock/facility metrics. Automatic grading now completes successfully rather than failing schema/skill source attribution. |
| Inventory | scenario-12 | 2 | PASS | Correctly distinguishes recorded unit-creation/sale timestamps from procurement milestones and future schedules. The first candidate's database-row-creation and outbound-completion interpretations are absent. No unsupported claim that later records are invisible is made. |
| Distribution | scenario-14 | 1 | PASS | Correctly states that supplier selection and lead times cannot be determined from the available inventory/center schema. Identifies absent supplier, procurement, demand and fulfillment inputs without inventing a replenishment plan or repeating the erroneous five-center count. |
| Distribution | scenario-14 | 2 | FAIL | Missing-input list is appropriate and the erroneous five-center claim is gone. However, the closing statement says the authorized service “tracks only recorded unsold inventory units.” This incorrectly applies the stock relation's membership limit to the full inventory relation, which also exposes sold and later-created rows. Automatic grade is PASS. |

## Remaining finding

**Distribution 14/2: relation visibility versus filtered stock.** The schema explicitly states that inventory includes all authorized records for quality checks. The frozen source includes, for example, a row sold exactly at the cutoff and a row created after it; both remain inventory records while being excluded from stock at that cutoff. Therefore the service's available data cannot be described as only unsold units. This additional closing assertion remains unsupported despite the correct main procurement limitation. It is recorded as a final limitation; no further prompt iteration was performed during this audit.

The six final inventory answers fix the three failures observed in the first candidate's same six turns: exact sale-boundary wording, unsupported exclusion of historical depletion, and timestamp event semantics. The previously correct incoming-order answer now also receives a valid automatic grade. These are observed outcomes for this rerun, not guarantees across future samples.

## Scope and limitations

The first candidate's inventory findings remain in `CANDIDATE_INVENTORY_REVIEW.md`; earlier full-run findings remain in `INVENTORY_REVIEW.md` and `DISTRIBUTION_REVIEW.md`. Final focused results do not replace those observations or establish a new 120-answer full-suite result. Google Maps is intentionally inactive for this deployment, so no live route/weather capability is validated or assumed.
