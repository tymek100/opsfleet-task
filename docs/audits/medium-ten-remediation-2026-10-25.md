# Remediation of the ten-question evaluation

Date: 2026-10-25. This follow-up addresses the findings in the [initial evaluation](medium-ten-questions-2026-10-25.md); that report remains a historical record.

## Changes

- **Complete rankings:** “number of distinct customers” and “number of unique customers” create a separate customer-ranking requirement. Fetching both datasets is insufficient: both required rankings must appear in the validated answer.
- **Readable churn:** show eligible and inactive customers alongside percentage shares and a percentage-point change. Display small movements without rounding both snapshots to the same value. If the active population count stays unchanged, explain the denominator effect. An increase alone does not establish a spike or its cause.
- **Better analytical hypotheses:** reject a product-mix hypothesis supported only by individual-product comparisons or product rankings. Do not describe a single-period comparison as a change across periods.
- **Clear empty results and permissions:** explain that no qualifying sales were found; do not turn NULL revenue into zero. Out-of-scope brand requests receive an explicit access explanation. Tool-level authorization errors terminate the request rather than invite model repair or substitution of an authorized brand.
- **Business formatting:** consistent two-decimal monetary and basket values; concise proposed-action dates and baselines. Calculation boundaries remain in the evidence and diagnostics.
- **More useful model prose:** allow evidence-bound references to names, dates and metric values. The model writes the connective text; code supplies reference values. Unknown references, uncited values and row labels without supporting metrics from that same row are rejected. A separate model review checks the resolved prose for support, relevance and safety. In particular, suppressed state cohorts cannot establish overall geographic concentration, and filtered customer histories cannot establish absence of all purchases.
- **Avoid unnecessary calls:** plain scalar answers and empty sales results skip optional commentary. Requests explicitly asking for interpretation, comparisons or reports can still receive it. Empty results always skip it.

This is a hybrid presentation layer: deterministic tables and calculations, optional reviewed model interpretation. The semantic reviewer remains probabilistic; it is not a proof that prose is correct. Optional-layer failure preserves verified findings. No query permissions, PII controls, model thinking level or budget limits were relaxed.

## Verification

Regression checks cover dual-ranking completeness, reference binding and substitution, same-row label support, empty results, small churn changes, incompatible hypotheses, access denials and skipped commentary calls. The live follow-up uses the same ten questions and `gemini-3.8-flash` with medium thinking. Independent BigQuery queries use separate SQL, not the application compiler. Full rendered responses are in the [follow-up transcripts](medium-ten-remediation-transcripts-2026-10-25.md).

### Automated checks

- Ruff lint/format checks and strict Pyright pass.
- Offline suite: **157 passed**, three live-marked tests deselected. The separate live follow-up below exercises real providers.
- `git diff --check` passes.

### Live results

| Case | Outcome | Seconds | Commentary |
| --- | --- | ---: | --- |
| 1 | validated | 47.18 | Included |
| 2 | validated | 45.44 | Included |
| 3 | validated | 43.53 | Included |
| 4 | validated | 49.34 | Included |
| 5 | validated | 46.08 | Included |
| 6 | validated | 54.84 | Included |
| 7 | validated | 17.63 | Not included |
| 8 | validated | 24.12 | Not included |
| 9 | Expected access denial; no query | 6.52 | Not included |
| 10 | validated | 75.57 | Not included |

Independent read-only BigQuery SQL checked **179 metric/NULL cells**, plus row identifiers and ordering, with **no mismatches**. Public data can change; this is a dated observation.

Measured estimated list cost: **$0.237048** for the ten questions; independent oracle queries add **$0.002027**. Median response time: **45.76 seconds**. These use the dated price assumptions in the [earlier evaluation](medium-ten-questions-2026-10-25.md), include thinking tokens, and are not an invoice. Reservations shown by the application remain conservative caps rather than actual spend.

The nine analytical answers passed validation; the tenth outcome was the expected permission refusal. Commentary was accepted for six answers, intentionally skipped for the scalar and empty-result cases, and rejected by semantic review for the customer follow-up. That follow-up still returned the correct verified ranking and retained the January–June period from case 2. No provider retry or missing usage was recorded in this run.

### Limits and remaining tradeoffs

The optional prose is reviewed by a model, so deterministic correctness of the underlying metrics does not guarantee every interpretation is correct. It can still be repetitive or stylistically awkward. The 13-second model-call pacing remains enabled; this follow-up does not establish that all simple questions meet the production latency target. Public-data historical values can change with source updates. No saved reports were created or deleted by this evaluation.
