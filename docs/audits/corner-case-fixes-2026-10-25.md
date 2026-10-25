# Corner-case fixes — 25 October 2026

This follow-up addresses the findings in the [20-question audit](corner-cases-2026-10-25.md). The original audit remains a historical record of first attempts.

## Changes

- Recognize `customer ID` and explain the individual-geography restriction before any query. Requests for customer contact details now receive an explicit privacy explanation and a supported ID-ranking alternative, rather than silent substitution.
- Explain that profit/margin after shipping, tax and marketing costs is unsupported; do not substitute revenue. These bounded English request checks also handle explicit exclusions of unsupported fields.
- Recognize brand rankings, retain separately requested totals alongside rankings, and validate the requested ranking metric for brands/categories/states as well as products/customers.
- Exclude negated quarter references from the comparison contract while preserving action-period context and year rollover.
- Specify comparison requirements separately. A report comparing revenue needs the prior total and computed revenue changes, not an entire duplicate prior-quarter report. Explicit requests for both quarters' breakdowns retain those requirements.
- Render fallback results as readable tables containing all returned monthly rows instead of taking the first 12 metrics. Preserve selected brands and individual/product filters. Keep the validation warning and do not fabricate missing insights/actions.
- Finish an empty total churn analysis directly after the successful query. Show both as-of dates, zero eligible/inactive counts and an undefined share, with no narrative-generation/repair loop.
- Explain impossible dates and reversed ISO date ranges specifically. Tighten commentary wording instructions to avoid the awkward order-count phrasing and redundant table narration; this is guidance, not a guarantee about all future prose.

## Verification

**175 offline tests passed**, including **18 new regression cases**. Ruff lint/format, strict Pyright, and `git diff --check` passed. One existing ADK experimental-schema warning remains. Offline tests block provider/network access and use synthetic data/isolated stores.

The new cases cover explicit notices without provider calls, ranking dimensions plus totals, negated periods, comparative-report completeness, preservation of all months in fallback, one-call empty-churn handling through the actual ADK tool loop, excluded unsupported fields, and action-period context after a negated quarter.

### Focused live rerun

The same original prompts were used; no retries until success. Five cases terminate locally, and four analytical cases use the real Gemini/BigQuery path with normal commentary settings.

| Original case | Result after fix | Time |
|---|---|---:|
| 4: impossible date | Specific calendar-date explanation, no provider/query call | <0.01 s |
| 5: reversed range | End-after-start explanation, no provider/query call | <0.01 s |
| 8: contact details | Explicit privacy restriction and customer-ID alternative | <0.01 s |
| 9: individual state | Explicit refusal to associate a customer with a location | <0.01 s |
| 10: net profit margin | Explains missing cost measures and distinguishes revenue from profit | <0.01 s |
| 12: Q2, not Q1 | Validated Q2 total and April/May/June table; no Q1 comparison | 44.69 s |
| 15: empty churn | Validated zero counts and undefined share at both dates; one model call | 8.30 s |
| 19: CEO brands + total | Validated total 617,439.84 and top-three brands; no product substitution | 45.47 s |
| 20: comparative report | Validated Q3/Q4 comparison, all Q4 months, product table, labelled hypothesis and Q1 2026 action | 56.53 s |

All four analytical cases returned `quality_status=validated`, with **zero narrative repairs**. Independent read-only SQL matched **all nine evidence sets**, including the empty cohort. The report shows 9,575.34 → 10,374.19 revenue, +798.85 (+8.34%), and Q4 monthly values 3,471.79 / 3,038.12 / 3,864.28, which sum to the total. The proposed action window is 1 January–31 March 2026. Terminal output was reviewed at 100 columns; earlier offline display tests remain green.

The live rerun used 11 completed model calls: 46,392 input tokens and 14,974 output-plus-thinking tokens. At the Gemini 3.8 Flash introductory paid rates checked in this session (USD 0.75 / million input and USD 3.75 / million output), that is approximately **USD 0.091 for the entire focused rerun**, not a billing statement. BigQuery/oracle usage is separate; Gemini Free Tier may charge nothing. The USD 1 per-question limit and billing configuration were not changed.

Local transcripts, original prompts, answers, timings, evidence, oracle SQL/job IDs and logs are under `.retail-agent/corner-fixes-2026-10-25/` (gitignored). No user reports were modified.

## Limits

This is a bounded English intent parser, not proof of correct interpretation of arbitrary language. Unrecognized unsupported metrics or more complex negation remain evaluation targets. No new general-purpose reasoning model, provider, or permission bypass was introduced. The nine-case rerun validates the audited fixes; it is not a fresh full 20-case benchmark or a production reliability estimate. Report persistence and failure-injection checks remain covered by the full offline suite and the earlier live workflow audit.
