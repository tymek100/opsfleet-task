# Historical evaluation journal

Archived during submission-documentation cleanup. Statements and counts below describe their dated versions; use the [current evaluation](../evaluation.md) for the reviewer summary.

# Evaluation record

## Targeted fixes and new variants — 25 October 2026

The final replay of **10 new targeted questions passed 10/10**, with **50 acceptance checks**, **10 independent SQL evidence checks**, and **167 offline tests**. Initial attempts exposed an empty-sales aggregate defect, an exhausted-server-error message gap, and an unclear mapping from monthly cardinality to the row limit. All were corrected, and unsuccessful attempts were preserved. Changes also cover explicit comparison baselines, disjoint periods, bounded ordered library operations and actual cancellation, nonmutating help, specific refusals, and bounded timeout recovery. Gemini remains on `medium`; no question-specific parser or exceptions were introduced.

On the completed implementation, median time was approximately **14.15 seconds**, with **no provider retries, semantic repairs or fallback reports** in the final ten. Recorded paid-rate token estimate was **$0.06974** for that batch and **$0.31249** across all 38 attempts in this work session, not an invoice. Five of six original regressions passed together; the sixth passed separately after the capability refinement, following retained provider and planning failures. This does not establish future provider availability. See the [implementation, exact prompts, failed attempts and final evidence](targeted-fixes-v4-2026-10-25.md).

## Fresh holdout after direct-plan migration — 25 October 2026

**20 new first attempts: 14 pass, 2 UX issues, 3 functional failures and 1 provider timeout.** All **14 raw evidence sets** matched independent SQL, but derived comparisons have two deterministic defects: chronological sorting reverses an explicitly requested baseline, and the adjacent-period restriction prevents a year-over-year report from completing. Natural-language cancel-and-list only lists reports and leaves the pending deletion active. Eight report-state checks passed; actual cancellation failed. Median time was **14.84 seconds**, with a recorded paid-rate token estimate of **$0.158**. No runtime fixes or question-level reruns were made. See [questions, results and root causes](fresh-holdout-v3-2026-10-25.md).

This fresh set qualifies the successful known-case replay below; schema validation and raw SQL agreement do not prove that derived comparisons or multi-operation requests fulfill user intent.

## Direct-plan implementation and same-20 replay — 25 October 2026

After removing blanket plan review and model-driven query selection, the final replay of the same **20 cases passed all 20 functional scenarios**. All **14 evidence sets** matched independent SQL, **12 live report-state assertions** passed, and **157 offline tests** passed. Median time decreased **35.91 → 13.68 seconds**; the report **97.59 → 29.65 seconds**. Recorded paid-rate token estimate decreased **$0.290 → $0.132**; this is not an invoice. The run included one provider 504 retry and one bounded contract repair. An intermediate run exposed omitted filters, incomplete clarification fields and a provider schema rejection; those failures and fixes are preserved in the [full comparison](direct-plan-replay-2026-10-25.md). These are known regressions, not a fresh holdout.

## Fresh corner cases after model-planning migration — 25 October 2026

**20 new first-attempt prompts: 12 pass, 2 presentation issues, 6 failed answers.** Four valid plans were unnecessarily blocked by semantic review; unsupported country/zero-day constraints produced inadequate explanations. All **10 returned evidence sets** matched independent SQL, **12 live report-state assertions** passed, and **164 offline tests** passed. Simple analyses remained slow (43–87 seconds); the report took 97.59 seconds. The paid-rate token estimate for all 20 turns was approximately **$0.290**, not an invoice. No runtime changes were made in this audit. See [exact questions, failures and evidence](corner-cases-v2-2026-10-25.md).

This fresh set qualifies the earlier 14-case semantic regression pass below: model review can reject valid requests, and passing schema/contract checks does not establish useful answers.

## Model-proposed planning — 25 October 2026

The natural-language regex/keyword resolver, duplicate action-date parser and exact-phrase save shortcut have been replaced by structured Gemini planning, a separate semantic review and deterministic contract/execution validation. See [design and official research sources](../model-planning.md).

**164 offline tests passed**, with 17 live tests deselected and the known ADK experimental warning. Ruff lint/format and strict Pyright passed. The previous 175-test count included obsolete regex interpretation assertions; those were replaced by contract/orchestration tests and a separate live semantic suite, not retained as evidence about the model.

The final **14-case semantic regression suite passed against Gemini 3.8 Flash in 138.67 seconds**. It covers negation, ranking dimensions, missing years, invalid dates, unsupported metrics, privacy, exclusions, role spoofing, status overrides and follow-ups, Polish, deletion preview and explicit relative years. Expected fields and required outputs are asserted in code. These cases helped refine the prompts, so this is regression evidence, not an unbiased held-out accuracy estimate.

First attempts exposed real limitations:

- The reviewer unnecessarily asked a manager whether a report should use their authorized brand. The review policy now explains implicit scope and allowed default report sections.
- A follow-up produced an empty analytical contract. Provider output now requires period and nonempty requirements, with application-side validation still authoritative.
- The initial semantic run passed 11 of 12 cases but silently assumed a current year for an unqualified quarter. Both prompts now explicitly require clarification when neither question nor relevant history supplies a year. Two additional year cases were added; all 14 passed on the final run.

End-to-end observations:

| Scenario | Result | Wall time |
|---|---|---:|
| CEO top-three brands plus total | Validated; correct brand ranking and separate total. Provider 504 retry and optional commentary timeout occurred; verified evidence remained available. | 120.01 s |
| Manager Q4 versus Q3 report with next-Q1 actions, after scope fix | Validated; total comparison, all three months, top-five products and correctly dated actions. No automatic save. | 118.26 s |
| Follow-up switching to Q2, explicitly excluding Q1 and actions | Validated; requested period, complete monthly figures, no extra comparison/actions. | 70.30 s |
| Customer-contact request | Application-owned privacy notice; no analytical execution. | 19.21 s |

Independent handwritten BigQuery SQL matched **all eight evidence sets** across the ranking, corrected report and follow-up. Q4 revenue was 10,374.19 versus Q3 9,575.34, a change of 798.85 (8.34%); the follow-up Q2 total was 15,273.95. This validates the observed data, not arbitrary future interpretations.

Planning/review add two model calls per natural-language turn and share existing budget/deadline limits. Recorded tokens for the corrected report were 31,307 input, 1,103 output and 11,669 thinking; the follow-up used 27,182 input, 682 output and 4,693 thinking. At the assumed introductory rates of $0.75/M input and $3.75/M output including thinking, these correspond to approximately **$0.0714 and $0.0405**, respectively; they are token-based estimates, not invoices or the conservative budget reservation. Free-tier billing can differ. The $1 cap was not increased.

Raw local artifacts, including unsuccessful first attempts: `.retail-agent/model-planning-2026-10-25/` (gitignored). Final semantic artifacts are in `semantic-evals-v2/`; numerical oracle results are in `verification/oracle-results.json`. The same-model reviewer can repeat planner mistakes, and these timings are observations rather than latency percentiles. Hosted CI and a broad fresh held-out evaluation remain unverified.

## Corner-case fixes — 25 October 2026

The audited intent, comparison-report and fallback issues have been fixed. **175 offline tests passed**, including 18 new regressions; lint, formatting and strict typing passed. All **nine focused rerun cases** behaved as intended (five local explanations and four live analyses), and independent SQL matched **nine evidence sets**. Empty churn dropped from 120 seconds to 8.3 seconds; the comparative report now includes verified comparisons and dated actions. See the [fixes and verification record](corner-case-fixes-2026-10-25.md).

## Corner-case audit — 25 October 2026

A new live audit executed **20 held-out prompts: 11 passed, 4 had safe-response UX/completeness issues, and 5 failed intent/relevance/report presentation**. All **25 evidence sets**, including an additional successful baseline report, matched independent BigQuery SQL. **19 report workflow assertions** and **157 offline tests** passed. Main gaps are silently substituted metrics/groupings, negated periods, comparative-report requirements and truncated fallback output. These findings qualify the earlier successful smoke checks below; no runtime fixes were made in this audit. See the [full questions, results and evidence](corner-cases-2026-10-25.md).

## Latest verification — 25 October 2026

Following the audit fixes: **110 offline tests passed**, Ruff and strict Pyright passed, and the source/wheel build succeeded. **All three live tests passed**, covering rankings, a follow-up, quarterly report generation and an independent churn analysis. See the [remediation record](remediation-2026-10-25.md) for exact scope, timings, conservative cost reservations and remaining limitations.

Earlier results below are historical evidence; their quota-blocked status is not the latest run. Hosted CI and human UX evaluation remain unverified.

## Historical evaluation — 22 October 2026

At that checkpoint, the prototype had **85 passing offline tests**. Ruff lint/format and strict Pyright checks pass. A clean uv runtime installation, CLI entry point, source distribution and wheel build were verified on Python 3.12.12/macOS ARM64. The offline CI workflow is defined but has not been run on GitHub in this implementation session.

The quarterly-report flow **passed a focused live check with the new structured quality boundary**. The complete live scenario suite has **not passed end to end**: the latest broader retry passed validated rankings, then a Gemini rate-limit delay exceeded the configured retry/deadline allowance during the follow-up, preventing the churn scenario from running. Successful live BigQuery and Gemini observations are listed separately below. This is an evidence record, not a claim of production reliability or a guaranteed interview ranking.

## Offline checks actually executed

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest -q --tb=short
```

| Layer | Assertions exercised |
|---|---|
| Numerical SQL oracle | Synthetic shared customers, mixed-brand orders, repeated purchases, returns, order/item status mismatch, monthly boundary and future purchases. Alice revenue 350 vs CEO 1,250 in the fixture; distinct orders/customers independently asserted. |
| Query admission / privacy | Invalid plans, unknown raw-SQL/role fields, out-of-scope brands, Hypothesis-generated brand strings, bound injection-like values, absent prohibited columns, state cohorts and individual-filter denial. |
| Churn | Brand-scoped first/last history, changing eligibility, future/other-brand purchases excluded, deterministic decrease/undefined premise checks. |
| Report state | Owner/session checks including CEO isolation, exact-set confirmation, new matches excluded, expiry, cancellation, replay, stale versions, transactional rollback and managed-chat purge. |
| Actual ADK loop | Scripted model responses traverse real tools, callbacks and Runner. Captured outbound requests contain no synthetic source PII canaries. Follow-up context, malformed-plan repair, unrequested metric overrides, denial, draft-not-saved behavior and deletion preview are checked. |
| Provider faults | Dry-run scan rejection before execution, execution byte limit, uncertain submission recovered by the same job ID, timeout cancellation, unexpected result columns, sanitized errors, shared cost/call/deadline limits. |
| Model resilience | Bounded transient retries, no retry on permanent 403, reservation accounting and honoring a synthetic provider RetryInfo delay. |
| Report quality | Independent metric calculations, undefined denominators, compatible comparison scopes, invented margin/metric rejection, free-prose rejection, labelled hypotheses, February/Q2 mismatch, quarter/year rollover, target domains, tool-free single repair, failed repair fallback, no auto-save and continued chat. |
| CLI | Owner-scoped library/delete/cancel/confirm/replay flow without cloud credentials; unknown identity rejection; evidence rendered independently of model prose. |

Offline execution blocks network sockets and substitutes fake credentials; Unix sockets are allowed for asyncio internals. DuckDB executes SQLGlot-translated generated queries over synthetic data. This validates numerical intent and scope on the fixture, **not** BigQuery dialect compatibility. Real BigQuery checks complement it. No live model calls occur in Hypothesis tests.

One known warning comes from ADK's experimental structured final-response tool. It is retained in test output rather than hidden. Test success does not validate all future framework/model versions; the lockfile and live compatibility suite are important.

## Live observations

Credentials: updated user-supplied Gemini key and separately configured Python ADC. No credentials are included in this report. Dataset: `bigquery-public-data.thelook_ecommerce`; model: `gemini-3.5-flash`; locked ADK 2.12.0, BigQuery client 3.46.2, SQLGlot 30.24.0. Results depend on the public dataset's state.

| Check | Observed result |
|---|---|
| BigQuery schema via Python ADC | Success after Application Default Credentials were configured. |
| Scoped Q1 total | Success; 12,991,542 bytes processed in one observed Alice query. |
| Live two rankings | Success with separate product revenue/customer queries and evidence; observed reserve about $0.1455 in a two-query run. |
| Live follow-up | Success; prior Q1 period retained, total and monthly queries returned. Observed reserve about $0.2647 in one run. |
| Live churn investigation | Success in an earlier suite run; total and brand snapshots returned. Later repeated runs encountered quota limits. |
| Live quarterly report, with quality boundary | Passed: four queries, two model calls, no repair or transient retry; 16.06 seconds from trace events, $0.171114 reserved. Verified findings, code-calculated basket size and quarter-over-quarter revenue change, unverified hypotheses and Q2-only action dates; no automatic save. |
| Direct state analysis | Success as Alice, six aggregate rows; 14,941,405 bytes processed. This exercises the users table without personal contact fields. |
| Direct Bob product analysis | Success, ten product rows; 14,467,039 bytes processed. |
| Direct CEO brand churn | Success, 100 bounded snapshot rows; 11,538,774 bytes processed. Compiler preserves paired snapshots for at most 50 selected brand cohorts. |

These are a handful of observations, not latency percentiles, measured answer-accuracy rates or actual billing totals. Reserved cost is conservative admission accounting, not invoiced spend. Free-tier allowances and cache hits can reduce billed cost. Current quotas may prevent a reviewer from reproducing all scenarios in one run.

### Earlier retry and report review (before the quality boundary)

After the user updated quota/billing settings, the full suite completed rankings with two queries and $0.226383 reserved, then failed during the follow-up after transient 503 and 429 responses; its final provider error was 503 (high demand). The focused report check then completed successfully under the existing deadline and budget. This verifies the corrected report routing, but does not establish sustained provider availability or confirm the account's billing tier.

Manual comparison of that report with its returned evidence confirmed Q1 revenue of $9,687.79, 168 units, 167 orders and 167 customers for Alice's Calvin Klein scope, versus Q4 revenue of $11,198.01 and 161 units. Its monthly totals and leading product figures agreed with the returned rows. These figures describe this particular public-dataset snapshot.

The earlier report exposed the need for stronger narrative-quality controls: it described seasonality as an observed association without a seasonal comparison; called products “high-margin” without margin evidence; and mentioned February in an action intended for Q2. Its basket explanation also relied on customer/order counts where units/order is the relevant measure (although the stated 1.01 units/order baseline agrees with the evidence). At that point the live test only checked evidence/action presence, so it did not detect these issues. They now have offline regression cases and a structured report boundary: facts resolve to actual metrics, basket ratios are computed in code, seasonal explanations stay explicitly unverified, margin claims are unavailable, and Q2 dates are independently validated. The live test now requires `quality_status=validated`, verified findings, proposed actions and the correct Q2 interval. This is still a bounded contract check, not proof of complete analytical relevance or a comprehensive production quality benchmark.

### Latest quality-boundary verification

After implementing the structured contract, the first live report attempt revealed that ADK 2.12's `set_model_response` path tried to JSON-serialize Python date objects. Added explicit ISO date serialization and a regression test that exercises that actual ADK tool path, not just final text responses. The corrected focused live report passed, and manual inspection confirmed the four original issues were addressed. See the [observed report excerpt](../examples/q1-report.md).

The subsequent rankings/follow-up/churn test passed rankings with two queries, `quality_status=validated`, and $0.271093 reserved. The follow-up then hit a provider rate-limit delay outside the allowed retry/deadline bound; churn was not reached. A fixture-backed ADK churn check separately verifies code-derived direction and changing eligible denominators. No complete post-change live suite pass is claimed, and provider availability is not under application control.

The offline suite now includes the original four report mistakes, typed nested-date compatibility, successful repair, invalid/schema/tool-call repair failures, exhausted repair call budgets, unavailable repair transport, and continued chat after fallback. The report repair has no analytical or library tools. The known ADK experimental-schema warning remains visible.

## Defects found and changes made

- Added a typed report-quality contract, deterministic rendering, and one tool-free repair under the shared budget/deadline; failed repairs show verified figures only.
- Found and corrected the missing runtime connection to the existing model pacer; the analyst now passes its shared pacer into the model, including repair calls.

- The quarterly-report narrative was incorrectly replaced when the model labeled it as a library response. Fresh evidence now retains the analytical narrative; a regression test covers the mislabel.
- A live model requested Complete-only metrics without user instruction. The tool now rejects unrequested overrides and returns correction guidance; the default remains exclusion of Cancelled/Returned statuses.
- Repeated provider 503s made 3.8 Flash unsuitable for the initial demo run. 3.5 Flash succeeded and was selected explicitly as the configurable default.
- Free-tier 429s exposed insufficient spacing/backoff. Calls are now paced by default, and one retry honors the provider's delay within the question deadline; oversized delays fail safely instead of blocking indefinitely.
- Churn cohort limiting now selects whole cohorts before returning both snapshots, avoiding a row limit that could silently discard the second period. Direction/percentage-point comparison is calculated in code.

## What remains unverified

- A complete successful four-question live suite in one run; individual scenarios have succeeded across separate runs, including the corrected Q1 report.
- Broad model answer-quality and adversarial prompt testing across a frozen holdout set; metric correctness and the bounded report contract are checked; completeness of selected facts, usefulness and proposed-target feasibility still need broader evaluation.
- Representative nontechnical-user UX sessions, production load/latency/error-rate tests, Linux/Windows runtime testing and hosted CI execution.
- Production SSO, IAM isolation, DLP quality, centralized telemetry, backup erasure/restore behavior, retrieval, persona publishing and learning. These are design-only deliverables.

## Reproduce and extend

Run the opt-in live suite with your credentials:

```sh
uv run --locked pytest -m live --force-enable-socket -s tests/test_live.py
```

To isolate the report without repeating earlier scenarios:

```sh
uv run --locked pytest -m live --force-enable-socket -s tests/test_live.py::test_live_quarterly_report
```

The full suite runs four questions with a configurable maximum of $1 reserved per question by default, and creates only temporary report storage. Record model/version, period, scope, query/evidence IDs, timings and failure categories. Do not remove a failing check just to show a green demo.

For answer quality, independently grade: intent/period/scope correct; metrics/numbers agree with evidence; claims cite evidence; causal hypotheses are labelled; uncertainty/empty denominators are explicit; actions are specific and tied to a measurable outcome; language suits an executive. A model judge can assist but cannot be the sole privacy, authorization or numerical oracle. Use unseen fixtures/questions so Golden examples do not contaminate evaluation.

For UX, ask representative executives to complete ranking, follow-up, report-save and delete/cancel tasks without coaching. Measure completion, time, clarifications, mistakes and confidence; specifically ask what they believe will be deleted. No such user study is claimed in this submission.

## Follow-up regression: explicit quarter comparison

The exact question comparing Q4 2025 and Q1 2026, then referring again to “Q4 to Q1”, exposed a resolver bug: repeated quarter references were treated as missing-year requests. This is fixed, with regressions for unambiguous references, genuinely ambiguous years, complete metric requirements, daily normalization, undefined growth baselines, and metadata-free clarification replies.

Verification: 130 offline tests passed; Ruff and strict Pyright passed. The exact question also completed through Gemini and BigQuery with `quality_status=validated`. A separately authored BigQuery aggregation confirmed every revenue/unit/order/customer total below for the Calvin Klein scope. This live check used the existing credentials; no secrets or customer-level data were exported.

| Period | Revenue | Units | Orders | Customers | Calendar days |
|---|---:|---:|---:|---:|---:|
| Q4 2025 | 10,374.19 | 157 | 157 | 157 | 92 |
| Q1 2026 | 10,200.38 | 163 | 162 | 162 | 90 |

The generated comparison reported −173.81 revenue difference, −1.6754% total revenue change, and +0.5096% average daily revenue change. Independent fixture tests distinguish a decline caused solely by different calendar lengths (920 over 92 days versus 900 over 90 days) from a change in daily revenue. Live public data can change; these numbers are an observed verification result, not a permanent golden answer.

### Gemini 3.8 Flash high and optional commentary follow-up

See the [dated commentary and cost evaluation](gemini-3.8-commentary-2026-10-25.md).
The requested model and high thinking are configured; 145 offline tests pass.
Live customer and comparison results matched an independent BigQuery aggregation,
but provider 504s/timeouts blocked report generation. Optional commentary succeeded
in one initial case and was safely omitted/rejected in final cases. Recorded token
costs, missing-usage limitations, latency and unsuccessful attempts are reported separately.

### Ten-question medium-thinking evaluation

The [2026-10-25 medium evaluation](medium-ten-questions-2026-10-25.md) covers ten
live questions and includes [full displayed answers](medium-ten-transcripts-2026-10-25.md).
All 179 checked metric/NULL cells and the tested brand boundary matched independent
BigQuery checks. However, one requested ranking was hidden by an intent-parser gap,
and churn, empty-data, refusal and commentary wording need improvement. Six answers
included commentary; three analytical drafts were rejected. Median latency was
approximately 47 seconds with 13-second inter-call pacing. These results distinguish numerical
correctness from intent completeness and executive readability.

### Remediation of the medium-thinking evaluation

See the [remediation audit](medium-ten-remediation-2026-10-25.md) for ranking coverage, churn presentation, permission/empty-result handling, evidence-bound commentary references and follow-up verification. The earlier ten-question report remains a record of behavior before these fixes.
