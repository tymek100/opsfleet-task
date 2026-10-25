# Direct-plan implementation and same-20 replay — 25 October 2026

**Final replay: 20/20 functional scenarios passed. All 14 evidence sets matched independent SQL; 12 live report-state assertions and 157 offline tests passed.** This is a regression replay of known cases, not a fresh held-out accuracy estimate. An unsuccessful intermediate run is preserved below.

## Implemented change

- Shared executable capability schemas, explicit plan decisions/filters and structured, schema-checked constraint explanations. Clarification identifies missing information. One bounded schema/contract repair; authorization and resource limits are not relaxed.
- Removed blanket second-model review and model-selected analytical tool calls. Code expands, deduplicates and preflights the complete plan before queries. Simple factual output is selected/rendered directly from evidence.
- Optional tool-free ADK narration supplies requested actions, with existing numeric/date/completeness checks and bounded repair/fallback. Commentary is now generated only for explicitly requested interpretation.
- Display effective brand scope and product/customer filters, including empty results. Corrected a churn explanation that claimed the share changed when both snapshots were 100%.
- Preserved trusted identities, scoped compiler/SQL gateway, shared budgets, source privacy, exact owner-scoped report operations and token-only deletion. No question-specific regexes, date/product exceptions or fixture lookups were added to runtime.

See [workflow and limits](../model-planning.md) for architecture and official sources.

## Controlled replay

Questions, identities, session dependencies, settings and original expectations are identical to the [previous 20-case audit](corner-cases-v2-2026-10-25.md); the exact case manifests were compared programmatically. The read prompt uses the ID actually saved in that run. Each run has its own isolated SQLite library. Same Gemini 3.8 Flash, medium thinking, 120-second deadline, eight-call/six-query limits, $1 conservative budget and 13-second provider pacing. No billing tier or quotas were changed.

| # | Final result | Observation | Before (s) | After (s) |
|---|---|---|---:|---:|
| 1 | Pass | Single leap day; all requested measures. | 18.60 | 15.81 |
| 2 | Pass | Exact UTC exclusive endpoint; honest empty result. | 35.88 | 9.24 |
| 3 | Pass | Both totals and 31/28-day normalized comparison. | 76.02 | 20.70 |
| 4 | Pass | Top four categories by units, without unsolicited commentary. | 86.51 | 7.46 |
| 5 | Pass | Same month/top count; distinct-customer ranking. One provider 504 retry. | 74.43 | 59.65 |
| 6 | Pass | Exact two-brand total; effective scope in heading. | 46.11 | 11.93 |
| 7 | Pass | Product IDs retained and shown; empty result stays filtered. | 55.81 | 17.51 |
| 8 | Pass | Specific unsupported country-filter explanation; no query. | 35.94 | 13.83 |
| 9 | Pass | 30-day inactivity, both snapshots and population counts. | 25.81 | 12.35 |
| 10 | Pass | 180-day follow-up, same month and consistent definition. | 24.99 | 8.64 |
| 11 | Pass | Explains 7–365-day bounds; no zero/default substitution. | 37.78 | 10.65 |
| 12 | Pass | Last completed month is September 2026. | 43.19 | 21.11 |
| 13 | Pass | Explains identical-period conflict and asks which comparison; one contract repair. | 24.95 | 41.25 |
| 14 | Pass | Asks for fiscal start month/dates. | 26.06 | 8.60 |
| 15 | Pass | Explicitly declines unavailable net profit without substitution. | 27.96 | 17.00 |
| 16 | Pass | Complete Q2 report and Q3 actions; no comparison or auto-save. | 97.59 | 29.65 |
| 17 | Pass | Exact Polish title saved once. | 24.48 | 7.67 |
| 18 | Pass | Stored answer returned unchanged; no requery. | 26.02 | 16.52 |
| 19 | Pass | Exact owner-scoped preview; no deletion. | 25.59 | 8.39 |
| 20 | Pass | Requires /confirm TOKEN; sentence cannot authorize deletion. | 38.11 | 13.53 |

## Measurements

- Functional outcomes: baseline 12 pass / 2 presentation issues / 6 failed answers; final 20 pass.
- Total wall time: **851.83 → 351.49 seconds**; observed median **35.91 → 13.68 seconds**.
- Report: **97.59 → 29.65 seconds**. The slowest final case was the ranking follow-up (59.65 seconds), with one recorded provider 504 and its bounded retry.
- Recorded model responses: **62 → 22**. The final run had 1 contract repair(s) and 1 provider retry event(s). Simple successful analytics normally use one model response.
- Paid-rate model estimate from recorded usage: **$0.2898 → $0.1320** for the 20 turns. Intermediate-run estimate: $0.1191, plus the separate schema probe. These are not invoices; Free Tier billing can be zero. Failed calls may not report token usage. BigQuery is excluded. Rates assumed: $0.75/M input and $3.75/M output including thinking ([Google pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.8-flash)).
- Final query cache hits: 13 (baseline 0). Provider variability and caching affect timings; these observations do not establish production percentiles or isolate every cause of improvement.

## Independent evidence and report operations

The handwritten BigQuery oracle does not call the application compiler. All 14 returned sets matched, including the newly answered leap day and both inactivity thresholds. The filtered product result is empty; the compiler did not widen it. SQL agreement is evaluated separately from plan faithfulness: a correctly calculated broader query failed the intermediate run. Monthly report values sum to 7,536.22, and the daily-rate comparison remains -11.71%.

Twelve assertions inspect actual SQLite state and query traces: no auto-save, exact title/single save, unchanged stored body, exact rendered read, exact preview set, no preview deletion, no tokenless deletion and no analytical queries for library cases 17–20. Token-confirmed hard deletion was not performed in this replay; offline tests cover confirmation, ownership, expiry, cancellation and replay. The saved test report remains isolated from the user library.

## Intermediate failures retained

The first implementation replay is stored separately and was not reported as successful:

1. Case 7 omitted explicit product IDs and returned an authorized but broader total. All analytical fields are now required in the provider schema and omission is rejected in code. This prevents silent defaults; it cannot prove a model-chosen empty filter is semantically correct.
2. Cases 13, 14 and 20 failed bounded planning repair. Conditional clarification fields were not reliably emitted. The provider schema now requires explicit route fields as well, including missing information.
3. Case 16 hit provider HTTP 400 for the expanded narrative schema and fell back to verified figures without actions. Restoring the existing 120-fact bound made a separate schema probe succeed; the final report passed through the real ADK path. No dependency upgrade was used.
4. Cases 9 and 10 exposed an existing deterministic wording defect: a constant 100% share was followed by a sentence claiming it changed. That sentence now requires a nonzero measured change; an offline regression covers it.

All initial artifacts remain under `.retail-agent/direct-plan-2026-10-25/`; the schema probe is in `.retail-agent/direct-plan-schema-probe/`. The final complete rerun is `.retail-agent/direct-plan-final-2026-10-25/`. No question-level rerun was hidden within either 20-case sequence. Provider-internal retries remain recorded.

## Verification and remaining limits

- `pytest`: **157 passed, 17 live tests deselected**, 3.78 seconds. Old second-review/tool-selection-loop assertions were replaced with direct-execution, explicit-schema, repair, budget and narration tests. The earlier 164-test count is not retained coverage.
- Ruff lint/format, strict Pyright and source/wheel build passed. Native structured output avoids the prior experimental tool warning in this suite.
- Actual 80/120-column terminal transcripts were reviewed. Tables and effective filters are readable. Report text remains English for a Polish request, and action templates remain generic proposals.
- A schema-valid plan can still misunderstand a question. The same known 20 cases helped refine this implementation; a fresh holdout is needed for a new generalization claim. Optional prose review is fallible, and source dataset state can change.
- Final source fingerprint: `d038b84a7f55660e`; prompt fingerprint: `869263f5a643e150`. Raw prompts, answers, settings without credentials, traces, timing/token counts, oracle SQL/jobs and workflow assertions are retained in the gitignored final artifact directory.
