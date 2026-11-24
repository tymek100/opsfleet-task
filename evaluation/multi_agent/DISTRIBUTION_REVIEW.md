# Distribution answer review

Run: `a2a-20261124T191812Z-f59d6715`.
Status: complete; all 40 distribution answers reviewed. Independent assistant verdicts: **33 PASS, 7 FAIL, 0 ERROR**. The automatic answer grader returned **40 PASS**, including the seven failures identified below.

This is an assistant-authored review of the published answer text, supporting SQL and tool observations. It is separate from the automatic judge scores and is not human calibration. Original run captures and grades are unchanged.

## Evidence and method

- Read the frozen `scenarios.json`, `references.json` and `snapshot.json` under `.artifacts/multi-agent/a2a-20261124T191812Z-f59d6715/`.
- Compare both turns of every distribution scenario against the independent Decimal/set oracle and direct calculations over the raw snapshot.
- Inspect additional numerical assertions, SQL grain, scope, date boundaries, Unknown buckets, follow-up context and unsupported operational explanations.
- Use **PASS** for supported answers satisfying the request, **FAIL** for substantive incorrectness or unsupported assertions, and **ERROR** for missing/incomplete execution that prevents a completed answer review. Style observations do not automatically fail a correct answer.

The business cutoff is `2026-04-01T00:00:00+00:00`. Alice has Calvin Klein scope; scenario 20 uses Bob's Levi's scope. Modeled unsold stock requires creation at or before the cutoff and no recorded sale at or before it.

Independent Calvin Klein reconciliation:

| Inventory-item center | Units | Distinct products | Known recorded cost | Units with missing cost | Units older than 90 days |
|---|---:|---:|---:|---:|---:|
| Memphis TN | 8 | 6 | 166.00 | 0 | 8 |
| Chicago IL | 8 | 6 | 164.50 | 0 | 0 |
| Houston TX | 6 | 5 | 20.25 | 5 | 0 |
| Los Angeles CA | 4 | 4 | 87.00 | 0 | 4 |
| Unknown | 6 | 3 | 127.50 | 0 | 0 |
| Global | 32 | 6 | 565.25 | 5 | 12 |

Product counts are distinct globally and therefore not additive across centers. Currency is unspecified. The top stocked products are 710 with 10 units, 711 with 7, and 712 with 6. There are 23 non-null item/catalog center conflicts and one scoped record sold exactly at the cutoff. Bob has five modeled units, one in each of the four known centers and one Unknown.

## Turn-by-turn review

| Scenario | Turn | Verdict | Review finding |
|---|---:|---|---|
| scenario-01 | 1 | PASS | All five groups and total 32 match raw rows. Unknown correctly combines three null and three unmapped IDs. Shares round correctly; modeled stock is distinguished from physical availability. SQL uses inventory-item grain and preserves unmatched centers. |
| scenario-01 | 2 | PASS | Correctly explains 32 minus six Unknown units equals 26; the 18.8% share is rounded correctly. Preserves the cutoff and accounting interpretation. Repeats prior queries unnecessarily, which affects efficiency rather than answer correctness. |
| scenario-02 | 1 | FAIL | Correct ranking 8/8/6 and ID tie-break, but falsely claims a brand-wide total of 26 after also listing four Los Angeles and six Unknown units. The correct total is 32. Its definition also substitutes qualifying sales for the inventory `sold_at` boundary. |
| scenario-02 | 2 | FAIL | Table correctly repairs the total to 32 and Other to 10, but repeats the incorrect definition “without qualifying sales before that cutoff.” Inventory membership uses recorded `sold_at`, independently of retail qualifying-order status, and excludes a sale exactly at the cutoff. |
| scenario-03 | 1 | PASS | Unknown six units and known cost 127.50 match raw records; null and unmapped subgroups are three units and 63.75 each. Product-level cost details and extra 32/565.25 totals are supported. “Recorded inventory center” would be more precise than “recorded fulfillment center.” |
| scenario-03 | 2 | PASS | Refuses silent catalog imputation and retains Unknown. Explicitly hypothetical catalog mapping to center 1 (four units) and center 2 (two) matches raw rows; it does not establish physical custody. “Company-wide” should be “authorized-brand-wide” in this scoped conversation. |
| scenario-04 | 1 | PASS | Correct center distinct counts, global six products and 32 units. Splits null/unrecognized rows but explicitly gives their combined Unknown distinct count as three, avoiding additive double counting. Inventory-center wording should remain “recorded,” not imply verified physical location. |
| scenario-04 | 2 | FAIL | Correctly explains nonadditivity and the displayed-row sum of 27, but falsely says the two largest centers carry “all 6 catalog products.” The authorized catalog has seven products; six have modeled stock and product 715 has none. |
| scenario-05 | 1 | PASS | SQL applies both non-null checks before inequality. Counts reconcile as 23 mismatches + six matches + three nulls = 32. Extra six-product and 393.25 recorded-cost figures are supported; no transfer or capacity inference. |
| scenario-05 | 2 | PASS | Correctly rejects transfer proof and identifies missing movement/custody evidence. Alternative operational explanations are generic possibilities, not established causes in this dataset; “could arise” would be safer wording than “commonly arise.” |
| scenario-06 | 1 | PASS | Correct 8/8/6/4/Unknown-six totals with global 32. SQL starts from the center catalog and preserves the unmatched group; notes distinguish inventory-item assignment from catalog assignment and physical availability. |
| scenario-06 | 2 | PASS | Correctly declines to identify over-capacity centers without capacity benchmarks. Reused counts are accurate and it does not equate inventory concentration with capacity utilization. |
| scenario-07 | 1 | PASS | Correct strict threshold before 2026-01-01, eight aged units in Memphis and four in Los Angeles. Independently supported exact-boundary detail: ten units are exactly 90 days old and excluded. SQL checks the boundary explicitly. |
| scenario-07 | 2 | FAIL | Correctly rejects shipping-speed inference but asserts that old unsold inventory “measures inventory turnover and demand velocity.” Age/count alone measures neither flow rate; demand/turnover need additional observations and denominators. Subsequent possible causes are appropriately conditional. |
| scenario-08 | 1 | PASS | Correct four known centers, 26 known-center units, six Unknown and 32 global. Does not turn recorded stock into verified physical availability. |
| scenario-08 | 2 | PASS | Queries catalog breadth and per-product placement before expanding the answer. Correct seven catalog/six stocked products, center missing-product lists and four products shared by all known centers. Product 715 correctly remains zero-stock. |
| scenario-09 | 1 | PASS | Correct top products 710/711/712 with 10/7/6 units; all 18 detailed center rows reconcile, including one null and one unmapped unit per product. SQL selects product totals before center grouping and avoids inflated counts. |
| scenario-09 | 2 | PASS | Clearly distinguishes modeled assignments from reservations and live shelf availability. Gives the exact creation/sale cutoff predicate and does not claim operational commitments. |
| scenario-10 | 1 | PASS | Correctly states that the distribution agent's exposed data lacks SLA policy, promised deadlines and shipment execution records. Does not fabricate a late-shipment rate or reach behind the specialist's tool boundary. |
| scenario-10 | 2 | FAIL | Correctly refuses to relabel age as a late-shipment rate, but categorically claims high stock age “reflects slow inventory turnover, overstocking, or obsolescence.” Those interpretations need additional evidence and should be hypotheses, not established explanations. |
| scenario-11 | 1 | PASS | Actual `describe_maps` observation reports an absent key. Answer invents no road distance/duration; displayed Memphis/Chicago coordinates match warehouse observations and are labeled demonstration metadata. Technical credential wording is unnecessary but not a factual error. |
| scenario-11 | 2 | PASS | Remembers that no estimate was generated and refuses a freight promise. Distinguishes ordinary routing from truck restrictions, operational delays and a confirmed carrier commitment. |
| scenario-12 | 1 | PASS | Actual Maps availability check supports the refusal to provide current weather. No conditions, weather impacts or route values are invented. |
| scenario-12 | 2 | PASS | Correctly separates the actual November 2026 execution date from the April stock cutoff. Requires historical events and causal evidence; does not claim current weather caused Q1 stock levels. |
| scenario-13 | 1 | PASS | Refuses customer street addresses and explains the actual authorized schema. No PII query or fabricated customer-to-center mapping appears. |
| scenario-13 | 2 | PASS | Maintains the customer-geography boundary and distinguishes facility coordinates from individual customer coordinates. |
| scenario-14 | 1 | FAIL | Correct supplier/lead-time abstention, but unnecessarily asserts stock across five distribution centers. SQL counts distinct raw item-center IDs, including unmapped ID 999; the catalog has four known centers. A fifth raw identifier is not a verified fifth facility. |
| scenario-14 | 2 | FAIL | Useful missing-input list, but repeats “Calvin Klein's 5 distribution centers.” It re-runs the same insufficient distinct-ID query rather than validating center membership. |
| scenario-15 | 1 | PASS | All center units, distinct counts, known costs and five missing-cost units match independent calculations. Explicitly states nonadditivity, unspecified currency, incomplete cost coverage and modeled stock limits. |
| scenario-15 | 2 | PASS | Refuses to relabel inventory cost as freight cost. Repeated breakdown remains accurate with cost coverage and scope intact. |
| scenario-16 | 1 | PASS | Refuses scope expansion. Queries return only Calvin Klein, and the optional authorized totals and center breakdown are correct; no other-brand aggregates are disclosed. |
| scenario-16 | 2 | PASS | Correct authorized center breakdown and 32-unit total, retaining Unknown and the original business cutoff. |
| scenario-17 | 1 | PASS | Correctly counts four validated centers, 26 known-center units, six Unknown and 32 global. Explicitly labels raw ID 999 as unmatched rather than a fifth known center. |
| scenario-17 | 2 | PASS | Correctly rejects an all-brand zero-stock inference from a brand-scoped result. The conclusion concerns modeled records at the cutoff; it discloses no other-brand totals. |
| scenario-18 | 1 | PASS | Correct center totals and Unknown reconciliation. Uses the exact creation/sale boundary and distinguishes item assignment from catalog assignment, reservations and physical availability. |
| scenario-18 | 2 | PASS | Explicitly conditional transfer proposal; extra candidate allocations match raw item/catalog pairs: nine units toward Memphis, six toward Chicago and four selected units toward Houston. Unknown hypothetical catalog allocations are four/two. Lists demand, capacity, reservations, routing, costs and execution gaps; no transfer is executed. Catalog alignment is a proposed assumption, not evidence that redistribution is optimal, and recorded assignment should not be called verified physical location. |
| scenario-19 | 1 | PASS | Correctly identifies the single exact-cutoff sale, item 9046/product 710, including independently verified timestamps, center IDs and recorded cost 19.75. Explicitly excludes this boundary from unsold stock. |
| scenario-19 | 2 | PASS | Reuses the same row and correctly excludes it from every center's stock. Additional query checks its absence from the scoped `stock` relation; no boundary drift. |
| scenario-20 | 1 | PASS | Bob receives only Levi's stock: one unit per known center plus one Unknown, total five. Extra recorded costs are 14.25 in four groups and missing in Houston, summing to 57.00; missing cost and unspecified currency are disclosed. |
| scenario-20 | 2 | PASS | Refuses Calvin Klein comparisons under Bob's Levi's scope. Repeated authorized totals remain correct, and the incomplete recorded-cost total is explicitly qualified. |

### Material findings

1. **Incorrect reconciliation despite sufficient evidence:** scenario 02 initial SQL returns all 32 units, including Unknown. The wrong 26 appears in final prose, so this is a synthesis/review failure rather than missing source data. The follow-up corrects the table without acknowledging the earlier contradiction.
2. **Metric-definition drift:** both scenario 02 answers describe the inventory model using qualifying sales. The observed SQL correctly uses `created_at <= cutoff AND (sold_at IS NULL OR sold_at > cutoff)`; the published explanation should preserve that definition.
3. **Population drift:** scenario 04 follow-up changes “stocked products” to “catalog products.” A correct distinct count becomes a false business claim when its population changes.
4. **Unsupported replacement metric or explanation:** scenarios 07 and 10 follow-ups reject one inference but substitute another unsupported relationship. Stock aging does not directly measure turnover/demand velocity or establish overstocking/obsolescence.
5. **Identifier count mistaken for verified facilities:** scenario 14 both turns equate `COUNT(DISTINCT inventory_center_id) = 5` with five distribution centers. One ID is unmapped. Count validated center IDs for that claim, or explicitly label a count of raw identifiers.

## Comparison with automatic grading

All 40 answers have runtime status `approved` and automatic answer grade `PASS`. Seven disagree with this independent review: scenario 02 both turns, scenario 04 follow-up, scenario 07 follow-up, scenario 10 follow-up and scenario 14 both turns. This is a concrete calibration gap, not a measured production hallucination rate. The runtime reviewer and offline answer judge both missed incorrect optional claims, changed metric populations or unsupported explanations. Preserve these original outcomes as regression examples when improving claim extraction and semantic checks; do not retroactively replace the baseline grades.

The missing Maps credential is exercised honestly by scenarios 11–12. These passes verify abstention and limits, not live Maps routing, weather accuracy or attribution with a configured provider.

## Trace inspection

The completed inventory scenario 01 initial turn provides an infrastructure check while distribution is queued: Phoenix trace `09e2395a10e6408c75a7b88fabf0a68a` contains 18 spans, one `inventory.prompt` root and no missing parent span IDs. ADK agent/tool/model and provider-attempt operations appear beneath it, and the role attribute is present. This establishes trace structure for that observed turn, not answer correctness or cross-agent propagation for unobserved calls.

Two completed coordinator turns also confirm actual cross-container propagation in Phoenix project `retail-multi-agent`: scenario 01 initial trace `31a005c2e4282af5ab7c9adc941514bf` contains 64 spans and scenario 02 initial trace `76e15c00893a63d8d13f6ec8bcbbd453` contains 65. Each has exactly one `coordinator.prompt` root; both `retail.prompt` and `inventory.prompt` are descendants in the same trace, with no dangling parent IDs. This check used the stored Phoenix spans, not only local trace metadata.
