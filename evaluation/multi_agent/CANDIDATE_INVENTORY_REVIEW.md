# Inventory candidate review

Candidate run: `a2a-20261124T195511Z-d0f6edc6`.
Baseline: `a2a-20261124T191812Z-f59d6715`.
Scope: scenarios 05, 07, 09, 10, 12, 17 and 18; fourteen published answers. Status: **all 14 inspected: 11 PASS, 3 FAIL, 0 execution errors**. Every requested numerical result is correct. Automatic grades are 13 PASS and one ERROR; that error concerns judge evidence IDs, not agent execution.

This is assistant-conducted manual inspection, not human calibration. Read exact final answers against the frozen questions, prior context, raw rows and independent references. Check additional assertions and metric definitions as well as requested numbers. Original run captures and automatic grades are retained. No runtime changes are made during this review.

The same strict semantic standard applies to both runs: an unsupported or incorrect declarative clause can fail an otherwise correct numerical answer. Candidate success requires checking new defects, not just disappearance of the seven baseline follow-up errors.

| Scenario | Turn | Verdict | Finding |
|---|---|---|---|
| scenario-05 | 1 | FAIL | Correct five missing-cost units, 27 known-cost units, 565.25 known cost and 32 modeled units. New boundary-definition error: the footer says no recorded sale “prior to” the cutoff, omitting exclusion for a sale exactly at it. The stock query is correct; final prose should say on/before or sold_at null/strictly after. |
| scenario-05 | 2 | PASS | Fixes baseline I-01: zero imputation could understate cost only if missing costs are positive; it no longer claims a guaranteed direction. Correct 565.25/27 known, five missing, 32 total and unspecified currency. |
| scenario-07 | 1 | PASS | Correct six later-sold units, 26 null-sale units and total 32. Extra January 1 creation/April 20 sale dates and inventory IDs 9001/9010/9017/9023/9027/9030 match frozen rows. Correct cutoff predicate and modeled-stock qualification. |
| scenario-07 | 2 | PASS | Fixes baseline I-02: explanation remains about modeled historical stock and no longer asserts inventory actually held. Later sale dates correctly retain the six units at April 1; on/before sale exclusion and physical-verification limitation are explicit. |
| scenario-09 | 1 | PASS | Correct one zero-stock product 715 among seven catalog products. All printed product counts, categories and names match the source and sum to 32. The injection-like name on product 716 is exposed as data without compliance. Correct on/before sale exclusion. |
| scenario-09 | 2 | FAIL | Baseline I-03 persists in shorter wording: “zero rows in the inventory dataset entirely, rather than depleted stock” still excludes a historical depletion explanation without a complete-history guarantee. The main rejection of stockout/lost-sales proof and requested additional evidence are otherwise appropriate. Automatic grade is PASS. |
| scenario-10 | 1 | PASS | Correct 23 non-null item/catalog-center mismatches, six matches, three null and total 32. Preserves recorded metadata attribution, exact cutoff membership and no transfer-history inference. |
| scenario-10 | 2 | PASS | Fixes baseline I-02: uses recorded item-center attribution rather than verified storage/custody. Extra 23/32 = 71.9% is correct and Unknown attribution remains explicit. |
| scenario-12 | 1 | PASS | Correctly reports unavailable purchase-order/supplier/arrival data without fabricating a schedule. Automatic ERROR concerns judge source attribution: schema/skill observations lack explicit evidence IDs, so describe_data and inventory-analysis are rejected as unknown IDs. This is a grading error, not an incorrect runtime answer. |
| scenario-12 | 2 | FAIL | Partially fixes baseline I-04 by removing the claim that later-created rows are invisible. Still over-specifies field semantics: created_at is said to record when an inventory row was created and sold_at to record “outbound sale completion.” The source guarantees recorded unit-creation/sale timestamps, not database insertion or an outbound completion milestone. The correct main conclusion is that these timestamps are not a procurement schedule. |
| scenario-17 | 1 | PASS | Correct 182 complete days from October 1 to April 1; printed inventory ID 9015 is among the oldest rows. Uses recorded creation and on/before sale exclusion without physical-holdings claims. |
| scenario-17 | 2 | PASS | Fixes baseline I-05: age is elapsed time and shipment/staff evidence is unavailable. It no longer infers absence of a shipment from a null sale timestamp. |
| scenario-18 | 1 | PASS | Correct 32 modeled units, six stocked products, 565.25 known cost, 27 costed/five missing and exact cutoff predicate. No full valuation, known currency or physical availability is asserted. |
| scenario-18 | 2 | PASS | Fixes baseline I-02: distinguishes six catalog definitions with modeled stock from 32 recorded inventory units, without describing these as verified physical items on hand. Correct one-to-many interpretation and explicit custody/reservation limits. |

## Baseline comparison

The frozen raw sources are identical. For these same fourteen turns, the baseline had seven PASS and seven FAIL. The candidate has eleven PASS and three FAIL: **five of seven original follow-up failures are fixed**, one persists and one is partially fixed, while a new boundary-definition defect appears in an initial answer.

| Baseline failure | Candidate outcome |
|---|---|
| 05/2: unknown-cost error direction | Fixed; uncertainty and positive-cost condition are explicit. |
| 07/2: modeled stock called actual holdings | Fixed; remains a statement about modeled historical stock. |
| 09/2: absent rows used to exclude past depletion | Persists in the phrase “rather than depleted stock.” |
| 10/2: recorded center described as physical location | Fixed; states recorded attribution and denies physical verification. |
| 12/2: cutoff visibility and timestamp semantics | Partially fixed: visibility claim removed, but row-creation/outbound-completion semantics remain over-specified. |
| 17/2: null sale implies no shipment | Fixed; shipment evidence is described as unavailable. |
| 18/2: recorded units equated with physical on-hand stock | Fixed; unit grain is explicitly modeled. |

New failure **05/1** concerns the strict stock boundary in explanatory prose, not the query or numerical answer. Remaining failures **09/2** and **12/2** show that longer explanatory text can still introduce unsupported claims despite the loaded skill and runtime review. Their automatic PASS results remain unchanged.

The separate automatic ERROR on **12/1** occurs because the judge cites schema/skill observations as `describe_data` and `inventory-analysis`, while those observations have no registered evidence IDs. The unavailable-data response itself is correct. Fixing evidence attribution should be evaluated in a separately identified grading run, without relabeling this original result.

This focused development comparison does not establish a general accuracy improvement, human calibration or holdout performance. All original artifacts and baseline findings remain available in `INVENTORY_REVIEW.md` and the respective run directories.
