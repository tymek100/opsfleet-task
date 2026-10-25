# Gemini 3.8 Flash high: commentary and live cost evaluation

Date: 2026-10-25. Scope: implement optional model-written interpretation, switch to the requested model, and exercise three distinct questions against real Gemini and BigQuery. This is a small development sample, not a production benchmark.

## Implemented behavior

- Default and local configuration: `GEMINI_MODEL=gemini-3.8-flash`, `THINKING_LEVEL=high`, `MAX_OUTPUT_TOKENS=8192`, `MAX_MODEL_CALLS=8`, `COMMENTARY_ENABLED=true`. The existing USD 1 reservation limit and 120-second turn deadline remain unchanged.
- The agent still computes and validates numbers in application code and renders deterministic tables. The optional writer receives verified findings and the authorized metric catalog, without tools, raw user text or conversation history.
- A structured commentary draft supplies supporting metric references. Deterministic checks reject unknown/duplicate references, digit-containing prose, detected personal details, links and markup. A separate tool-free model call checks factual support, relevance and safety. Accepted prose is labelled **AI commentary**, separate from **Verified findings**.
- If writing/review fails, is rejected, or exhausts the shared budget/deadline, existing verified findings survive. No commentary-specific repair loop or additional tool access is added. The existing one-retry provider policy remains bounded by the same turn limits.
- All provider responses emit input, output, thinking and cached token counts. BigQuery events include billed bytes. No hidden reasoning or raw prompts are logged.
- Planning instructions now request independent queries together and only relevant output metrics. They discourage unnecessary schema calls and repeated ranking queries with different limits.

Semantic review is probabilistic, including when the reviewer is a separate call to the same model. It does not prove prose truth or guarantee privacy. Source minimization, deterministic numbers and the existing authorization boundaries remain necessary. No report was automatically saved by these tests.

## Price snapshot and method

The [official Gemini pricing page](https://ai.google.dev/gemini-api/docs/pricing) lists standard Gemini 3.8 Flash introductory rates through December 31, 2026: USD 0.75/M uncached input tokens, USD 0.075/M cached input tokens, and USD 3.75/M output tokens **including thinking**. Published rates from January 1, 2027 double those token prices. High changes token consumption, not the per-token rate used here. See also [model migration guidance](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.8).

For completed responses, the list-price estimate is:

```text
((input - cached) * 0.75 + cached * 0.075 + (output + thinking) * 3.75) / 1,000,000
```

BigQuery US on-demand list cost uses billed bytes / 2^40 * USD 6.25, before the monthly free allowance. Cached query results are not charged. See [BigQuery pricing](https://cloud.google.com/bigquery/pricing).

These are usage-based list-price estimates, not an invoice or a reading of account credits. Failed/timed-out model requests may not return usage; observed costs then do not establish total spend. Missing usage is **unknown**, not evidence of zero cost. Conservative admission reservations still use the configured USD 2/M input and USD 12/M output rates plus query caps. They intentionally exceed these measured estimates.

## Questions

1. `Show the top 10 customers by total spend for Q1 2026.`
2. `Compare total revenue in Q4 2025 and Q1 2026. Show revenue, units sold, orders, and distinct customers for each quarter. Calculate the absolute revenue difference and percentage change from Q4 to Q1. Explain whether the quarters contain the same number of days and distinguish total growth from daily performance.`
3. `Create a report for Q1 2026 including insights and action items for Q2 2026.`

Identity: Alice, Calvin Klein only. Each question starts a fresh conversation. Settings retain 13-second model pacing and a 100 MB per-query cap. Local diagnostic stores are isolated under the ignored `.retail-agent/commentary-evaluation/` directory.

## Initial run

| Question | Outcome | Time | Recorded Gemini list cost | BigQuery list cost |
| --- | --- | ---: | ---: | ---: |
| Top customers | Verified results and accepted AI commentary | 75.65 s | $0.044422 | $0 |
| Quarter comparison | Provider error after bounded retry | 114.35 s | $0.008219, incomplete | $0 |
| Quarterly report | Turn deadline exceeded | 120.01 s | $0.039718, incomplete | $0.000358 |

The first successful commentary explained that the ranked customers each had one qualifying order/item and that spend differences reflected item values, within the displayed brand/period scope. It did not invent repeat purchases or margin information. However, the model selected unnecessary table columns. Planning instructions were tightened to avoid that verbosity and combine independent queries, then all three questions were repeated once.

## Final run after planning changes

| Question | Outcome | Time | Recorded Gemini list cost | BigQuery list cost |
| --- | --- | ---: | ---: | ---: |
| Top customers | Verified results; commentary omitted on timeout | 120.01 s | $0.029371, incomplete | $0 |
| Quarter comparison | Verified results; commentary rejected by semantic review | 111.57 s | $0.062560 | $0 |
| Quarterly report | Provider 504; bounded retry also failed | 88.42 s | Unknown: no usage returned | $0 |

| Question | Input tokens | Candidate output | Thinking tokens | Cached input | Response usage records |
| --- | ---: | ---: | ---: | ---: | ---: |
| Top customers | 12,466 | 346 | 5,508 | 2,860 | 3 |
| Quarter comparison | 12,308 | 537 | 13,684 | 0 | 4 |
| Quarterly report | Unknown | Unknown | Unknown | Unknown | 0 |

Final trace IDs: `69319cdb34034d89a2ffbb28e1f8f060`, `a11e5dc3906f42aabfea917bb62eebe5`, `f38eeeee49c04be9bbeceed8f2f655ce`.

The semantic rejection record in this run identifies the rejection stage, but does not preserve the rejected prose or distinguish the three review flags. The implementation now records the support/relevance/safety booleans for future rejections without logging prose. No claim is made about which particular sentence caused this rejection.

## Independent numerical verification

A separately authored, parameterized, read-only BigQuery aggregation used item dates, Calvin Klein, and both item/order status exclusions. It did not call the application's SQL compiler. Cache was disabled; dry-run and 100 MB cap were applied. Job: `926ec40c-7721-4d0c-b51a-be9c3cca9494`; billed bytes: 31,457,280 (about $0.000179 before the free allowance). This verification cost is separate from the question costs above.

All 40 customer-ranking metric cells matched in each successful ranking answer. All eight base metric cells in the final quarter comparison matched. Decimal arithmetic independently confirmed:

| Metric | Q4 2025 | Q1 2026 |
| --- | ---: | ---: |
| Revenue | 10,374.19 | 10,200.38 |
| Units | 157 | 163 |
| Distinct orders | 157 | 162 |
| Distinct customers | 157 | 162 |
| Calendar days | 92 | 90 |

Absolute revenue difference: -173.81; revenue change: -1.6754079%; daily revenue change: +0.5095830%. The rendered -1.68% and +0.51% are correct. No report answer was produced in the final report case, so report completeness and commentary were **not** verified live.

## Offline checks and conclusion

145 offline tests passed, with three pre-existing live tests deselected. Ruff, formatting and strict Pyright passed. Focused tests cover unsupported references, detected personal details, numeric/markup text, reviewer rejection, missing/invalid provider responses, timeout, call limits, thinking-token telemetry, and actual ADK integration with accepted/rejected commentary. Existing authorization and deletion tests continue to pass. Tests use synthetic providers; their pass count does not establish live model quality.

The requested model is configured and the commentary mechanism has a successful live example. The final numerical answers that completed are correct, and rejection/timeout preserve verified findings. However, this sample does **not** establish that 3.8 Flash high is reliable or meets the 10–30 second simple-question target. Both initial and final report attempts failed, and final comments were omitted or rejected. Keep this limitation visible rather than treating a stronger model as an automatic quality upgrade. A follow-up controlled comparison with medium thinking or another available model would be appropriate; no silent model/effort downgrade was applied here.
