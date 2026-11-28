# Prompt consolidation and summary experiment

Date: 26 November 2026. Status: implemented and tested in the real ADK coordinator loop; existing Docker services were not rebuilt or restarted.

Follow-up: [content selection and reviewer calibration](2026-11-26-summary-quality-resolution.md) records the subsequent fix, repeated checks, remaining limitations and cumulative summary-work cost. The results below describe the earlier experiment.

## Result

Runtime prompt and skill text decreased from **11,149 to 5,534 whitespace-delimited words (50.4%)**, including the new examples and unchanged trust policy. The final live summary decreased from **69 to 54 words** and preserved the distinction between modeled stock, physical availability and current demand.

This was a **modest improvement**, not a complete style fix. The final answer still opens with several totals despite guidance to lead with the report's priorities. It retains two cost-concentration priorities but omits the source's highest/lowest-ratio contrast. All three runtime reviews approved presentation, so reviewer approval is not evidence that the writing problem is solved.

## Implementation

- All four agents and the retail CLI share runtime protocol and [answer-style guidance](../../src/retail_insight/runtime/answer_style.md). Three fictional examples show selecting priorities, retaining requested figures and explaining missing data. Examples are always present; no retrieval call or runtime knowledge store was added.
- Role prompts retain capabilities and essential domain constraints. Eight analytical skills retain measurement methods and edge cases without repeated writing instructions; all changed skill versions were incremented.
- The writing skill now addresses report-specific choices. The mandatory reviewer rubric distinguishes summarization from repeating the original report and checks information density as well as format.
- Trust policy, enforced tool/authorization boundaries, agent loop and completion protocol remain intact. Independent offline evaluation prompts and references were deliberately unchanged, avoiding a simultaneous change to the external grading standard.
- Ignored temperature settings were removed from active runtime and evaluation configurations in the preceding cleanup. This experiment used the resulting configuration throughout.

Assembled coordinator instructions decreased from 1,432 to 1,249 words; its reviewer, including domain guidance, decreased from 3,629 to 2,183. Retail CLI instructions increased from 1,128 to 1,192 because the shared runtime and examples now reach that path too. Source-text reduction is not a claim that every individual request is shorter.

## Small live experiment

The exact request was:

> summarize this report in 2 sentences

All variants received the same frozen report and its 15 evidence artifacts from the previous [model comparison](2026-11-26-flash-neon-summary-comparison.md). The source uses public TheLook data, Q1 2026 sales and the 26 November inventory cutoff. No report was regenerated.

The production coordinator class, context tools, ADK loop, completion tool and reviewer ran locally with isolated report stores. A2A transport and specialist execution were not exercised; external delegation was disabled. Each variant started with the same prior report and evidence, with no preceding variant's output in its conversation.

| Setting | Value |
| --- | --- |
| Model, analyst and reviewer | Gemini 3.8 Flash |
| Analyst / reviewer thinking | low / medium, matching current configuration |
| Analyst / reviewer output allowance | 4,096 / 2,048 tokens; unchanged |
| Per-variant admission cap | $0.65 |
| Cumulative experiment ceiling | $1.30 |
| Live summary runs | 3: baseline, consolidated, one refinement |
| Model calls, including reviewers | 11 |
| New BigQuery queries | 0 |
| Additional independent LLM judges | 0 |

The baseline used a pre-edit prompt and skill snapshot. The first consolidated result still foregrounded totals, so one fictional example was changed to show selecting priorities and the summary instruction was clarified. The final result is a development retest of the same case, not a held-out evaluation. Sequential single samples do not establish statistical reliability, generalization or causality.

## Exact outputs and manual assessment

### Before

> Across all 26 categories, current modeled unsold inventory stands at 310,553 units with an unstated-currency cost basis of 8,908,773.88, representing 31.76 times total Q1 2026 qualifying sales volume of 9,777 units (585,692.93 revenue). The report prioritizes Jeans and Outerwear & Coats due to high inventory cost concentration (12.88% and 11.40% of total cost, respectively), alongside Suits and Dresses for having the catalog's highest (40.72) and lowest (28.25) modeled-stock-to-sales ratios.

The 69-word answer reproduces totals, percentages and ratios. It omits the explicit physical-availability/current-demand limitation and uses awkward wording such as “unstated-currency cost basis.”

### Consolidated instructions, first attempt

> Across all 26 categories, current modeled unsold inventory stands at 310,553 units with an 8,908,773.88 recorded cost basis, representing 31.76 times total Q1 2026 sales volume of 9,777 units. Categories such as Suits and Outerwear & Coats show the highest modeled stock-to-sales ratios, though these figures reflect historical benchmarks and modeled records rather than verified physical availability or current demand.

This 60-word answer restores the material limitation but still opens with a dense list of totals.

### Final refinement

> Modeled unsold inventory stands at 310,553 units with an 8.91 million recorded cost basis, representing 31.76 times total Q1 2026 sales volume across all 26 categories. Jeans and Outerwear & Coats warrant the closest review due to high cost concentration, though modeled stock figures do not verify physical shelf availability or reflect current demand.

This 54-word answer is shorter and retains the main limitation. The 8.91 million amount rounds the source's recorded cost of 8,908,773.88 appropriately, with no invented currency. Jeans and Outerwear & Coats are supported cost-concentration priorities. It still leads with aggregate numbers, so the desired prioritization style remains inconsistent.

No exact wording, word-count threshold or example facts are imposed in application code. These are manually assessed outputs, not proof that hallucinations or verbosity are eliminated.

## Cost

| Variant | Model calls | Input tokens | Output tokens | Thinking tokens | Time | Estimated USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Before | 3 | 17,286 | 571 | 680 | 16.65 s | 0.017656 |
| Consolidated | 4 | 20,571 | 548 | 512 | 16.86 s | 0.019403 |
| Refined | 4 | 20,684 | 486 | 429 | 15.86 s | 0.018944 |

Total estimate: **$0.0560, approximately 0.23 PLN before taxes/credits**. This prices all input at the uncached rate; any implicit cache discount would lower the estimate. Every call returned usable metering; no unsettled reservation remained. The application's more conservative $2/$12 admission rates accounted for **$0.155794** across all three runs, also far below the task's 10 PLN ceiling.

Pricing: $0.75 per million input tokens and $3.75 per million output/thinking tokens, applicable through December 2026. [Google pricing](https://aistudio.google.com/docs/pricing#gemini-3.8-flash). PLN conversion uses the indicative 26 November quote of 4.0785 PLN/USD, not a guaranteed card/billing rate. [Exchange-rate quote](https://www.money.pl/pieniadze/ile-kosztuje-dolar-kurs-dolara-do-zlotego-pln-usd-26-11-2026-7355076514691168a.html).

The refined run was admitted against the prior settled $0.103446 plus its maximum $0.65 allowance, preserving the cumulative $1.30 ceiling. Artifacts and before-edit snapshots remain under `.artifacts/prompt-simplification/`; marker files prevent accidental reruns of the paid script.

## Validation and limits

**650 offline tests passed, 5 live/Phoenix tests deselected**; Ruff and `git diff --check` passed. A new regression test checks that shared style reaches the retail analyst, service agents and reviewer exactly once and changes prompt provenance hashes when edited. Existing tests cover tool boundaries, review flow, budget settlement, A2A contracts and prompt registry integration.

Offline scripted-model tests verify execution contracts, not semantic robustness of the rewritten instructions. No paid 20-scenario suite or adversarial LLM evaluation was run. Broader quality and grounding regression checks remain necessary before claiming the shorter instructions are equally reliable across all domains.

The experiment follows Google's recommendation to use a few varied examples to teach phrasing and scope, and Anthropic's guidance to remove redundant context while retaining essential constraints. Neither source guarantees a quality improvement; the observed limitation above is retained rather than hidden. [Google prompting strategies](https://aistudio.google.com/docs/prompting-strategies#few-shot), [Anthropic context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents).

New CLI sessions load the files directly. Existing agents use skill snapshots; restart the CLI or rebuild/restart Docker services to load these changes.
