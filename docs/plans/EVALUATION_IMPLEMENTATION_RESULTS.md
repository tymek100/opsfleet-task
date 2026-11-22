# Evaluation rebuild: implementation and observed results

**Date:** 2026-11-22. **Scope:** synthetic fixtures, actual Gemini calls, independent offline grading, and local Phoenix. This is a diagnostic implementation baseline, not a production-quality estimate.

## Delivered

- Replaced the old `evals/`, historical runners and test implementations with `evaluation/` and a reconstructed offline suite.
- Added 43 canonical cases, nine independent fixtures and 40 paired judge controls. Runtime Golden Knowledge remains separate from evaluation references.
- Added isolated conversations, frozen clocks, typed confirmation/cancellation, scheduled faults, per-prompt budgets, run-wide limits and frozen artifact hashes.
- Added independent Decimal/set references, bound-fact checks, observed-evidence grading, exact report-state checks and versioned grader outputs.
- Added local Phoenix traces, datasets, experiments and annotations. Publication imports saved results rather than executing agent tasks again.
- Removed repository Codex skills and their manifest. Runtime ADK analytical skills remain an application feature.

Canonical pilot v3 clarifies previously implicit acceptance requirements. Its 43 cases are code-verified and **not human-approved**. Frozen experiments retain their original requests/references; changing canonical cases does not rewrite previous results.

## Verification

The completed offline suite passed **249 tests**; the optional Phoenix service test passed separately. Ruff, formatting and Pyright passed. The runtime Golden validator also passed all 11 examples, 14 queries and 23 explicit reference facts.

The checks cover scope, SQL restrictions, metric grain, statuses, UTC boundaries, NULLs, zero denominators, category reconciliation, pagination, budgets, provider settlement/retry, exact publication, private reports, deletion confirmation, context bounds, CLI behavior, reference isolation, grading failures and capture redaction. Offline tests block ambient dotenv and Google credential discovery.

After restarting Phoenix, both live experiments and their 181 annotations remained available. The collector retained 204 spans, including nine prompt spans and 51 provider attempts. Provider attempts matched the runtime ledger exactly: **51 model calls and 274,170 total tokens**. Only provider-attempt spans contribute token totals, avoiding nested ADK double counting. A separate scripted integration test verifies case/run/repetition correlation and trace linkage.

## Live agent experiments

All calls used `gemini-3.8-flash` against the independent `retail_v1` fixture, with an evaluation clock of `2026-04-02T12:00:00Z`. Every repetition started with isolated state. No production warehouse or user report library was used.

| Scenario | Trials / user turns | Runtime results | Independent published-answer result | Agent accounted cost |
|---|---:|---|---|---:|
| Q1 qualifying revenue, customers, orders and AOV | 3 / 3 | Three reviewed answers; 16.6–20.3 s | 3 PASS | Included below |
| Revenue change versus an unproven demand explanation | 3 / 3 | Three reviewed answers; 39.4–66.1 s | 3 PASS | 0.575744 USD for both repeated scenarios |
| Quarter comparison, category contributions, concise follow-up | 1 / 3 | Three reviewed answers; 78.7 s total | 1 conversation PASS | 0.234531 USD |

The repeated suite passed all three attempts for both selected cases. The category conversation had one repetition, so it does not establish repeated reliability. Across the nine published answers, **53/53 required numerical facts** matched independent references and the judge labeled **74/74 assessed factual claims** as supported. These are small, selected, synthetic samples; they do not estimate general hallucination rates.

Observed calculations included:

- Q1 revenue 798, 12 customers, 20 orders, AOV 39.90.
- Q4 revenue 570; the increase was 228, or 40%.
- Category changes: Outerwear +240, Suits -140, Tops +60, Other +68, totaling +228.
- In the final follow-up, grouping everything except Outerwear and Suits correctly changed the remainder to +128.

The offline judge also considered two runtime-rejected drafts valid against the frozen requirements. This is a reviewer/grader disagreement to audit, not proof that those reviews were unnecessary. No independently invalid draft was present in that small candidate sample, so its reviewer false-accept rate is undefined.

The final grading passes cost 0.428842 USD and 0.176824 USD. Costs use configured conservative rates; they are not invoices. Prior grading attempts, diagnostics and calibration calls have their own retained cost records.

## Grader failures found and repaired

Initial live grading produced attribution errors because the judge removed Markdown emphasis from quoted answer spans. The six-trial run initially had two passes and four grading errors; the category conversation had a grading error. Those artifacts were preserved.

A first repair constrained quotes to full verbatim excerpts in the response schema. Gemini rejected the larger schema. The final implementation uses short source IDs, resolves them back to exact original text, and then applies attribution and Decimal checks. Unknown IDs, fabricated spans, malformed responses and missing evidence remain failures or unresolved judgments. Provider/schema/attribution diagnostics are retained with bounded, sanitized visible output; hidden thoughts and credentials are excluded.

The same saved agent answers were graded again with the new judge version. The agent was not rerun and no answer was selected from repeated attempts. This demonstrates a grader compatibility repair, not an improvement in agent behavior.

The fixed judge was tested against 16 family-separated validation controls:

| Measurement | Result |
|---|---:|
| Correct controls accepted | 8 / 8 |
| Deliberately defective controls rejected | 8 / 8 |
| Resolved controls | 16 / 16 |
| Code-authored expected claim spans covered | 16 / 16 |
| Required fact slots extracted | 25 / 26 |

The controls include wrong values/periods, unsupported causal claims, fabricated support, stale-report authority and grader injection. Required-slot coverage is not human-annotated extraction recall. Human calibration remains pending. An additional code-only rescore recognizes observed report IDs as sources while excluding IDs embedded in query rows; it does not make stale report content authoritative for current facts.

## Artifacts and reproduction

Run artifacts are ignored local outputs under `.artifacts/evaluation/`:

- Repeated scenarios: `run-20261122T122912Z-5c1f467e`, final grade `grade-20261122T124522Z-f2b8a51b`.
- Category conversation: `run-20261122T123159Z-acc205bf`, final grade `grade-20261122T124523Z-371e3783`.
- Final sentinel run: `calibration-20261122T124524Z-1c63f7b4`.
- Persistence/accounting check: `phoenix_persistence_audit.json`.

The observed live runs predate the added harness-source hashes and shared trial parent span. Their manifests still pin runtime files, lockfile, cases, fixtures and captured outputs; the final harness also pins its own sources and groups each conversation's prompt spans under its trial. These additions were verified with scripted runtime and local collector tests.

Use [the README commands](../../README.md#independent-evaluation) for new runs and grading. Existing experiments can be inspected in [local Phoenix](http://127.0.0.1:6006). Versioned artifacts preserve earlier errors and exact judge/model settings.

Remaining work before release-quality conclusions: independent human reference review, adjudicated judge calibration, a sealed held-out family split, controlled BigQuery execution, and predeclared product-specific quality/latency margins. The source-checkout workflow is supported; standalone wheel execution still needs repository knowledge assets and lockfile metadata.

## End-to-end Phoenix workflow, 2026-11-22

`retail-eval run` now validates references, checks or starts local Phoenix, creates the
experiment and trace project before inference, executes each case, and publishes its captured
output and independent grades incrementally. Agent execution and answer, draft, and trajectory
judgments share one experiment cost ceiling and absolute deadline. Per-prompt allowances remain
independent within that ceiling. The evaluation guide documents the single-command entry point.

The new trajectory evaluator assesses tool selection, arguments, evidence use, recovery, and
progress from ordered observations. It uses event references, accepts different valid tool
sequences, and receives neither expected answers nor hidden reviewer evidence. Its ratings are
diagnostic and do not alter answer-level task success.

Verification passed **289 offline tests**, Ruff checks, formatting, and Pyright. Both opt-in
integration tests passed against the real local Phoenix service using scripted providers.
They verify early experiment links, incremental outputs and scores, and annotations attached to
the appropriate trial and prompt spans. Regression checks cover shared limits, startup failures,
incomplete judgments, immutable captures, and publication failures that must remain visible even
when later uploads succeed.

The real-model smoke execution `run-20261122T172426Z-4773837d` completed four cases and six user
turns using `gemini-3.8-flash`. Agent execution cost 0.493540 USD; initial independent grading cost
0.605928 USD, for 1.099468 USD combined at the configured rates. All four trials and their scores
were published to Phoenix. This execution used the ordinary one-command workflow with a 5 USD,
900-second ceiling.

Initial grading returned one PASS, one FAIL, and two ERROR results. A capture integration bug
exposed trajectory event IDs to the answer judge, which then cited them as business evidence.
The answer-judge input now excludes that metadata; frozen captures and strict source validation
remain intact. Original results are preserved under `grade-20261122T172426Z-bb453ea9`.

The category conversation also exposed a substantive issue: its first answer attributed growth
to “customer acquisition/activity” from aggregate quarterly customer counts. Those counts do
not establish acquisition or a causal mechanism. Correct numerical values did not make that
explanation supported, and the independent answer evaluator rejected it despite runtime approval.

The same six saved answers were regraded under `grade-20261122T173017Z-3b355e7f`, without rerunning
the agent. This grading cost 0.587964 USD and was published as a separate version. Answer-level
results were **three PASS and one FAIL**, with **57/57 required numerical facts correct** and all
six candidate judgments resolved. The unsupported acquisition explanation remained a failure.

Trajectory results were three PASS and one ERROR: for the category conversation, the judge
claimed complete coverage while omitting observed decision events from its assessment. Validation
rejected that claim instead of recording a pass. This remains an unresolved diagnostic judgment;
there was no selective retry to obtain a passing score. It illustrates why trajectory coverage
checks and human calibration are necessary. The original run and both grade versions remain
available for inspection.

Phoenix 22.0.1 streams completed spans when trace streaming is enabled. Its experiment table
does not auto-refresh results logged by an external SDK process; refresh that view to see newly
published outputs and scores. Neither view promises token-by-token output.
