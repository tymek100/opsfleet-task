# Distribution candidate review

Run: `a2a-20261124T195511Z-d0f6edc6`.
Status: complete; **all 10 answers reviewed: 8 PASS, 2 FAIL, 0 ERROR**. Automatic answer grades are **10 PASS**. This assistant-authored audit is separate from automatic grading and human calibration.

The focused rerun includes both turns of distribution scenarios 02, 04, 07, 10 and 14. The original baseline is `a2a-20261124T191812Z-f59d6715`; its independent review found seven failures among these ten answers. Preserve those answers and grades unchanged.

## Review criteria

- Scenario 02: 32 scoped units, 26 at known centers, top-three values 8/8/6 and Other 10; inventory membership uses the recorded creation/sale boundary, not qualifying retail sales.
- Scenario 04: seven catalog products, six stocked products; per-center distinct product counts are nonadditive.
- Scenario 07: 12 units strictly older than 90 days; aging alone does not measure shipping performance, turnover or demand velocity.
- Scenario 10: absent shipment/SLA data cannot be replaced with stock age or categorical explanations of overstocking/obsolescence.
- Scenario 14: missing supplier/lead-time data requires abstention; four known centers must not become five facilities by counting unmapped ID 999.

Compare published text, additional assertions and tool observations against the candidate's frozen raw snapshot and independent references. Use PASS for a supported completed answer, FAIL for substantive incorrectness or unsupported assertions, and ERROR when incomplete execution prevents review. Record disagreements with automatic grades without overwriting them.

The candidate and baseline `snapshot.json` files have identical SHA-256 `59a85c3399a4583312a7b20ed6a79f37d058c205d171952efeffd78796960a5a`. This comparison therefore uses the same source facts.

## Turn-by-turn review

| Scenario | Turn | Baseline manual verdict | Candidate manual verdict | Finding |
|---|---:|---|---|---|
| scenario-02 | 1 | FAIL | PASS | Correct top-three ranking 8/8/6; distinguishes 22 top-three, 26 known-center and 32 global units, including six Unknown. Explicit reconciliation query supports the totals. No qualifying-sales definition substitution. |
| scenario-02 | 2 | FAIL | PASS | Correct 8/8/6/Other 10/global 32 and shares 25%/25%/18.75%/31.25%. Other decomposes as Los Angeles four plus six Unknown. Preserves modeled-stock and facility-attribution limitations. |
| scenario-04 | 1 | PASS | PASS | Correct six stocked versus seven catalog products and all center unit/distinct counts. Unknown combines null and ID 999 without adding their overlapping product sets. Several redundant queries affect efficiency, not correctness. |
| scenario-04 | 2 | FAIL | PASS | Correctly explains distinct-count nonadditivity: 24 summed group memberships versus six stocked products, average four group memberships per product, and 32 additive inventory units. Does not substitute catalog breadth for stocked breadth. The internal answer ID is unnecessary presentation detail. |
| scenario-07 | 1 | PASS | PASS | Correct 12 aged units, 10 exactly-90-day units and 10 younger units. Center subtotals and 182-day age of the October records match the frozen snapshot. Keeps recorded attribution distinct from physical custody. |
| scenario-07 | 2 | FAIL | PASS | Rejects shipping-speed inference and defines age only as elapsed time since creation. Explicitly labels operational explanations as unverified hypotheses; does not claim age measures turnover or demand velocity. |
| scenario-10 | 1 | PASS | PASS | Correctly abstains from warehouse SLA and late-shipment metrics because required promises and shipment observations are absent from this specialist's schema. |
| scenario-10 | 2 | FAIL | PASS | Refuses to relabel stock age as late-shipment rate. Potential seasonal/slow-moving-stock explanations use conditional language rather than asserting the observed cause. Requires actual dispatch timestamps and promised deadlines. |
| scenario-14 | 1 | FAIL | FAIL | Supplier/lead-time abstention is correct, but the optional summary again presents five recorded IDs as five inventory centers: “32 unsold stock units across 6 distinct products distributed among 5 recorded inventory centers.” SQL counts distinct non-null raw IDs, including unmapped 999. There are four recognized centers, three unmapped units and three null units. The null units are not among those five IDs. |
| scenario-14 | 2 | FAIL | FAIL | Useful missing-input list, but repeats “5 recorded inventory centers” without distinguishing the unmapped identifier from known facilities or preserving the null-attribution group. The repeated query still counts raw IDs without joining the center directory. |

## Comparison and remaining defect

Five of the seven baseline failures are resolved in this focused run: both scenario 02 answers and the follow-ups for scenarios 04, 07 and 10. All three previously passing answers still pass. Both scenario 14 answers remain incorrect; the word “recorded” alone does not establish that all five identifiers correspond to centers or that all 32 units are assigned among them.

A valid optional summary could state **four recognized centers, five distinct non-null recorded item-center IDs (including unmapped 999), and six units with unknown attribution**, or omit these unrelated counts from a supplier-data refusal. The current candidate grader returned PASS for all ten answers, so it still misses both population/attribution defects. Preserve those automatic scores and the baseline outcomes; this audit records the disagreement rather than replacing them.

This is a targeted retry on previously inspected failures, not an independent holdout or a production reliability estimate. Runtime, graders and deployment were unchanged during review.

## Deployment check

Before the candidate run, all four containers were healthy and used `/data/fixture/fixture-9431eaba980db40b53b2/a2a.sqlite3`, initially with zero tasks and contexts. Existing databases directly under `/data` remained intact with their historical rows; the new profile did not load them. Public health responses exposed only status, role, backend, fixture hash and Maps credential availability, with no credential values or local paths. This verifies the observed deployment layout, not a live BigQuery switch.
