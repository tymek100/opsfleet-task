# Targeted comparison, library, messaging and transport fixes

Date: 2026-10-25. This record supplements the [fresh 20-case audit](fresh-holdout-v3-2026-10-25.md).

## General implementation changes

- Comparison arithmetic, completeness validation, narrative rendering and detailed arithmetic use the explicit primary/baseline roles. Chronological order and adjacency no longer determine the denominator or eligibility. Matching scope, filters and definitions remain mandatory.
- Empty sales aggregates with zero units, orders and customers have zero derived revenue even when raw SQL SUM is NULL. Missing revenue on a nonempty population stays unknown. Percentage change against zero is undefined; absolute change remains available. Raw evidence is not rewritten.
- Typed plans can execute an ordered list of up to four library operations. Cancellation uses the actual owner/conversation-scoped pending table. Known reads and save availability are checked before mutations. The list is sequential, not transactional; a later controlled failure reports earlier completed steps.
- A nonmutating help route explains saving, reading, deletion and analysis. The model chooses the topic semantically; code owns accurate descriptions of actual application behavior. Unsupported measures no longer receive unrelated profitability boilerplate.
- HTTP transport timeouts/network errors receive at most one retry, sharing the original call/cost/deadline budget. Partial emitted responses are not replayed. SDK retries remain disabled beyond one attempt. Exhausted failures get a timeout/connection-specific message. No production availability guarantee is implied.

No natural-language regexes, question-specific exceptions, higher reasoning setting, extra reviewer model or new dependencies were added. Mathematical rules, operation schemas and authoritative product descriptions are application contracts, not keyword matching.

## Method and retained attempts

Ten new prompts and acceptance expectations were fixed in `cases.py` before the first live request. Live requests use Gemini and BigQuery; report operations use an isolated SQLite library seeded with a recorded report solely for mutation checks. No hard deletion is performed. A pending preview is seeded for the cancellation test. The real report library is untouched.

The first attempt is preserved at `.retail-agent/targeted-v4-attempt1/`. Case 3 exposed SQL NULL on empty sales: the percentage was correctly undefined, but the absolute difference was missing. This was a failed acceptance case, despite the application's `validated` status. A distinguishing offline regression was added, the empty-population semantics were fixed, and the full ten-case suite was rerun. Save-help wording was also made explicit about owner-only access. Two initial harness setup errors occurred before any provider call (a required trace ID and a non-analytical seed rejected by the store); neither is counted as a live question attempt.

First successful replay artifacts are in `.retail-agent/targeted-v4-final/`. The final post-capability-refinement replay is in `.retail-agent/targeted-v4-complete/`. Original failing prompts are separately replayed in `.retail-agent/targeted-v4-original-regressions/`. Raw answers, rendered output at widths 80 and 120, provider events, runtime fingerprints and state snapshots are retained. Once replayed, these prompts are regressions rather than held-out evidence.

Independent handwritten SQL checks raw evidence without calling the application compiler. Additional acceptance checks calculate differences and percentages directly from returned totals, inspect expected period roles and assert actual database state. Human review checks relevance, completeness and readability. Successful application quality flags alone are not treated as proof.

## Offline verification

167 tests passed; 17 opt-in live tests from the existing suite were deselected. Ruff, strict Pyright and package build passed. New coverage includes reversed/disjoint periods, empty and genuinely unknown revenue, owner/conversation-scoped cancellation, invalid-read preflight, nonmutating help, and bounded timeout recovery/exhaustion. A presentation fixture was corrected to declare Q4 as the baseline it already expected in its assertions. The former empty-aggregate NULL assertion was replaced with separate empty-population and missing-price tests.

The timeout tests inject HTTP read timeouts and verify recovery after one retry or a specific failure after two attempts; they are not live provider outages. Remaining mixed analysis-plus-library requests must be split into separate turns. Plans can still be schema-valid but semantically wrong; this small suite is not a proof of universal correctness.

## Ten new questions: first successful replay

**10/10 passed after one implementation correction; 46 acceptance assertions passed.** All ten raw evidence sets matched independent SQL. The first live series was 9/10 acceptable, with the empty-baseline absolute-change defect retained. No individual failed question was silently retried until a lucky answer appeared.

Runtime for this replay: `b981b7077fbc2bd7`; prompt: `e562bd4cbe2866d8`; intent contract: `direct-plan-v4`. Model: `gemini-3.8-flash`, thinking: `medium`, 120-second turn deadline, unchanged $1 admission cap. These are the same settings as the preceding audit.

| # | Question (verbatim) | Result | Seconds |
|---|---|---|---:|
| 1 | Use Q3 2025 as the reference. Express Q2 2025 revenue relative to that reference, including the absolute difference and the percentage with Q3 in the denominator. | Pass | 16.76 |
| 2 | Compare April 2026 revenue against January 2026 revenue. Show the dollar change and growth percentage; do not include February or March. | Pass | 15.83 |
| 3 | Compare January 2026 revenue with January 1900. Show both totals, the absolute change, and the percentage change if it is mathematically defined. | Pass | 64.35 |
| 4 | Prepare a Q2 2025 report against Q2 2024: revenue totals, monthly revenue and the top two products for Q2 2025, plus proposed actions for Q3 2025. Leave it unsaved. | Pass | 33.90 |
| 5 | Withdraw the deletion I was about to confirm. After that, list my saved reports so I can check they are still there. | Pass | 8.71 |
| 6 | First preview removal of reports whose title contains Keep me, then cancel that preview, and finally list my reports. Do not delete anything. | Pass | 13.11 |
| 7 | Suppose next time I ask you to archive this report under a title: would it store the current draft, and who would be able to read it? I am only asking about the behavior. | Pass | 10.94 |
| 8 | How do I stop a proposed deletion, and does asking for a deletion preview already erase the report? Explain only; do not run anything. | Pass | 13.40 |
| 9 | For August 2025, calculate the 90th percentile of order value. Do not replace it with average order value. | Pass | 26.93 |
| 10 | I need one revenue row for each month from February 2021 through April 2025 inclusive. Keep all 51 months; do not group by year. | Pass | 25.60 |

Numerical findings independently checked:

- Q2 2025 relative to Q3 2025: 7,536.22 vs 9,575.34, difference −2,039.12, **−21.30%** using Q3 as denominator.
- April 2026 relative to January 2026: 4,790.12 vs 3,223.40, difference +1,566.72, **+48.60%**. No intervening-month query.
- January 2026 relative to the empty January 1900 query: 3,223.40 vs zero qualifying sales, difference **+3,223.40**, percentage undefined. This says nothing about historical business activity outside the dataset.
- Q2 2025 relative to Q2 2024: 3,241.78 vs 2,098.56, difference +1,143.22, **+54.48%**; three monthly rows, exactly two products, and proposed Q3 2025 actions. Not saved.
- Cancellation removed the actual pending confirmation (1→0), preserved the report, and listed its ID. Preview→cancel→list ended with no pending confirmation or exposed active preview. Help questions did not mutate state.
- Percentile was explicitly unavailable with no average substitution or profitability boilerplate. The 51-month request received the actual 50-row bound with no query/truncation.

The rendered 80- and 120-column outputs were inspected: comparison values and headings remain readable; long dates wrap at 80 columns without dropping numeric cells. Report proposals are labelled as unverified targets rather than forecasts.

Total final duration: **229.53 seconds**, median **16.30 seconds**; report **33.90 seconds**. One provider 504 was recovered by the bounded retry (case 3, 64.35 seconds). No final question failed, and no semantic planning repair was needed in the final series. Recorded usage: 29,235 input tokens, 13,796 output-plus-thinking tokens. At the previously documented paid-rate assumption ($0.75/M input and $3.75/M output including thinking), that is **$0.07366** for all ten questions. The first series was **$0.09120**. These estimates exclude BigQuery and any unreported failed-call usage, are not invoices, and do not establish actual free-tier billing.

## Original failures and final transport-message follow-up

The separate six-question original regression batch completed **5/6**: reverse comparison, median refusal, year-over-year report, hypothetical save help and actual cancel-and-list passed. All six raw evidence sets matched independent SQL. The exact 60-month question failed before any query after an initial 504 and a subsequent server error, taking 95.74 seconds. This failure is retained, not reclassified as a success.

That run exposed one remaining failure-message path: exhausted API server errors still fell through to the generic credentials/quota message. The wrapper now distinguishes 504 timeouts and other transient server statuses (500/502/503), preserving the same single retry and original budget. Added fault injection covers exhausted 504 as well as 503, HTTP read timeout, recovery, and permanent 403 without retry. The final offline suite has 167 passing tests; lint, types and build pass.

Current source after this narrowly scoped error-message correction is `9d704283b20485e9`. The successful ten-case replay above used `b981b7077fbc2bd7`; arithmetic, planning, library behavior and successful response paths are unchanged by the final correction. The ten semantic cases were not rerun a third time solely for that failure-message patch. The previously failed original question is retried separately in `.retail-agent/targeted-v4-timeout-replay/` with the same question and `medium` setting.

| Original question | Batch outcome | Seconds |
|---|---|---:|
| February relative to March 2026 | Pass: +79.38, +2.30% | 15.83 |
| June 2025 median order value | Pass: specific unsupported metric, no substitute | 5.73 |
| Every month January 2021–December 2025 | Provider failure after bounded retry; no query | 95.74 |
| Q1 2025 vs Q1 2024 report, top three, Q2 actions | Pass: +1,613.52, +89.30%, complete report | 29.12 |
| Hypothetical save under Archive review | Pass: explanation, no save | 9.27 |
| Cancel pending deletion and list reports | Pass: pending 1→0, report retained and listed | 15.77 |

## Monthly cardinality contract refinement

The isolated replay after the server-message correction also failed: the initial plan violated the executable contract; a repaired response, after a recovered 504, violated the output schema. Duration was 105.01 seconds. It is retained at `.retail-agent/targeted-v4-timeout-replay/`. This was not counted as a pass or attributed solely to provider availability.

The capability manifest now explicitly explains the general cardinality rule: one output row per intersected calendar month, bounded by `query_schema.properties.limit.maximum`. The capability issue schema describes using the exact bounded property for out-of-range refusals instead of an invented field name. These are shared execution semantics and schema instructions, not date-specific or phrase-specific exceptions. Sanitized validation reasons are now logged for future diagnosis; hidden reasoning is not logged.

After that refinement, the **same original 60-month question passed in 7.49 seconds on one planning call**, explicitly reporting requested limit 60 versus maximum 50 and performing no query. This is a successful regression after retained failed attempts, not evidence that provider timeouts are eliminated. Its artifact is `.retail-agent/targeted-v4-limit-contract/`.

Current source is `6105cd2920f1c9fc`. Because this refinement changes planner context, the complete ten-case suite is replayed again on this source, rather than assuming the previous successful run establishes semantic behavior after the change. The offline suite still has 167 passes, with lint, strict types and build passing.

## Final acceptance on the completed implementation

**10/10 targeted questions passed again on source `6105cd2920f1c9fc`, prompt `80990c71abd431cd`. All 50 acceptance assertions and all 10 independent SQL evidence comparisons passed.** There were no provider retries, semantic repairs, fallback reports or failed questions in this final batch. Thinking remained `medium`.

| Case | Result | Seconds |
|---|---|---:|
| reverse_quarters | Pass | 13.72 |
| gap_months | Pass | 16.12 |
| zero_baseline | Pass | 14.57 |
| annual_report | Pass | 33.81 |
| cancel_list | Pass | 7.06 |
| preview_cancel_list | Pass | 15.29 |
| save_help | Pass | 11.22 |
| delete_help | Pass | 13.10 |
| percentile | Pass | 29.54 |
| long_months | Pass | 8.12 |

Total: **162.55 seconds**; median: approximately **14.15 seconds**. Recorded usage: 30,021 input, 2,590 output and 10,003 thinking tokens; paid-rate estimate **$0.06974** for this batch under the same assumptions above. The exact 51-month refusal took 8.12 seconds with one planning call, compared with 68.80 seconds and one schema repair in the initial series.

Final rendered report/comparison/empty-baseline outputs were inspected at 80 and 120 columns. All numerical findings above remained identical. Report actions are correctly dated and labelled as proposals. Actual pending state and retained report IDs were verified again. The five original semantic/state regressions passed in their separate batch; the sixth original question passed after the capability refinement, with all unsuccessful attempts retained. No claim is made that all six passed in their initial batch or that future provider outages cannot occur.

Across all six retained batches: **38 question attempts**, recorded paid-rate token estimate **$0.31249**. This includes the failed and superseded runs; it still excludes unreported failed-call usage and BigQuery, and is not an actual billing statement.
