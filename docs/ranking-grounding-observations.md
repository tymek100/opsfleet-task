# Ranking interpretation: prompt changes and regression observations

Date: 20 November 2026. These are selected development regressions, not a held-out benchmark or a guarantee of factual correctness.

These trials predate the [runtime-skills refactor](runtime-skills.md), which moved detailed analytical guidance into packaged skills. See [the subsequent skill trials](runtime-skills-test-observations.md) for the current implementation's measurements.

## Reported problem

A follow-up correctly identified no overlap between two displayed top-five lists, then attributed the difference to higher prices, lower unit volumes and brand-wide concentration in premium products. Revenue and distinct-customer counts do not establish unit prices or units sold. A top-five list also lacks the whole-brand denominator needed to establish revenue concentration.

## Implemented guidance

The application's [analyst prompt](../src/retail_agent/prompts/analyst.md) now requires explanations to distinguish measured facts, supported calculations and explicitly unverified hypotheses. It separates revenue, customers, orders, quantities and unit prices; requires a population total for concentration claims; and warns that product names and ranking membership cannot supply missing measurements. The agent can obtain more evidence or give a narrower supported answer. No fixed tool sequence or answer template was added.

The [reviewer prompt](../src/retail_agent/prompts/reviewer.md) applies the same distinctions to every factual explanation, including follow-ups. A price or unit-volume comparison needs supporting measurements identified in the grounding finding. Unsupported conclusions must be revised even if introduced by “suggests,” “likely” or “can.” Clearly labelled hypotheses with an explicit evidence gap remain acceptable. Prior approval is not independent evidence.

These are runtime instructions loaded by the chatbot. A developer-only skill file would not, by itself, change the chatbot's behavior. Restarting the CLI is a convenient way to begin a clean test conversation.

## Real-model conversation replays

Both runs used the configured `gemini-3.8-flash`, low analyst thinking, medium reviewer thinking, the read-only gateway to Google's public TheLook data, and temporary report storage. Each turn retained the USD 1 admission cap and 120-second deadline. Prompts and full answers, SQL, evidence, usage and prompt-file hashes are preserved in the linked captures.

| Run | Initial ranking / follow-up seconds | Manual assessment |
| --- | --- | --- |
| [First prompt revision](../evals/rewrite/runs/ranking-grounding-01/observations.md) | 22.748 / 13.868 | **Remaining false approval.** Follow-up still inferred higher/lower prices from revenue and customer counts. This failed attempt prompted the explicit one-customer-is-not-one-unit rule. |
| [Final prompt revision](../evals/rewrite/runs/ranking-grounding-02/observations.md) | 20.629 / 18.692 | The follow-up correctly compared revenue per customer and explicitly stated that unit sales and unit prices were unmeasured. It treated the price-versus-quantity explanation as unverified. |

The first run chose revenue as a secondary customer-ranking tie-break, producing two overlapping products. Its preface described ties incompletely, although a later footnote disclosed the revenue tie-break. The second run used product ID and produced zero overlap, matching the user's displayed selection. This difference is explained by the recorded SQL tie-breaking rules; it is not evidence of a data refresh.

For the second run, direct arithmetic over the captured evidence confirms five products per list, an empty product-ID intersection, and revenue-per-customer ranges of **108.00–259.99** for revenue leaders and **20.00–69.50** for customer leaders. These checks validate the follow-up against its evidence; they are not a separate warehouse audit. The follow-up used stored evidence and made no new warehouse query.

The corrected answer included:

> Because unit sales and individual price points are not measured here, whether this divergence stems from higher individual retail prices or multiple units purchased per buyer remains an unverified possibility.

Remaining presentation issues: the paragraph is dense, “driven by different dynamics” sounds more causal than necessary, and “realized selling prices” would be more precise than “retail prices.” The material unsupported price/volume conclusion was removed in this replay; prose quality is not perfect.

## Evaluator calibration

[Four regression cases](../evals/rewrite/ranking_grounding_cases.json) replay the previously recorded ranking evidence and prior answer. The first candidate reproduces the user's reported answer; the others are authored controls. Expected decisions and defect annotations are excluded from model input. No warehouse queries or report changes occur in this calibration.

| Candidate | Expected | Observed |
| --- | --- | --- |
| Exact reported price/volume/concentration explanation | Revise | Revise: absent unit-price and quantity evidence |
| Unsupported explanation hedged with “suggests” | Revise | Revise: absent unit-price, quantity and whole-brand denominator evidence |
| Supported concise overlap observation | Approve | Approve |
| Explicitly unverified, nonexclusive hypotheses with evidence gaps | Approve | Approve |

[Full evaluator findings](../evals/rewrite/runs/ranking-grounding-reviewer-01.json) record four model calls and zero queries. Timings were 15.108, 22.382, 8.276 and 10.475 seconds. All four expected decisions matched, and manual inspection confirmed the rejections identified real grounding defects. This tiny selected set does not estimate general false-accept or false-reject rates.

Offline verification: **49 relevant tests passed**, including three new tests that preserve captured evidence/context, verify that changing grading labels cannot change the model payload, and retain the original calibration suite. Existing reviewer, runtime, cancellation and budget tests also passed. Ruff check/format and `git diff --check` passed. These offline tests verify application behavior and evaluation-input isolation, not whether an LLM will always reason correctly.

## Reproduce

```bash
uv run --locked python scripts/calibrate_reviewer.py \
  --live --suite ranking_grounding --timeout 120 \
  --output evals/rewrite/runs/ranking-grounding-reviewer-local.json

uv run --locked python scripts/evaluate_rewrite.py \
  --live --backend bigquery --golden-bootstrap --case ranking_followup \
  --output evals/rewrite/runs/ranking-grounding-local
```

Use a new output path to preserve prior observations. The first command calls only the evaluator over recorded evidence; the second runs a fresh two-turn analyst conversation with public warehouse queries. The model remains autonomous in tool selection and answer composition. Prompt guidance and review reduce this failure mode but cannot make factual correctness certain.
