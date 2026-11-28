# Summary quality: content selection and reviewer calibration

Date: 26 November 2026. Status: implemented, tested and deployed to the four local Docker agents.

## Result

The original problem was poor information selection: the agent compressed a report's opening metrics instead of answering the business question behind it. Shorter instructions and a sentence limit alone did not solve that problem. The reviewer also approved the dense answer because it checked facts and sentence count without adequately assessing selection.

The revised instructions make the source question explicit: a priority summary leads with the priorities and their measured reasons, while a numerical comparison retains the requested figures. A calibrated reviewer rejects the known dense answer and requests a specific revision. The model and execution architecture remain unchanged.

Three runs of the original report, including a paraphrased request, now lead with supported priorities and retain a material limitation. One exact result:

> Prioritize Outerwear & Coats and Jeans for their large shares of recorded inventory cost, alongside Suits for having the highest ratio of modeled stock to historical sales. The report highlights these category concentrations, but modeled stock and past Q1 sales do not confirm physical shelf availability or current demand.

This 49-word answer retains the decision-relevant findings without the original inventory of totals, percentages and ratios. It does not diagnose overstock, infer current demand, or turn recorded cost into cash. The wording can still vary; these small experiments establish a correction to the observed case, not a universal reliability guarantee.

This work continues the [earlier partial result](2026-11-26-prompt-consolidation.md). That report remains an accurate historical record.

## Research and hypotheses

| Hypothesis | Guidance and experiment |
| --- | --- |
| More reasoning might improve selection | Gemini 3.8 supports thinking levels; tested high analyst reasoning. Temperature, top-p and top-k are ignored for this model, so they are not useful tuning controls. [Google model guidance](https://aistudio.google.com/docs/whats-new-gemini-3.8). |
| Clearer selection instructions and varied examples might suffice | Consolidate context and use relevant, diverse examples rather than accumulating exceptions. Tested an initial version, a repeat, then stronger purpose-based selection. [Anthropic context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents), [prompting guidance](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices). |
| An isolated writing call might avoid analytical context | Tested one focused writer with the frozen report. It repeated unsupported risk language and was not adopted. Context reduction alone did not ensure grounded selection. |
| The reviewer needs calibration too | Test against a known bad answer, a good answer and unsupported claims; inspect actual outputs rather than treating approval as proof of quality. [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices). |
| Output limits may confound review results | Thinking consumes the output allowance. One large reviewer control truncated; it is recorded as an invalid test, not successful semantic rejection. [Google token-limit guidance](https://aistudio.google.com/docs/thinking#token-limits). |

The existing Flash model solved the observed selection problem at the current reasoning settings. Another model comparison would have added cost without resolving an outstanding requirement, so it was not run. The [previous Flash/Neon comparison](2026-11-26-flash-neon-summary-comparison.md) remains separate.

## Implementation

- [`runtime/answer_style.md`](../../src/retail_insight/runtime/answer_style.md) tells every analyst to recover the source question, select the main answer, and preserve the limitation that changes its interpretation. It distinguishes priority summaries from explicitly requested numerical comparisons. Three fictional examples teach selection, numerical completeness and missing-data explanations.
- [`analytical-review`, version 10](../../src/retail_insight/review/skills/analytical-review/SKILL.md), requires a substantive presentation finding about selection and density. A fictional positive/negative pair distinguishes a useful priority summary from a correct but irrelevant list of metrics. The reviewer still checks coverage, grounding, metrics and authorized operations.
- [`business-report-writing`, version 6](../../src/retail_insight/runtime/skills/library/business-report-writing/SKILL.md), reinforces selecting the answer to the report's question rather than its introduction or largest totals.

The shared style is always included through the existing prompt assembly, for analysts and reviewer; it does not depend on the analyst loading an optional skill. There is no additional writer agent, fixed answer template, sentence-count gate, model router or mandatory new model call. Production settings remain Gemini 3.8 Flash, analyst **low**, reviewer **medium**, with output allowances of **4,096 / 2,048** tokens.

## Controlled experiments

The original business question was:

> Compare our Q1 2026 sales with current inventory. Which categories deserve a closer look?

The follow-up was:

> summarize this report in 2 sentences

All original-case experiments used the same saved report from the earlier model comparison, with its public TheLook data and 26 November cutoff. The real coordinator class, ADK loop, context tools, completion tool and reviewer ran in isolated sessions. No BigQuery query, remote specialist or Maps call was allowed. Synthetic held-out reports tested transfer to other summary tasks; they were not runtime knowledge or writing examples.

Before testing, acceptance required priority-first selection, measured reasons, readable prose and the modeled-stock/historical-sales limitation. Requested numeric facts must survive. Word count was diagnostic, not the success criterion. Every output was inspected by the coding assistant against its source; this is not an independent human evaluation or a calibrated benchmark score.

| Experiment | Observation | Estimated USD |
| --- | --- | ---: |
| Higher analyst reasoning, earlier instructions | Good selection in one run; abstract wording remained. More expensive than the selected low-reasoning runs. | 0.030099 |
| Initial selection instructions, low reasoning | First result selected priorities correctly. | 0.023681 |
| Focused writer, low reasoning | Failed: repeated unproven replenishment-risk language and blurred reasons across categories. | 0.001692 |
| Initial instructions, repeat | Failed selection: opened with 310,553 units and a stock/sales ratio again. | 0.019733 |
| Earlier reviewer, dense-answer control | Incorrect approval at medium reasoning. | 0.023562 |
| Earlier reviewer, dense-answer control, high reasoning | Incorrect approval again. More reasoning did not repair the quality criterion. | 0.026281 |
| Calibrated reviewer, oversized control | Invalid: output truncation followed by context-limit failure. Included in cost; not counted as semantic success. | 0.027356 |
| Final selection instructions, original request | Pass: priorities, reasons and material caveat; 43 words. | 0.018292 |
| Calibrated reviewer, compact source-report control | Correctly rejected dense answer; 4,096-token experimental allowance. | 0.009122 |
| Final instructions, repeat | Pass: priorities and caveat; 49 words. | 0.014239 |
| Held-out numerical comparison | Pass: all four requested values retained; no invented currency or cause. | 0.016116 |
| Held-out missing costs | Partial: correct inability to rank profitability, but omitted the requested test criterion's next step and retained an unnecessary revenue figure. | 0.015083 |
| Held-out distribution data quality | Pass: relevant attribution/cost issues; no invented physical losses. | 0.016508 |
| Calibrated reviewer, production output limit | Correctly rejected dense answer at the unchanged 2,048-token allowance. | 0.009092 |
| Calibrated reviewer, good-answer control | Correct approval at production settings. | 0.006844 |
| Calibrated reviewer, hallucination control | Correctly rejected cash, confirmed-overstock, weak-demand and physical-inventory claims. | 0.007919 |
| Final instructions, paraphrased request | Pass: priority-first answer and verification caveat; 48 words. | 0.019223 |

The compact review controls supplied the source report as a historical observation, matching a summary's evidence needs. They do not independently validate the report's SQL or prove every upstream fact correct. Normal agent experiments used the actual context and completion paths. The oversized control was a harness construction problem, not evidence that the production output allowance should be increased.

The final summary runs met the full recorded criteria in **five of six cases**: three original-source runs, numerical comparison and distribution. The missing-cost case was partial. All three final reviewer controls behaved as expected. Neither result is a population-level accuracy estimate.

## Transfer examples and remaining limitation

Numerical comparison, explicitly requesting both quarters' revenue and order counts:

> Between Q1 and Q2, qualifying revenue rose from 120,000 to 132,000 as orders increased from 2,000 to 2,200. Both metrics grew by 10% with an unchanged average order value, though these aggregates do not explain what drove the increase.

Distribution data quality:

> Prioritize reconciling the 10,000 modeled units with unknown center attribution and investigating Beta's missing item costs, which affect 30% of its recorded units. The report emphasizes that these reflect inventory data-completeness issues rather than verified physical losses or facility errors.

Missing costs:

> The report cannot determine the most profitable category or rank investments because item costs and operating expenses are missing. While it records 134,000 in qualifying sales revenue led by Jackets and Swim, that revenue cannot be used as a proxy for profit.

The last answer preserves the central limitation and avoids inventing a profitability winner, but an explicit next step to obtain cost inputs would be more useful than the revenue figure. Its prewritten criterion required that next step, so it is recorded as partial rather than silently relaxing the criterion. No further prompt changes were made after these held-out results.

## Cost and reproducibility

This investigation made **42 metered model calls across 17 experiments**. Together with the preceding three summary runs, the cumulative scope is **53 calls**. No unsettled charge remains.

| Cost scope | Estimated provider USD | Conservative accounting USD |
| --- | ---: | ---: |
| Previous three summary runs | 0.056003 | 0.155794 |
| This investigation, including failed controls | 0.284838 | 0.804100 |
| **Cumulative summary work** | **0.340841** | **0.959894** |

The provider estimate prices all input at $0.75 and output plus thinking at $3.75 per million tokens, without deducting cache discounts. It is an estimate from returned usage, not a billing invoice. [Google pricing](https://aistudio.google.com/docs/pricing#gemini-3.8-flash).

At the indicative 4.0785 PLN/USD rate, the cumulative estimate is **1.39 PLN before tax**. Even the conservative accounting is **3.91 PLN**, or **4.82 PLN with a 23% tax buffer**, below the user's 10 PLN ceiling. [Exchange-rate quote](https://www.money.pl/pieniadze/ile-kosztuje-dolar-kurs-dolara-do-zlotego-pln-usd-26-11-2026-7355076514691168a.html).

A persisted ledger enforced a **$1.50 cumulative conservative admission cap**, including previous tests. Each request reserved its full input-byte estimate and output allowance at $2/$12 rates before execution; retries and failures remained charged or reserved until usage was known. The prior Flash/Neon report-generation comparison predates this summary-improvement budget and is accounted for separately in its own report.

[Audit data](2026-11-26-summary-quality-data.json) contains frozen report text, held-out inputs and criteria, all final candidate texts, reviewer decisions, model usage and prompt snapshots. Detailed local traces, experimental prompt variants and the guarded harness remain in `.artifacts/summary-quality/`. These experiments do not create new runtime knowledge or modify evaluation references.

## Verification and deployment

**650 offline tests passed; 5 live/Phoenix tests were deselected.** Ruff and `git diff --check` passed. Offline tests verify application contracts and prompt integration; the live experiments above assess writing and grounding on the recorded examples. No full paid evaluation suite was run.

All four agent images were rebuilt and their idle containers recreated using the existing Compose environment. The running containers' shared style, reviewer rubric and writing-skill hashes match the tested files. All four agent-card endpoints and the GUI health endpoint returned HTTP 200. The GUI remains available at `http://127.0.0.1:8080`; existing conversation and report volumes were preserved. No additional paid inference was used for deployment checks.

Weekly Codex usage percentage is not exposed by available tools, so the requested 82%-to-60% stopping threshold could not be enforced. Work was bounded to the experiments above and stopped once the original issue passed repeated checks; no claim about remaining weekly usage is made.
