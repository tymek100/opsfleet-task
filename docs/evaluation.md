# Evaluation record — 22 October 2026

The prototype has **85 passing offline tests**. Ruff lint/format and strict Pyright checks pass. A clean uv runtime installation, CLI entry point, source distribution and wheel build were verified on Python 3.12.12/macOS ARM64. The offline CI workflow is defined but has not been run on GitHub in this implementation session.

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

After implementing the structured contract, the first live report attempt revealed that ADK 2.12's `set_model_response` path tried to JSON-serialize Python date objects. Added explicit ISO date serialization and a regression test that exercises that actual ADK tool path, not just final text responses. The corrected focused live report passed, and manual inspection confirmed the four original issues were addressed. See the [observed report excerpt](examples/q1-report.md).

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
