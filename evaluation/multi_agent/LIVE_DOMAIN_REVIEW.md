# Live BigQuery domain review

Run: `a2a-20261124T202152Z-276d3486`.
Scope: inventory scenario 01 and distribution scenarios 01 and 14; six answers.
Result: **6 PASS, 0 FAIL, 0 ERROR** in assistant-conducted manual inspection. All six automatic answer grades also report PASS. These are observed results, not human calibration or a general accuracy guarantee.

## Source and independent checks

The live BigQuery source was frozen at **2026-11-24T20:21:39.856527+00:00**. The business stock cutoff is **2026-04-01T00:00:00+00:00**. Query evidence carries the same physical table version and uses the authorized Calvin Klein scope. Observed skills are inventory-analysis 1.2 and distribution-analysis 1.3.

The captured source contains 756 products, 12,766 inventory rows, 10 center records, 4,739 order items and 4,677 orders across the evaluation identities' authorized brands. This audit independently selects Calvin Klein before aggregation: 497 catalog products and 8,510 available inventory rows. It does not reuse the synthetic fixture's 32-unit expectation.

Recalculation over distinct raw inventory IDs, using created_at <= cutoff and (sold_at null or strictly later), gives:

| Check | Independently calculated value |
|---|---:|
| Modeled unsold units | 4,929 |
| Distinct stocked products | 495 |
| Units with recorded cost | 4,929 |
| Units with missing cost | 0 |
| Known recorded cost, exact Decimal sum | 144865.2586596839000330 |
| Known recorded cost, rounded to two decimals | 144,865.26 |
| Stock assigned to recognized Houston TX, ID 3 | 4,929 |
| Stock with null or unmatched center attribution | 0 |
| Recognized center directory records | 10 |
| Other recognized centers with scoped stock | 0 |

The BigQuery FLOAT64 sum differs from the independent Decimal sum only below displayed precision; both round to 144,865.26. Currency is unspecified. All required values and optional numeric claims were compared with this live snapshot and its frozen references.

Canonical source hash from the manifest: `86e105a1b66ce5859c78b5f6bd30f595e921173a89ef23db2a6ac7bcaf8a45bf`.
Snapshot file SHA-256: `b98a430fc2c65ef1c88fd8275214c52c37fa5b885d624ab0622cd4db1e3e68cc`.

## Answer inspection

| Agent | Scenario | Turn | Verdict | Finding |
|---|---|---|---|---|
| Inventory | scenario-01 | 1 | PASS | Correct 4,929 modeled units, 495 stocked products and 144,865.26 known cost. Extra 4,929 known-cost units and zero missing costs agree with raw rows. Exact stock predicate, unspecified currency and physical-availability limits are retained. |
| Inventory | scenario-01 | 2 | PASS | In exactly two sentences, rejects treating the modeled count as available-to-promise stock. Identifies missing reservations, physical verification and order commitments. No physical holding or supply commitment is inferred. |
| Distribution | scenario-01 | 1 | PASS | Correct Houston TX/ID 3 count 4,929, explicit Unknown zero and global total 4,929. Additional directory count 10 is independently verified; only Houston has scoped stock. Distinguishes recorded assignment from physical custody, capacity and reservations. The displayed snapshot timestamp is shortened to seconds while query metadata preserves the exact version. |
| Distribution | scenario-01 | 2 | PASS | Correctly explains that dropping the zero-unit Unknown group leaves this total unchanged. Both null and unmatched counts are zero in the live source; no fixture-specific assumption that Unknown must contain six units is carried over. Scope and cutoff are preserved. |
| Distribution | scenario-14 | 1 | PASS | Correctly declines to identify a supplier or lead time without supplier/procurement/operational records. Describes the inventory/product/center sources without claiming they contain only unsold records. No invented supplier, delivery date, extra center count or replenishment commitment appears. |
| Distribution | scenario-14 | 2 | PASS | Lists missing supplier mappings, lead times, purchase orders, demand, inventory-policy and facility-constraint inputs. Explicitly limits the absence of sales relations to this distribution service. The previous fixture-run assertion that the whole service contains only unsold units is absent. |

## Interpretation and retained limitations

The final deployed distribution version avoids the remaining source-visibility defect in this live scenario-14 sample. Its earlier failure remains recorded in `FINAL_DOMAIN_REVIEW.md`; this successful rerun does not overwrite it. This six-answer review covers only the assigned subset of the twelve-answer live run and is not a new full 120-answer evaluation.

These records come from the public TheLook dataset through the real BigQuery backend, not a physical warehouse audit. Historical stock membership does not reconstruct historical knowledge, assignment movements or physical usability. Google Maps is intentionally inactive, so live routes and weather were neither tested nor assumed. Answers remain more verbose than the concise style guidance in places; that did not introduce a material factual error in these six outputs.
