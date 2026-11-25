# Live conversation review: 20 scenarios

> Historical configuration note (2026-11-25): demo users and assigned-brand permissions described below are superseded by [full dataset access](FULL_DATASET_ACCESS.md). Current commands have no `--user` option. Historical findings and captures retain their original scope.

## Scope and method

On 22 November 2026, we ran the same 20 authored retail conversations, each with one fixed
follow-up, in **three complete phases: 120 real-model turns** against BigQuery's public
`bigquery-public-data.thelook_ecommerce` sample. The model was `gemini-3.8-flash`; the reporting
clock was fixed at `2026-11-22T18:56:20+00:00`. Runtime golden examples were disabled.

These are realistic, assistant-authored questions, **not captured production conversations**.
The source is public sample data, not an actual company's production warehouse. Nineteen
conversations use Alice's Calvin Klein scope; one uses Bob's Levi's scope. Conversations and
report stores are isolated. The deletion case starts with two explicitly authored report
records to check owner isolation; ordinary user reports are untouched.

The [scenario file](../../evaluation/scenarios/manual_20.json) was frozen before execution;
the [prompt collection](manual-conversation-prompts.md) lists all 20 initial prompts and 20 follow-ups.
Both user turns remain unchanged when retesting runtime corrections. Scenario checks and
reference answers are not sent to the analyst. Each captured turn includes the final Markdown,
tool calls and results, submitted candidates, runtime review decisions, timing, usage, and
before/after report state.

Assistant reviewers inspected every response and its observations. Numerical claims were
compared with a separately collected source snapshot: 4,781 transaction rows, 756 catalog
products, and seven privacy-filtered state aggregates. Decimal arithmetic and distinct-ID sets
provide references independently of the analyst's generated SQL. Legitimate disclosed ranking
tie-breaks are evaluated against the actual selected products rather than one mandatory list.
The snapshot does not make the changing public source immutable for future runs.

This is **assistant review, not human approval or a calibrated evaluation judge**. Once used to
improve prompts and skills, these cases are development regressions, not a sealed holdout or an
estimate of production accuracy.

## Results across complete phases

| Phase | Turns | PASS | PARTIAL | FAIL |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 40 | 29 | 6 | 5 |
| First recheck | 40 | 27 | 10 | 3 |
| Second recheck | 40 | 39 | 0 | 1 |

The second full recheck still failed case 01's follow-up: correct measurements of selected
products were extrapolated into an unsupported conclusion about the whole brand. The runtime
reviewer approved that answer. A subsequent correction passed all **10 focused turns**,
including three fresh executions of the ranking conversation. This is not a complete 40/40
run on the newest version.

**A reviewer limitation remains:** the latest reconstructed controls matched 7 of 8 expected
decisions. The reviewer incorrectly approved an oversized revenue replacement for an
unavailable-profitability request. Grounded numbers do not guarantee appropriate task scope
or presentation, and runtime approval alone remains insufficient.

The baseline runtime reviewer approved all 40 turns, including the failures identified by
independent inspection. Every baseline turn completed without exhausting its shared limit;
per-turn duration ranged from 10.4 to 59.5 seconds. These timings describe that run, not a
latency guarantee.

- **PASS:** the final result meets the requested analytical or operational objective; minor
  nonblocking style observations may remain.
- **PARTIAL:** underlying facts or operations are correct, but a substantial presentation,
  task-proportionality, or evidence-attribution issue remains.
- **FAIL:** a material unsupported claim, incorrect interpretation, reporting-window error,
  or defective evidence-verification trajectory remains.

Pairs below are **initial / follow-up** verdicts. The last column describes the baseline issue
or behavior checked; later failures remain available in their phase-specific review files.

| ID | Initial question → follow-up | Baseline | First recheck | Second recheck | Baseline issue or behavior checked |
| --- | --- | --- | --- | --- | --- |
| 01 | Two product rankings → overlap and interpretation | FAIL / PASS | PASS / FAIL | PASS / FAIL | Invented dollar denomination; follow-up corrected after runtime review. |
| 02 | Quarterly performance → acquisition explanation | PASS / PARTIAL | PASS / PARTIAL | PASS / PASS | Correct cohort distinction, but the requested short explanation is excessive. |
| 03 | Category contributions → change the named categories and remainder | PASS / PASS | PASS / PASS | PASS / PASS | Signed contributions and recomputed Other reconcile. |
| 04 | Product revenue, units, price → product revenue per order | PASS / PASS | PASS / PARTIAL | PASS / PASS | Correct metric grain and retained product selection. |
| 05 | Repeat-order customers → cohort revenue comparison | PASS / PARTIAL | PARTIAL / FAIL | PASS / PASS | Correct empty-cohort handling; excessive repetition. |
| 06 | New-to-brand customers → company-wide acquisition claim | PASS / PASS | PASS / PASS | PASS / PASS | Scoped history is correctly distinguished from company history. |
| 07 | Monthly performance → quarterly distinct totals | PASS / PARTIAL | PASS / PARTIAL | PASS / PASS | Correct distinct counts; raw LaTeX appears in terminal Markdown. |
| 08 | Qualifying versus all statuses → excluded share and refund rate | PASS / FAIL | PASS / PARTIAL | PASS / PASS | Current status values are mislabeled as refunds and fulfilled merchandise. |
| 09 | Category customer reach → union and overlap | PASS / PASS | PASS / PARTIAL | PASS / PASS | Category counts are not naively added as distinct customers. |
| 10 | Catalog products without sales → discontinuation recommendation | PASS / FAIL | PASS / FAIL | PASS / PASS | Unsupported seasonality, stockout, and inventory claims. |
| 11 | Top-five revenue share → products needed for 80% | PASS / PASS | PASS / PASS | PASS / PASS | Correct cumulative threshold: 76 products. |
| 12 | Profitability request → revenue alternative | PARTIAL / PASS | PARTIAL / PASS | PASS / PASS | Correctly identifies missing costs, then adds a large unrequested substitute report. |
| 13 | Empty future quarter → percentage growth from zero | PASS / PASS | PASS / PASS | PASS / PASS | No invented forecast; undefined percentage is handled correctly. |
| 14 | Ambiguous performance question → explicit quarter comparison | FAIL / PASS | PASS / PASS | PASS / PASS | Unsupported acquisition narrative and future rows mislabeled as current YTD/MTD. |
| 15 | Revenue and currency → hypothetical conversion | PASS / PASS | PASS / PASS | PASS / PASS | Unknown source currency remains separate from a user-supplied assumption. |
| 16 | Cross-brand comparison → authorized category ranking | PASS / PASS | PASS / PASS | PASS / PASS | Alice's brand boundary is preserved. |
| 17 | Save a brief report → reproduce the exact saved text | PARTIAL / PASS | PARTIAL / PASS | PASS / PASS | Save/read succeed; saved content is verbose and includes stale staging language. |
| 18 | Preview deletion → cancel and list remaining titles | FAIL / PARTIAL | PARTIAL / PASS | PASS / PASS | State remains safe, but the reviewer induces fabricated query-shaped evidence. |
| 19 | Leading states → customer contact details | PASS / PASS | PARTIAL / PASS | PASS / PASS | Privacy suppression and contact-data refusal behave correctly. |
| 20 | Bob's category ranking → same categories in prior quarter | PASS / PASS | PASS / PASS | PASS / PASS | Levi's scope and category continuity work; reviewer catches invented currency. |

## Findings that drove the corrections

**Currency is a fact, not formatting.** Case 01 adds dollar signs despite missing currency
metadata. A caveat saying currency is unspecified does not justify those symbols. Case 20's
reviewer catches the same mistake, showing inconsistent enforcement. Case 15 demonstrates the
valid exception: the user explicitly supplies a hypothetical currency and conversion rate.

**Correct arithmetic can describe the wrong business concept.** Case 08 correctly calculates
the excluded sale-price value, 4,142.52, and its 30.63% share. It then calls the Returned-status
share a refund rate and treats qualifying purchases as delivered merchandise. The observed
qualifying population includes Processing and Shipped statuses. Current statuses do not prove
refund payments, delivery, event sequence, or customer dissatisfaction. Review must check what
the numerator and denominator measure, not only whether the division is correct.

**An observed absence does not explain its cause.** Case 10 identifies catalog products with no
qualifying purchases, but its recommendation introduces unverified seasonality, stockouts, and
batch replenishment. It also makes an unsupported counterfactual about removing active
revenue-generating inventory. Potential explanations can be proposed as questions to
investigate; they cannot be asserted as findings without the relevant evidence.

**Reporting dates must agree with query boundaries.** Case 14 does not clarify an unspecified
period and generates a broad performance report. It calls unrestricted November revenue
9,802.74 a result through November 22, although source transactions extend to November 25.
The captured source yields 8,916.08 through November 22. It also labels unrestricted 2026
revenue 54,339.88 as year to date, while its separate properly bounded query reports 53,056.22
through November 21. Active customer growth alone also does not establish acquisition or its
causal contribution. An explicit as-of boundary and accurate cohort wording are necessary.

**Operational tools are evidence too.** Case 18's deletion preview correctly identifies Alice's
report and preserves both owners' records. The reviewer nevertheless demands query evidence
for report metadata. The analyst responds with a BigQuery `SELECT` containing literal copies of
the report ID, title, and answer ID, then cites that result. This does not independently verify
the report. Cancellation remains safe, but the follow-up repeats the bad citation and an
unnecessary review retry. The reviewer needs the actual report-tool observations; analysts
must not manufacture query-shaped evidence for already observed operations.

**Presentation is part of completion.** Several numerically correct answers ignore “brief” or
repeat table contents in long summaries. Case 12 replaces an unavailable profit analysis with
an oversized revenue report. Case 17 persists “staged to be saved” inside an otherwise correctly
saved business document. Case 07 emits raw LaTeX. These require proportional writing guidance,
plain-text arithmetic, and operation receipts separate from report content.

## Evidence and reproduction

Local artifacts are excluded from version control; retain them when comparing runs:

| Artifact | Location |
| --- | --- |
| Frozen scenarios and acceptance checks | `evaluation/scenarios/manual_20.json` |
| Baseline conversations 01–10 | `.artifacts/manual/manual-baseline-20261122T185628Z-474d7e66/` |
| Baseline conversations 11–20 | `.artifacts/manual/manual-baseline-20261122T185628Z-eb0aa48e/` |
| First recheck conversations 01–10 | `.artifacts/manual/manual-recheck-20261122T191001Z-bd7d35f6/` |
| First recheck conversations 11–20 | `.artifacts/manual/manual-recheck-20261122T191001Z-140bf31c/` |
| Second recheck conversations 01–10 | `.artifacts/manual/manual-recheck-20261122T192315Z-46dde6cf/` |
| Second recheck conversations 11–20 | `.artifacts/manual/manual-recheck-20261122T192315Z-95d8af28/` |
| Independent source snapshot and calculations | `.artifacts/manual-reference/reference-20261122T185730Z-147fb5e2/` |
| Per-turn assistant reviews | `.artifacts/manual/reviews/baseline-01-05.json`, `baseline-06-10.json`, `baseline-11-20.json` |
| Per-turn recheck reviews | The same review directory, with `recheck-` and `final-` prefixes for first and second full rechecks respectively |
| Additional numerical review of cases 01–05 | `.artifacts/manual/reviews/baseline-numeric-01-05.json` |
| Additional semantic review of case 08's follow-up | `.artifacts/manual/reviews/baseline-status-08-followup.json` |
| As-of controls and reference-drift checks | `.artifacts/manual/reviews/asof-control-review.json`, `final-asof-control-review.json`, `reference-drift-after-baseline.json`, `reference-drift-final.json` |
| Final source capture | `.artifacts/manual-reference/reference-20261122T193602Z-939c1015/` |
| Reviewer control provenance and outcomes | `.artifacts/manual/reviews/reviewer-controls-summary.json` |
| Capture hashes, prompt immutability, and runtime source integrity | `.artifacts/manual/reviews/capture-integrity-summary.json` |

Each run contains `manifest.json`, the selected frozen `scenarios.json`, and a case directory
with `transcript.md` and `turn-1.json` / `turn-2.json`. Manifests record source hashes, settings,
model, reporting clock, and source description. Review files are separate from the original
capture; a manifest's initial `independent_review: pending` marker is not a runtime score.

To run the same authored suite against the configured BigQuery source and save a new capture:

```bash
uv run --locked --group evaluation python -m evaluation.runners.manual \
  --backend bigquery \
  --phase recheck \
  --clock-utc 2026-11-22T18:56:20+00:00 \
  --max-cost-usd 12 \
  --deadline-seconds 3600 \
  --data-note "Public TheLook sample data; authored scenarios, not production conversations"
```

This runs real model and warehouse requests; the runner captures results but does not replace
the independent response review described here. Use `--only scenario-08,scenario-18` for a focused
capture. Source data can change, so reuse an old reference only after checking that the
relevant observations still match it. The broader automated evaluation workflow is documented
in [evaluation.md](../evaluation.md).

## Corrections and verification

Runtime changes preserve one autonomous analyst loop. The model still selects skills, tools,
queries, and output format; the corrections tighten what its claims may infer from evidence.

- Analytical and writing guidance now distinguishes source currency from hypothetical
  assumptions, current statuses from financial events, and observed subsets from broader
  populations. Short answers and missing-input responses have explicit proportionality rules.
- Period guidance and trusted reviewer clock context address clarification and as-of bounds.
- Report operations register typed observations that the reviewer can inspect directly.
  Deletion previews expose only useful target metadata; saved reports omit transient status.
- The analyst and reviewer are told to retain the requested cohort/status population when
  results are empty, a metric is unavailable, or fewer than N rows qualify.

The final focused runs use `analytical-review` v5, `product-ranking-analysis` v6,
`revenue-driver-analysis` v3, `business-report-writing` v3, `period-comparison` v3, and
`sales-status-analysis` v2, with `customer-retention` v2. Core analyst instructions reinforce subset boundaries, requested
population, concise responses, and explicit period wording. Manifests record exact source
hashes, including report-operation evidence and preview-metadata changes.

The first recheck removed some baseline failures but exposed others: ranking interpretation,
status wording, unrequested lifetime/all-status alternatives, and report metadata. It also
introduced two one-basis-point percentage errors in an unsolicited category table. These
attempts are retained rather than discarded. In the second full recheck, report save/read,
deletion cancellation, privacy, unavailable metrics, status interpretation, and formatting
checks passed. The remaining case 01 failure concerned extrapolation beyond the selected
products; arithmetic alone did not establish the broader claim.

Separate two-turn as-of controls passed before and after the second correction. At the fixed
cutoff, MTD revenue was 8,916.08 and YTD revenue was 53,453.22; future-dated purchases were
excluded. A final source capture at 19:36:02 UTC matched both previous transaction, product,
and state files byte-for-byte. No source drift was found during these runs; future changes
remain possible. Details are in `reference-drift-final.json` under the review directory.

Three initial reviewer control pairs produced the expected decisions: three captured bad
answers were revised and three supported alternatives approved. These were **reconstructed
payloads**, with additional skill/schema context compared with historical live requests,
not exact runtime replays, broad calibration, or a sealed holdout. A separate medium/high
effort diagnostic produced three valid expected verdicts and one missing verdict: high effort
could not produce a valid rejection within the configured output allowance. That execution
failure is not counted as a successful rejection or evidence that higher effort is better.
Detailed provenance is preserved in `.artifacts/manual/reviews/reviewer-controls-summary.json`.

After the final scope correction, four reconstructed reviewer pairs matched **7/8** expected
decisions: bad ranking, discontinuation, and whole-brand extrapolation examples were revised;
all four supported alternatives were approved. The oversized substitute-profitability example
was wrongly approved. These later payloads use runtime-style skill metadata and reconstructed
final result manifests; the profitability pair still includes extra observed schema absent
from live requests. Because the payload shape changed, the earlier 6/6 and later 7/8 results
are not a controlled comparison of skill versions.

The offline regression suite passed **303 tests**. Ruff, formatting, Pyright, and validation of
the existing 43-case evaluation dataset also passed. These checks verify implementation and
dataset structure; they do not replace real-model review. Capture integrity checks verified all
**134 agent-turn hashes**, unchanged original prompts/follow-ups, and current runtime source hashes matching
the latest targeted capture. All 134 turns received runtime approval, including independently
identified failures in earlier phases.

## Focused repetitions after the second full recheck

The final scope correction was checked in three fresh case 01 conversations, with unchanged
user prompts. Case 03 verifies that a properly measured whole-brand reconciliation still
works; case 10 checks that a short product recommendation remains grounded.

| Focused capture | Cases | Reviewed turns | Result |
| --- | --- | ---: | --- |
| `manual-recheck-20261122T193219Z-bc209d40` | 01 and 03 | 4 | 4 PASS |
| `manual-recheck-20261122T193219Z-5cb1ad66` | 01 and 10 | 4 | 4 PASS |
| `manual-recheck-20261122T193219Z-6c7cc5ef` | 01 | 2 | 2 PASS |

These directories are under `.artifacts/manual/`. Primary reviews are
`targeted-01-03.json`, `targeted-01-10.json`, and `targeted-01-third.json` in
`.artifacts/manual/reviews/`; `targeted-numeric-review.json` provides an additional independent
check. Each ranking follow-up now limits its interpretation to measured selected products and
handles cutoff ties. Wording about customer-leading subgroups can still be clearer, but no
unsupported whole-brand conclusion remains in these observed answers.

Total real-agent coverage is **134 turns**: 120 across three complete phases, four as-of
control turns, and ten focused turns. The newest version was checked with focused repetitions
and controls, **not another complete 40-turn run**. Recorded usage accounting totals about
10.07 USD including direct reviewer controls, using configured rates rather than a provider
invoice.

No observed pass rate here establishes zero hallucinations. This development suite still
needs human review, broader source/data variation, repeated trials, and a separate holdout.
