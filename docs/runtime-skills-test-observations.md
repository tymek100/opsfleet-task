# Runtime skills: implementation and test observations

Date: 20 November 2026. These are development regression checks and small live trials, not a held-out reliability benchmark.

## Implemented and verified

Six packaged runtime skills are active: five analyst methods selected through `load_skill`, and one analytical-review rubric supplied on every review. A separate `load_skill_resource` tool reads a listed reference after its parent skill is loaded. The model chooses investigations, queries and presentation. Tools now live in `src/retail_agent/tools/`, backend services in `services/`, and instructions in `skills/library/`; `runtime.py` assembles the ADK conversation and `turn.py` holds shared accounting/state.

**158 offline tests passed.** [Recorded output](../evals/rewrite/runtime-skills-offline-checks.txt). All 135 pre-existing tests also passed immediately after tool/service extraction. The added loader/runtime tests verify:

- Metadata reaches the initial model context without full skill/reference text.
- A model-requested load supplies the exact instructions; reference text requires its separate read.
- Unknown names, reviewer-only skills, traversal, symlinks, oversized files and executable/tool-grant content are rejected.
- Skill reads share the tool budget and preserve the completion slot.
- Loaded guidance is recorded as method provenance, not numerical evidence.
- The reviewer receives its rubric without analyst skill selection and still has no tools.
- Catalog snapshots and hashes remain stable, and edits during native parsing are rejected.

Ruff check/format, Pyright, the installed CLI entry point and the existing Golden validator passed. The Golden validator checked 11 examples, 14 queries and 23 selected facts against the synthetic fixture. Two non-failing test warnings remain: a blocked SDK loopback-capability probe and ADK's experimental-schema notice.

The wheel was built offline and extracted to a temporary directory outside the repository. A fresh Python process loaded the packaged catalog there, found all six SKILL.md files, read the measurement reference and matched every source skill hash. Tools and relocated services were included. [Package check](../evals/rewrite/runtime-skills-package-check.json).

## Live analyst trials

The configured model was `gemini-3.8-flash`, with low analyst and medium reviewer thinking. All trials used temporary report storage and the existing per-turn USD 1 admission cap and 120-second deadline. The ranking runs used the read-only public TheLook gateway. The method-only trial used fixture mode and made no warehouse query. Captures include skill versions/content hashes and actual tool events; no user report library was read or changed.

| Trial | Seconds | Observed behavior and manual assessment |
| --- | ---: | --- |
| [Ranking skill version 1: initial question](../evals/rewrite/runs/runtime-skills-rankings-01/observations.md) | 45.001 | Autonomously loaded product-ranking-analysis. Values, selected lists and tie counts were grounded. Reviewer requested one grounding revision, then approved. **Presentation was too verbose:** six-column tables and unsolicited methodology/overlap. “Qualifying completed sales” incorrectly suggested Complete-only status. |
| [Ranking skill version 1: follow-up](../evals/rewrite/runs/runtime-skills-rankings-01/observations.md) | 21.036 | Reloaded the relevant method and reused evidence. This evidence included units sold, so average unit-price comparisons were supported. “Transaction values” was less precise than item prices/product spending; whole-order basket values were not measured. |
| [Explicit skill and reference](../evals/rewrite/runs/runtime-skills-reference-01/observations.md) | 13.307 | Loaded revenue-driver-analysis and references/measurement-guide.md. Correctly distinguished realized unit prices, quantities, customer counts and product-mix effects. One paragraph, no invented business figures, zero queries. |
| [Ranking skill version 2: initial question](../evals/rewrite/runs/runtime-skills-rankings-02/observations.md) | 31.327 | Autonomously loaded the refined ranking skill. Returned exactly five products per list in four-column tables with product-ID ties. Removed the unsupported Complete-only label and unsolicited overlap section. Notes remain longer than necessary. |
| [Ranking skill version 2: follow-up](../evals/rewrite/runs/runtime-skills-rankings-02/observations.md) | 29.232 | Checked overlap through local result analysis, read prior evidence, then **chose a fresh query for actual units and average realized prices** before explaining the difference. The measured data support the price/quantity comparison. |

The version 1 and version 2 customer lists differ because the agent chose different stable tie-breaks: revenue then product ID in the first run, product ID in the second. Each follow-up preserved its own selected lists. Their overlap difference does not establish a warehouse data refresh.

For the final follow-up, E3 confirms an empty intersection and E5 measures all ten selected products. Revenue leaders have 1–2 units and average realized prices of **108.00–259.99**; customer-reach leaders have 2–3 units and average prices of **20.00–69.50**. Each average was checked against captured revenue divided by units. Unlike the originally reported failure, this answer did not infer unit prices from customer counts alone: it obtained the missing measurements first.

The final wording still sounds broader than necessary (“driven by” and “outweighs”); its supported interpretation is a descriptive comparison of these selected products, not a causal study or proof of whole-brand concentration. Skill loading does not guarantee ideal prose or reasoning. The first run's false approval and verbosity are retained rather than hidden.

## Reviewer calibration after moving the rubric

[Recorded four-case calibration](../evals/rewrite/runs/runtime-skills-reviewer-01.json) replayed the original reported unsupported explanation, a hedged variant and two supported controls. Expected labels and issue descriptions remained outside the evaluator input.

| Candidate | Expected / observed | Manual assessment |
| --- | --- | --- |
| Original unsupported price/volume explanation | Revise / revise | Identified missing unit-price and unit-volume measurements |
| Unsupported explanation with “suggests” | Revise / revise | Identified missing price/quantity and brand-wide concentration evidence |
| Supported overlap observation | Approve / approve | No false rejection observed |
| Explicitly unverified hypotheses | Approve / approve | Accepted useful hypotheses with stated evidence gaps |

All four expected decisions matched, with genuine grounding reasons for the two rejections. This does not establish a general reliability rate. The evaluator's skill is always supplied, and its metadata appears in the trace on every review; it remains a separate tool-free LLM call within the shared allowance.

## Compact ranking presentation follow-up

The user requested less repetition after an otherwise correct ranking answer. `product-ranking-analysis` version **3** now omits unrequested IDs when names are unambiguous, keeps identifiers in evidence for grouping and follow-ups, and consolidates material caveats into a brief shared note. `analytical-review` version **2** checks substantial clutter while preserving explicit requests for identifiers, methods and all ties. The LLM still chooses the wording and generates the tables; no renderer filtering or fixed response template was added.

**49 focused loader, runtime and reviewer tests passed**, along with Ruff, formatting, Pyright and diff checks. Two real-model checks used temporary storage:

| Prompt | Seconds | Manual observation |
| --- | ---: | --- |
| [Exact compact-ranking request, public BigQuery](../evals/rewrite/runs/compact-rankings-01/observations.md) | 26.423 | Exactly five rows in each of two three-column tables: rank, product name, requested metric. No ID column, repeated scope section or extended methodology. One shared note. Values/order agree with captured evidence. A quantified tie parenthesis remains; wording is still model-selected. |
| [Explicit IDs and methods, synthetic fixture](../evals/rewrite/runs/compact-rankings-explicit-details-01/observations.md) | 33.735 | IDs retained in both tables, sales exclusions and tie-breaking explained, and the genuine two-product shortfall disclosed. Fixture values and excluded-item counts agree with evidence. |

The [terminal preview](../evals/rewrite/runs/compact-rankings-01/terminal-preview.txt) uses the actual CLI renderer at 110 columns. These selected trials demonstrate improved compactness and preserved explicit-detail behavior, not a guarantee of identical future formatting. Restart the CLI to load the new skill snapshot. The reusable evaluation cases are `compact_rankings` and `rankings_with_details`.

## Reproduce

```bash
uv run --locked pytest

uv run --locked python scripts/evaluate_rewrite.py \
  --live --backend bigquery --golden-bootstrap --case ranking_followup \
  --output evals/rewrite/runs/runtime-skills-rankings-local

uv run --locked python scripts/evaluate_rewrite.py \
  --live --backend fixture --case skill_reference \
  --output evals/rewrite/runs/runtime-skills-reference-local

uv run --locked python scripts/calibrate_reviewer.py \
  --live --suite ranking_grounding --timeout 120 \
  --output evals/rewrite/runs/runtime-skills-reviewer-local.json
```

Use new output paths to preserve previous observations. Runtime skills are enabled by default; no new CLI flag is needed. Restart the chat process after editing the library so it obtains a new content snapshot. See [architecture and research](runtime-skills.md) and [authoring instructions](../src/retail_agent/skills/README.md).
