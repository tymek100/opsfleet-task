# Ten-question evaluation: Gemini 3.8 Flash medium

Date: 2026-10-25. This is an evaluation of live answers, not a claim that all ten answers passed end-to-end quality requirements. Application code and prompts were held unchanged throughout this run. No production logic was modified as part of this evaluation.

## Main findings

- All nine analytical responses returned application status `validated`; the unauthorized-brand request returned no data. Independent BigQuery queries matched all 179 checked base-metric/NULL cells and churn delta, as well as returned group identifiers, ranking order and row counts. This does **not** mean all user questions were fully answered.
- The dual-ranking question omitted the customer ranking from the visible answer even though the model queried it. This is a genuine intent/presentation bug and a false-positive completeness validation.
- Six analytical answers included model commentary. Three drafts were rejected as unsupported. Accepted commentary was sometimes useful, but it also showed vague business language, insufficient scope qualification and an irrelevant product-mix hypothesis.
- Empty results, churn and permission refusal are numerically/safely handled but poorly explained to a non-technical user.
- All ten turns completed without a terminal provider failure. The report recovered from one 504 retry and completed in 112.88 seconds. This small run does not establish production reliability.

## Setup and method

`gemini-3.8-flash`, thinking `medium`, commentary enabled, 8,192 output-token cap, eight model-attempt cap, USD 1 conservative reservation cap, 120-second turn deadline, 13-second model pacing and 100 MB maximum billed bytes per query. Identity: Alice, Calvin Klein only. Cases 1–9 start fresh conversations. Case 10 resumes case 2, explicitly testing January–June context retention. No saved reports were created.

Both the actual business answers and the Rich CLI rendering at width 100 were reviewed. [Full questions and displayed answers](medium-ten-transcripts-2026-10-25.md) are preserved. Model grades were not used as the sole oracle: all quantitative evidence was checked against separately written SQL using an `EXISTS` order-membership condition rather than the application compiler. Churn was recomputed using two independently aggregated eligibility/inactivity snapshots. State queries return aggregates only. No raw customer contact details were retrieved.

Independent checks validate the effective request as well as the original question manually: date windows, status overrides, selected products, required rankings, retained follow-up period and brand scope. Matching the model-selected SQL alone would miss the omitted ranking in case 1.

## Results

| # | Scenario | Time | Commentary | Recorded list-price cost, USD | Answer review |
| --- | --- | ---: | --- | ---: | --- |
| 1 | Two product rankings | 45.14 s | Rejected | 0.031977 | Incomplete: second requested ranking hidden |
| 2 | Monthly revenue | 72.50 s | Accepted | 0.023973 | Useful; somewhat corporate wording |
| 3 | Product comparison | 44.44 s | Accepted | 0.017353 | Correct table; poorly targeted hypothesis |
| 4 | Revenue by state | 48.23 s | Accepted | 0.025092 | Correct aggregates; prose scope and wording need work |
| 5 | September inactivity / churn | 52.74 s | Rejected | 0.022277 | Correct values; does not clearly answer the spike/why premise |
| 6 | Quarterly report + actions | 112.88 s | Accepted | 0.043626 * | Complete report; action formatting is verbose |
| 7 | Completed-only revenue | 48.71 s | Accepted | 0.016703 | Correct status override; unnecessary and broad commentary |
| 8 | Empty historical period | 45.56 s | Rejected | 0.014010 | No fabrication; unhelpful undefined/denominator wording |
| 9 | Unauthorized brand | 28.93 s | Not applicable | 0.011794 | Access blocked; misleading off-topic refusal |
| 10 | Follow-up customer ranking | 45.53 s | Accepted | 0.022097 | Correct retained period and ranking; wordy prose |

Median latency: 46.89 s; mean: 54.47 s; total: 544.66 s. Recorded question costs sum to **$0.228902**, approximately $0.0229 per question. The 11 independent oracle jobs add approximately **$0.002027** before the BigQuery free allowance.

* The report case retried a provider 504 without usage for that failed attempt; its cost and the total are incomplete observed estimates, not the exact bill. No total-spend claim is made for missing usage. Costs use the previously verified October 2026 [Gemini standard pricing](https://ai.google.dev/gemini-api/docs/pricing): $0.75/M input and $3.75/M output including thinking, with the applicable cache discount. [BigQuery list pricing](https://cloud.google.com/bigquery/pricing) uses $6.25/TiB billed; free tiers, credits and invoice adjustments are not applied. Budget reservations are different, conservative values.

The 13-second pacing setting matters: four calls have at least three inter-call intervals, so a four-call answer cannot meet a 30-second target under this configuration even before the final response finishes. Medium thinking alone cannot solve that latency floor. Do not remove pacing without checking actual provider quota.

## Issues to address before a strong demo

### 1. Missing requested ranking — high priority

Case 1 asked for revenue and distinct-customer rankings. Both queries returned five rows, but `intent.py` recognizes “number of customers” and not “number of distinct customers”. The resulting contract contains only the revenue ranking, and `quality.py` hides the other table. `validated` therefore means the incomplete contract passed, not that the original request was fully satisfied. Add phrase variants and an end-to-end regression asserting that both visible rankings survive.

### 2. Churn needs a clear explanation, not raw fractions

Case 5 independently confirmed eligible customers 1,778 → 1,861 and inactive customers 1,776 → 1,859. The number of eligible active customers stayed at two. Shares were 99.887514% → 99.892531%, an increase of about 0.005 percentage points. The UI instead printed `0.9989` twice and then `+0.005` percentage points, with repetitive technical contexts. It did not clearly distinguish this tiny arithmetic shift from a claimed spike, nor explain the numerator/denominator change. Show a compact percentage/count table and a factual premise check before any hypotheses. Include these counts in the required narrative contract.

### 3. Model review does not eliminate weak or overbroad prose

Case 3 compared two individual product IDs in one quarter. Revenue, units and customers were correct (294 / 3 / 3 versus 260 / 2 / 2; revenue per unit 98 versus 130). The product-mix template and commentary nevertheless referred to variation across periods. It was labelled as an unverified hypothesis, but was poorly suited to the question. Hypothesis templates need compatibility checks for the analytical grain and time comparison.

Case 4 said “Overall proceeds were concentrated in the top territory”. The displayed privacy-eligible states summed to 5,588.90, while all authorized Q2 revenue was 15,273.95. The claim should explicitly refer to the shown eligible regions, not overall revenue. Case 7 also described no repeat purchases without explicitly qualifying that only completed, authorized purchases were counted. These are scope/interpretation concerns despite correct base numbers and accepted model reviews.

### 4. Simpler language and safe entity references

The writer instruction forbids names, dates and identifiers generally, which also discourages useful, permitted business labels. Accepted prose then uses “top territory”, “secondary item”, “overall proceeds”, “intake”, “order yields” and “solitary transactions”. Allow application-bound references to safe product/region/period labels while keeping personal names and contact details excluded. Prefer ordinary terms such as revenue, orders and average order value. Simple one-number questions may be better served without two extra commentary calls.

### 5. Empty-data and permission messages need dedicated wording

Case 8 had no qualifying sales in January 2000: SUM returned NULL and counts were zero. The reply “undefined (no eligible denominator/data)” is inappropriate for an executive asking about revenue. Explain that no qualifying sales were found for the selected brand and period.

Case 9 correctly rejected the unauthorized brand before executing BigQuery. The visible reply was “I can help with retail data analysis and your saved reports only.” This is a valid retail question with insufficient permissions, not an off-topic question. Give a deterministic permission explanation and the authorized brand scope.

### 6. Report layout and latency

Case 6 correctly returned Q2 revenue 15,273.95, monthly values, top products and explicitly proposed Q3 actions. The action text still repeats scope, ISO boundaries and “end exclusive”; units/order is displayed at four decimals. The natural commentary was more readable but should describe basket size as an average. Preserve technical definitions in `/details`, simplify action baselines and then measure again.

## Verification record

All groups, ordering and row counts matched. Numeric/NULL check totals below exclude identifiers and include the independently calculated churn percentage-point change. Oracle jobs were dry-run first, capped at 100 MB and executed with query-result cache disabled; duplicate effective requests reused the local oracle result. No evidence was silently broadened to another brand or time period.

| Case | Checked cells | Independent BigQuery job IDs |
| --- | ---: | --- |
| 1 | 40 | `a658396e-1039-4d3c-bd92-d8466f4ae1c4`, `17779cd6-997e-4b84-acfe-335fff284758` |
| 2 | 24 | `a0da33d9-2a70-4055-b0a7-42066a43cdce` |
| 3 | 8 | `a7a6e76e-70eb-4210-a515-388f91302d92` |
| 4 | 36 | `09199453-594c-4304-9114-ea0a554b8f8e` |
| 5 | 7 | `8fd621e5-e99f-4bce-92eb-07e395d2985e` |
| 6 | 36 | `5c998511-878f-472d-833a-2540ea83c5f5`, `3c6b3667-2e12-4861-bd8c-eed63c96f44e`, `a658396e-1039-4d3c-bd92-d8466f4ae1c4` |
| 7 | 4 | `98098611-e69f-4d48-ad1e-0c55e0dee3b0` |
| 8 | 4 | `574e9f7c-69f7-465e-aba6-7879d6fe25b6` |
| 9 | 0 | None: authorization rejection |
| 10 | 20 | `1f2135f1-15f0-434d-9a2b-dda79573fa5e` |

Application source fingerprint: `815a222f5382af39`; prompt fingerprint: `3648299c6272c2e3`. Local artifacts, raw evidence, usage events and oracle SQL are under the ignored `.retail-agent/medium-ten/` directory. The report and transcript contain no credentials or hidden reasoning. Existing offline tests were not rerun in this evaluation-only task; this report covers these ten live turns and independent source checks.

Conclusion: the numerical pipeline and tested brand boundary performed correctly, and the report completed on medium. The assistant is not yet consistently executive-friendly or complete across the tested phrasing. Fix the omitted ranking, churn/empty/refusal messages and scope-sensitive commentary before treating this as a polished interview demo.
