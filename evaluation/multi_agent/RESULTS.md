# Multi-agent evaluation results

> Access-mode update (2026-11-25): these recorded runs predate removal of demo users and brand permissions. Current suites use all-brand workspace access and have not yet been rerun live. Historical scores and findings below are unchanged; see the [current evaluation guide](../../docs/evaluation.md).

Status: the full baseline, two focused candidates and live BigQuery validation are complete. All three Phoenix datasets have 20 initial questions and 20 follow-ups, with independent references. Human reference review and human judge calibration remain pending.

## Smoke run — 24 November 2026

Run: `a2a-20261124T190417Z-a28a590e`. Six conversations, twelve actual A2A turns. Accounted run cost: **$2.994**. Every captured answer was inspected by the implementation assistant; this is not independent human review.

| Suite | Automatic answer results | Additional inspection |
|---|---|---|
| Inventory | 4 PASS | Counts, cost coverage, category ties and Other reconciliation agreed with independent source calculations. The initial answer included an unnecessary center breakdown. |
| Distribution | 4 PASS | Center totals reconciled, including null and unmapped center IDs. The answer correctly rejected dropping Unknown from the total. |
| Coordinator | 3 PASS, 1 FAIL | Initial scenario-01 exhausted the work deadline during review. Its follow-up was an automatic false positive: it claimed product 714 had six stocked units; the raw source contains three. It also overstated physical availability. Scenario-02 sales/stock and conditional coverage calculations were correct. |

The false positive demonstrates why evidence-grounding alone is insufficient: a model can accurately repeat an incorrectly aggregated tool result. The coordinator combined overlapping stock aggregates, and the original judge accepted the resulting extra claim because it matched that derived evidence.

Changes before the full candidate run:

- Additional optional claims are checked against independently computed product, category and center stock/cost facts and qualifying 30-day purchases. These background facts are grader-only and are not required answer content.
- A separate criterion rejects treating modeled stock as confirmed physical or available-to-promise inventory.
- The universal test suffix requesting item-center attribution was removed from unrelated questions; actual center questions retain explicit attribution requirements.
- Coordinator guidance and provider review-time handling are corrected separately in the runtime. Full candidate validation must use the rebuilt images.

All six original trajectory grades remain `ERROR`: the new trajectory schema omitted a field expected by the existing trace renderer. The adapter now includes `coverage_complete`, with a regression test. A separate real judge check over the captured inventory scenario-01 completed successfully: `trajectory-adapter-check-20261124T190750Z`, **$0.077476**. Original smoke outputs and grades were not overwritten.

## Independent grader controls

The observed coordinator false positive is retained as a negative control. A separate synthetic valid answer omits optional product numbers and clearly distinguishes modeled stock from physical availability. Live control run `optional-claim-controls-20261124T191444Z` rejected the observed answer (`FAIL`, optional numerical claim contradicts independent truth) and accepted the synthetic valid answer (`PASS`). Cost: **$0.107502**. The source answer, new reference, visible judge exchanges and results are stored separately from the original smoke run. These controls do not constitute human calibration.

## Full baseline

Run: `a2a-20261124T191812Z-f59d6715`, 24 November 2026. **60 conversations / 120 turns executed**, all 60 conversation results published to Phoenix. Accounted cost **$21.279905**; duration **1,631.6 seconds**. Immutable deployment image IDs, source hashes, raw rows and original grades are retained in the run directory. The model and skill sources were frozen for this run.

| Suite | Automatic answer grades | Assistant manual inspection |
|---|---|---|
| Inventory | 39 PASS, 1 FAIL | 33 PASS, 7 FAIL |
| Distribution | 40 PASS | 33 PASS, 7 FAIL |
| Coordinator | 36 PASS, 3 FAIL, 1 ERROR | 30 PASS, 9 FAIL, 1 ERROR |
| Total | **115 PASS, 4 FAIL, 1 ERROR** | **96 PASS, 23 FAIL, 1 ERROR** |

Every answer was inspected against its request, prior turn and independent raw-row calculations. These are assistant-authored judgments, **not independent human validation**. Detailed findings: [inventory](INVENTORY_REVIEW.md), [distribution](DISTRIBUTION_REVIEW.md), [coordinator](COORDINATOR_REVIEW.md).

The automatic supported-claim metric reported **654/654** while manual inspection found 22 semantic failures that the automatic answer grade missed. This is a judge coverage/calibration limitation, not evidence of zero hallucinations. Typical missed assertions equated modeled stock with physical availability, inferred complete history from an empty snapshot, treated missing cost as guaranteed undervaluation, or inferred turnover from age. All 60 trajectory judges returned PASS; that process score does not validate every answer assertion.

Three automatic failures were reference/extraction defects: inventory scenario-15/turn-2 required an unrequested product count; coordinator scenario-03/turn-1 and scenario-05/turn-1 correctly printed disjoint null/unmatched-center groups instead of a combined Unknown total. One failure was a real numerical defect: coordinator scenario-08/turn-1 included exactly-90-day units in a strict older-than-90-day request (22 units/461.50 instead of 12/253.00). Coordinator scenario-11/turn-1 failed before publication because a shared personal-geography check incorrectly rejected public facility coordinates. Original results are preserved, including the numeric metric **188/195**.

## Candidate validation

Run: `a2a-20261124T195511Z-d0f6edc6`. **21 selected conversations / 42 turns completed**, cost **$7.173089**, duration **680.8 seconds**. This reruns every manually failed scenario and the facility-coordinate error, including both turns. It is a targeted development comparison, not a replacement for the full baseline or a sealed holdout.

| Suite | Automatic answer grades | Assistant manual inspection |
|---|---|---|
| Inventory | 13 PASS, 1 ERROR | 11 PASS, 3 FAIL |
| Distribution | 10 PASS | 8 PASS, 2 FAIL |
| Coordinator | 17 PASS, 1 FAIL | 13 PASS, 5 FAIL |
| Total | **40 PASS, 1 FAIL, 1 ERROR** | **32 PASS, 10 FAIL** |

All 21 process evaluations passed. Manual details: [inventory](CANDIDATE_INVENTORY_REVIEW.md), [distribution](CANDIDATE_DISTRIBUTION_REVIEW.md), [coordinator](CANDIDATE_COORDINATOR_REVIEW.md). The strict older-than-90-day calculation and public-coordinate publication are fixed for this fixture. Remaining assertions concern history, event meanings, recorded IDs versus recognized facilities, physical availability and data/tool capabilities. Coordinator scenario-10/turn-1 regressed by counting only null center IDs and omitting unmatched IDs; the numerical oracle correctly rejected 3 units/63.75 instead of 6 units/127.50. Automatic supported claims remained 200/200 despite these manual findings.

Inventory scenario-12/turn-1 was a correct refusal whose automatic grade errored because the judge cited tool names as evidence identifiers. The adapter now assigns stable per-observation O IDs to schema/skill outputs and constrains the judge's source enum to observed IDs. A separate live regrade of the unchanged answer passed: `observation-source-control-20261124T200924Z`, **$0.026778**. Its original ERROR remains unchanged. This is an evaluator attribution fix, not an agent response improvement.

Candidate runtime changes address field semantics, strict age boundaries, measured versus inferred claims, reviewer fallibility and provenance-backed facility coordinates. Evaluator changes are recorded separately: requested-only metric bindings, independently verified equivalent disjoint partitions, atomic semantic criteria, and answer-context filtering. The answer judge sees the published answer and actual evidence; superseded drafts, finish arguments and reviewer verdicts remain available only to the separate process evaluation. Original full observations remain in artifacts.

Separate live judge checks over the unchanged baseline answers accepted coordinator scenario-03/turn-1, coordinator scenario-05/turn-1 and inventory scenario-15/turn-2 after their reference/extraction corrections: **3/3 PASS**, cost **$0.184692**, artifact `partition-controls-20261124T195607Z`. These are evaluator checks on saved answers, not new agent executions; their original baseline FAIL grades remain intact.

Eight paired judge development controls compare observed defective answers with minimally corrected versions. With identical v3 criteria and the corrected answer-only context, `calibration-candidate-20261124T195511Z-9bee4402` classified **16/16 as expected** (eight bad answers rejected, eight repairs accepted; **$0.652934**). The prior full control run with unfiltered context classified 14/16; one repair was wrongly rejected using a superseded draft. Both attempts are retained. These controls were derived from observed development defects, not a sealed or human-calibrated test set. Passing them does not establish general judge reliability.

Because both runtime and evaluation contracts changed, raw automatic pass rates across these runs are not directly comparable as a model-only improvement. Manual inspection and separate judge controls provide the comparison. The candidate deployment and grader hashes are saved before execution.

## Final targeted validation

Run: `a2a-20261124T201011Z-0d2b1640`, **nine conversations / eighteen turns completed**, cost **$3.109743**, duration **335.7 seconds**. It covers Inventory05/09/12, Distribution14 and Coordinator01/04/08/10/19 after a second runtime revision. The v3 semantic criteria remain unchanged; the observed-source attribution correction is included. All prior attempts remain available.

Automatic answers: **18 PASS**. Manual inspection: **16 PASS, 2 FAIL**; remaining unsupported assertions are Distribution14/2 describing the full service as tracking only unsold units, and Coordinator19/2 inventing an available facility operating-status field and confusing product versus inventory-unit creation timestamps. Details: [domain inspection](FINAL_DOMAIN_REVIEW.md), [coordinator inspection](FINAL_COORDINATOR_REVIEW.md). No execution error occurred.

Process evaluations: **8 PASS, 1 ERROR**. Inventory scenario-12's process judge invented an event identifier, correctly triggering validation and command exit 2 despite passing answers. Its response schema now restricts event references to actual observed IDs. A separate live regrade of the same observations passed: `trajectory-source-control-20261124T201758Z`, **$0.050880**. Original grades remain unchanged.

Before live warehouse validation, an additional raw-row boundary test exposed an oracle precision issue hidden by midnight-only fixture timestamps: “older than 90 complete days” must use whole elapsed days greater than 90, not merely elapsed time greater than 90 days. The independent oracle now excludes 90.5-day records and includes 91-day records. Existing fixture values remain 12 units/253.00. Runtime guidance and live aging checks must use the same explicitly requested definition.

## Live BigQuery validation

Run: `a2a-20261124T202152Z-276d3486`, **six conversations / twelve turns completed**, cost **$1.9810634**, duration **219.2 seconds**. The source snapshot is `2026-11-24T20:21:39.856527+00:00`, separate from the April 1 business cutoff. It contains 756 products, 12,766 inventory rows, 10 centers, 4,739 order items and 4,677 orders across the evaluation identities' scoped brands. All complete dataset references were published; no source rows or expected values were silently truncated.

| Suite | Automatic answer grades | Assistant manual inspection |
|---|---|---|
| Inventory | 2 PASS | 2 PASS |
| Distribution | 4 PASS | 4 PASS |
| Coordinator | 6 PASS | 3 PASS, 3 FAIL |
| Total | **12 PASS** | **9 PASS, 3 FAIL** |

All six observable-process evaluations passed. All requested numbers and checked additional numbers are correct, including **4,929 modeled units**, **47 qualifying 30-day purchases**, and **4,635 units older than 90 complete days costing 136,081.04**. The live source has five units between 90 and 91 elapsed days; the corrected complete-day calculation excludes them. The full inventory relation versus filtered-stock distinction and unavailable operating-status field are now described correctly in the targeted domain answers.

Three coordinator follow-ups still add unsupported semantic claims: an imprecise stock-boundary restatement, categorical denial of possible historical-weather effects, and advertising verified on-hand analyses from modeled records. Detailed evidence: [live domain review](LIVE_DOMAIN_REVIEW.md), [live coordinator review](LIVE_COORDINATOR_REVIEW.md). These remain failures in the assistant inspection despite automatic PASS. No further prompt tuning was performed after this run, and the latest version has not undergone a new full 60-conversation run or sealed holdout evaluation.

## Phoenix inspection labels and verification

Separate `Initial / Assistant inspection` and `Follow-up / Assistant inspection` evaluations expose the manual findings in the GUI. They are explicitly marked as **LLM/implementation-assistant origin, not human review**, with the report path/hash and exact answer-artifact hash. The importer verifies each reviewed answer equals its immutable Phoenix experiment output before publishing.

**192 annotations were published and read back successfully** across the full baseline and three subsequent runs: 153 PASS, 38 FAIL, 1 ERROR. Automatic evaluation digests remained unchanged. The smoke run retains its original automatic results and narrative review; it is not included in this 192-row import. Publication audit: `.artifacts/multi-agent/assistant-inspections-20261124T203041Z.json`.

Across the smoke, full baseline, two focused candidates and live validation, **102 conversations / 204 user turns** were executed. These use different runtime/evaluator versions and deliberately repeated development cases; do not aggregate them into a general accuracy score. The final complete offline suite reports **486 passed**, with five external-service pytest checks deselected; separate Docker/A2A/BigQuery/Phoenix checks are documented above. The focused evaluation contract checks also passed (51 tests, included within the broader suite). Ruff is clean and targeted Pyright reports zero errors. Independent judge controls and saved-answer regrades are reported separately above.
