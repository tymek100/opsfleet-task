# Gemini 3.8 Flash vs Gemini 4 Neon: report and summary comparison

Date: 26 November 2026. Code: `9371e0d`. Status: completed with live Gemini calls and BigQuery queries.

## Finding

**Changing to Neon did not solve the writing problem in this test.** Its summary preserved important analytical limitations, but was longer and harder to read: **103 words versus Flash's 67**, both squeezed into two sentences. Flash was cheaper and faster, but omitted the report's explicit warning that historical sales do not measure current demand.

For the successful report-plus-summary sequence, Flash cost approximately **$0.3524**, and Neon **$1.0940**—**3.10× more**. These are usage-based estimates, including specialist agents, reviewers, thinking tokens and BigQuery queries; they are not billing invoices.

The initial Neon attempt failed to produce a substantive report because of repeated reviewer-validation failures. Both configurations were then tested with a larger reviewer output allowance. All attempts are retained in the [complete transcripts](2026-11-26-flash-neon-summary-comparison-outputs.md); the [supporting JSON](2026-11-26-flash-neon-summary-comparison-data.json) contains token usage, costs, reference data and verification results.

## Exact prompts

Report:

> Compare our Q1 2026 sales with current inventory. Which categories deserve a closer look?

Follow-up, in the same conversation:

> summarize this report in 2 sentences

Each model summarized its own generated report. This evaluates the actual two-turn application experience, rather than isolated summarization of an identical document.

## Configuration and data

| Setting | Configuration |
| --- | --- |
| Models | `gemini-3.8-flash`, `gemini-4-neon` |
| Analyst thinking | `medium` for coordinator and all specialists |
| Reviewer thinking | `medium`, using the same model as the analyst |
| Analyst/reviewer temperature | Values sent during this experiment: `0.2` / `0`; ignored by these models |
| Analyst output allowance | 4,096 tokens per call |
| Reviewer output allowance | Initially 2,048; comparison rerun 4,096 for both models |
| Application path | Real ADK loops, completion reviewers and A2A delegation |
| Source | `bigquery-public-data.thelook_ecommerce`, all brands |
| Business cutoff | `2026-11-26T07:20:33.354469Z` |
| Physical warehouse snapshot | `2026-11-26T07:19:33.354469Z` |
| Deadline | 300 seconds per coordinator prompt; existing child limits retained |

The experiment used isolated local services and separate conversation stores. Repository prompts and skills were unchanged. Both rounds used the same frozen data, including follow-ups; figures differ from the earlier screenshot because that answer used an older version of the public dataset.

Subsequent documentation check: Google states that `temperature`, `top_p` and `top_k` are deprecated and ignored for Gemini 3.8 and newer models. The temperature values above record the submitted configuration, not effective sampling controls. These settings were removed from active application and evaluation code after the experiment; historical results remain unchanged. [Google's Gemini 3.8 migration guide](https://aistudio.google.com/docs/whats-new-gemini-3.8#migrate-to-gemini-3-8-flash).

An independent aggregate query verified **9,777 Q1 qualifying sales units**, **585,692.93 revenue**, **310,553 modeled unsold units**, and **8,908,773.88 recorded inventory cost**. The rerun's nine selected category rows passed **45 numerical comparisons** against that reference: sales units, revenue, stock units, recorded cost and stock-to-sales ratio. Summary figures were also checked against the reference. This does not validate physical inventory availability or current demand.

## Successful comparison: cost and latency

| Model | Report USD | Summary USD | Combined USD | Report time | Summary time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flash 3.8, medium / medium | 0.30817 | 0.04427 | **0.35245** | 186.8 s | 38.6 s |
| Neon 4, medium / medium | 0.91322 | 0.18074 | **1.09397** | 253.4 s | 43.5 s |

Neon made fewer model calls, but used more thinking tokens and had higher token prices. It was **3.10× more expensive overall** and **4.08× more expensive for the summary**. Total active request time was 225.4 seconds for Flash and 296.9 seconds for Neon; a single sequential run is not a reliable latency benchmark.

| Model / task | Model calls | Input tokens¹ | Output tokens | Thinking tokens | BigQuery jobs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flash report | 30 | 332,091 | 5,938 | 10,049 | 4 |
| Flash summary | 5 | 40,349 | 629 | 3,107 | 0 |
| Neon report | 16 | 179,455 | 7,537 | 17,402 | 5 |
| Neon summary | 4 | 39,537 | 793 | 3,349 | 0 |

¹ Input includes repeated context across calls, not just the user's prompt. Flash's report had 2,135 cached input tokens; all other rows had zero reported cached input. Calls include the coordinator, delegated specialists and their reviewers. Delegation charges are counted once.

### Pricing basis

Standard paid Gemini API rates used, in USD per million tokens:

| Model | Uncached input | Cached input | Output, including thinking |
| --- | ---: | ---: | ---: |
| Flash 3.8 | 0.75 | 0.075 | 3.75 |
| Neon 4 | 3.00 | 0.15 | 15.00 |

Flash's listed rates apply through 31 December 2026. Source: [Google Gemini API pricing](https://aistudio.google.com/docs/pricing).

Calculation: `(uncached input × input rate + cached input × cache rate + (output + thinking) × output rate) / 1,000,000`. BigQuery uses each job's reported billed bytes at the application's configured $6.25/TiB estimate. Taxes, credits, free-tier allowances and local compute are excluded. Runtime budget reservations are reported separately where actual usage was unavailable.

## Summary quality

### Flash 3.8 — exact rerun summary

> Across all 26 categories, current modeled unsold inventory stands at 310,553 units with an 8,908,773.88 recorded cost basis, equaling 31.76 times the 9,777 qualifying sales units (585,692.93 in revenue) recorded in Q1 2026. Closer examination is prioritized for Jeans and Outerwear & Coats due to leading inventory cost concentrations, Suits for having the highest stock-to-sales ratio at 40.72, and Dresses for having the lowest ratio at 28.25.

### Neon 4 — exact rerun summary

> Across all brands and 26 matched product categories, current modeled unsold inventory (310,553 units; 8,908,773.88 recorded inventory cost, currency unspecified, as of the November 26, 2026 business cutoff) stands at 31.76x Q1 2026 qualifying sales (9,777 units; 585,692.93 qualifying revenue), with category ratios ranging from 28.25x to 40.72x. The report prioritizes five categories for follow-up checks on recent sales, product-level mix, and inventory age—Suits and Outerwear & Coats (highest ratios), Jeans and Intimates (largest recorded cost and modeled unit shares), and Dresses (lowest ratio)—while noting that historical Q1 qualifying sales do not measure current demand and modeled stock is not verified physical inventory.

| Criterion | Flash | Neon |
| --- | --- | --- |
| Two-sentence instruction | Met; 67 words | Met; 103 words |
| Numerical grounding | Checked figures match the reference | Checked figures match the reference |
| Selection of information | Repeats most headline totals and ratios | Repeats totals, ratios, scope, cutoff and five categories |
| Readability | Shorter, but still formal and number-heavy | More cumbersome, with multiple parenthetical clauses |
| Historical-demand limitation | Not explicitly retained | Explicitly retained |
| Inventory limitation | Says “modeled unsold”; does not explain the limitation | Explicitly distinguishes modeled stock from physical inventory |
| Next steps | Names categories and reasons | Also retains checks on recent sales, product mix and inventory age |

**Neon wins on preserving qualifications; Flash wins on brevity and cost. Neither produces a particularly natural executive summary.** Neither rerun summary repeats the earlier cost-to-revenue comparison or declares proven overstock. Flash's omission of a caveat is a loss of context, not a fabricated numerical claim.

Both full reports provide a measured category shortlist and meaningful limitations. Flash still uses unnecessarily strong language such as “immediate scrutiny” and “high capital exposure.” Neon's report is more careful about distinguishing recorded cost from cash and proposed investigations from established shortages or surpluses. These are qualitative assessments for this case, not calibrated benchmark scores.

## What happened in the initial attempt

At the existing 2,048-token reviewer allowance, Flash produced a report and a 78-word summary. Neon encountered six specialist reviewer schema failures, then another coordinator review-validation failure. Its final report had runtime status `approved` but outcome `partial`: it contained a missing-input explanation rather than the requested comparison. The subsequent summary summarized that failure explanation.

The warehouse queries had succeeded. The final explanation attributed the missing comparison to retrieval/execution limits, which did not accurately identify the review failures observed in the trace. Runtime approval therefore was not evidence that the user's task had been completed.

In the 4,096-token rerun, Neon's successful reviews used:

| Reviewer | Thinking + output tokens |
| --- | ---: |
| Retail | 3,326 |
| Inventory | 3,075 |
| Coordinator report | 3,955 |

All exceed the original allowance. Google documents that `max_output_tokens` caps thinking and output together. The rerun supports the original cap being too restrictive, although the first run did not retain enough raw response metadata to prove the termination reason of each failed call. The coordinator review also came close to the new cap. Source: [Gemini 4 output-token limits](https://aistudio.google.com/docs/whats-new-gemini-4-neon#long-decode).

The initial round allowed up to $2 per prompt within a $2.45 per-model experiment allocation. The rerun initially allocated $1.40 to each two-turn sequence to preserve the overall $5 ceiling. That left Neon only $0.4847 after its report, below the runtime's admission requirement for the follow-up. This was a **test-harness allocation mistake**, not a model failure: zero model calls ran. The same conversation was resumed with a fresh $1.40 prompt allowance; the report was not regenerated and no failed answer entered conversation history. The existing application retained its normal per-prompt budgeting.

### Initial attempt and total experiment cost

| Initial configuration | Report USD | Summary USD | Combined USD |
| --- | ---: | ---: | ---: |
| Flash, 2,048 reviewer tokens | 0.30963 | 0.04911 | 0.35873 |
| Neon, 2,048 reviewer tokens | 0.62472–1.56565 | 0.10856 | 0.73327–1.67421 |

The Neon range reflects six failed reviewer calls without settled usage in the initial capture: its lower end includes known usage and warehouse charges; its upper end retains the runtime's conservative reservations. They are not treated as free calls or presented as exact billed costs.

**All attempts, reruns and the independent reference query total $2.53866 in known list-price usage, with a conservative upper estimate of $3.47959.** This stayed below the $5 experiment cap. The independent reference query contributed $0.000238; the blocked follow-up made no billable calls.

## Recommendation and limits

Do not switch the whole application to Neon solely to fix summary style. Keep Flash as the cost baseline, explicitly evaluate whether summaries select the main finding and preserve the essential limitation, and test that behavior across the existing conversation suite. If adopting Neon for analytical quality, first give its reviewer sufficient output allowance and retain raw usage/termination metadata for failed responses.

This was one scenario, with one successful rerun per configuration. The summaries had different source reports, the runs were sequential, and budget allocations differed between rounds. No blind human evaluation or additional paid LLM judge was used. The results establish what happened in this application test; they do not establish a general model ranking. Production configuration, application code, prompts and skills were not changed.

Local reproduction and diagnostic scripts are in `.artifacts/summary-model-comparison/`. Frozen outputs, numerical references and cost records needed to inspect these findings are included alongside this report.
