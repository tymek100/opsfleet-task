# Golden Knowledge bootstrap for the replacement application

This collection contains **11 LLM-authored illustrative Question → SQL → Analyst Report examples**, backed by **14 reference queries** against a frozen synthetic fixture. The replacement application retrieves these examples when explicitly started with `--golden-bootstrap`; they remain ineligible for normal production retrieval. It is not an evaluation score or a record of a live agent run.

The examples demonstrate methods and useful answers. They do not prescribe a sequence of actions, an analytical intent enum, a report template, or a presentation format. Some answers use a table; others use a sentence or short narrative. The analyst decides what the user's question requires and generates its own answer from fresh evidence.

## Files and provenance

- [bootstrap.json](bootstrap.json): questions, SQL, exact fixture results, LLM-authored analyst-report Markdown, method notes and publication metadata.
- [bootstrap.schema.json](bootstrap.schema.json): strict JSON Schema for this illustrative collection.
- [retail_seed_v1.sql](../fixtures/retail_seed_v1.sql): frozen synthetic rows, adapted from the repository's earlier small fixture and extended to distinguish item and order grain and include an unsold product.
- [validate_golden_bootstrap.py](../../scripts/validate_golden_bootstrap.py): standalone offline checker. It imports neither the application nor its tests and does not load credentials.

The Codex assistant authored the questions, SQL and reference prose. No company analyst supplied or approved them. `analyst_report_markdown` is the Trio's field name; it is not a claim of human authorship. The collection records `human_reviewed: false` and `live_application_model_run: false`.

All examples are `synthetic_fixture_validated_not_human_approved`, with `synthetic_demo_only` visibility. The implemented loader rejects this collection in normal production retrieval. A developer may explicitly enable synthetic demonstration mode to exercise retrieval locally; this is separate from publishing approved company knowledge. The schema deliberately cannot label this bootstrap corpus as approved. A production publication format should track a real reviewer, review time, compatibility and visibility.

The fixture includes two brands, a shared customer, a mixed-brand order, repeated purchases, two eligible items in one order, item-level and order-level exclusions, an unsold product, empty periods, and purchases at period boundaries. No customer contacts or geography appear in the fixture. Its values are invented; the figures must never be described as live company results. Its digest is recorded in the collection, so changing the rows invalidates the validation evidence until deliberately re-reviewed.

## What is included

| Example | Method illustrated | Reference answer choice |
| --- | --- | --- |
| Separate product rankings | Revenue and distinct customers have separate rankings | Two compact tables |
| Average scoped order value | Aggregate eligible authorized items to distinct orders | Brief prose |
| Repeat-customer share | Count distinct orders per customer before measuring repeats | Brief prose |
| Customer revenue concentration | Compute the denominator before limiting the ranking | Narrative and a qualified next step |
| Status reconciliation | Explicit all-status analysis with disjoint cancellation/return buckets | Compact reconciliation table |
| Catalog without sales | Preserve unmatched catalog products in a left join | One finding and a limitation |
| Monthly cohort retention | First observed authorized purchase and next-month activity | Cohort table with denominators |
| New and returning revenue | Compute customer history before filtering the report month | Narrative |
| Empty-period comparison | Correct a false premise; zero-baseline change is undefined | Narrative |
| Inactivity false spike | Check a claimed change in 90-day inactivity before explaining it | Narrative with numerator and denominator |
| Quarterly action report | Combine evidence, qualify interpretation and propose actions | Short report with one table |

These presentation choices are examples, not exact-match targets. The short report uses three reference queries because they provide sufficient evidence here; the analyst can obtain equivalent evidence through a different valid approach.

The fixture's Q1 Calvin Klein totals are independently enumerated as **375 revenue, 7 items, 6 orders and 5 distinct customers**. Its mixed-brand order contributes 125 to Calvin Klein and 900 to Levi's. This intentionally differs from the older application test fixture. Revenue uses item sale prices; no currency is asserted.

## Validate offline

From the repository root, using the locked environment including development dependencies:

```bash
uv sync --locked
uv run --locked python scripts/validate_golden_bootstrap.py
```

The existing locked environment provides DuckDB, SQLGlot and JSON Schema validation. To run directly with an already installed environment:

```bash
.venv/bin/python scripts/validate_golden_bootstrap.py
```

The checker validates the schema and frozen fixture digest; builds scope-filtered `sales`, `transactions` and `products` views; parses each query in BigQuery dialect; transpiles it only for the synthetic DuckDB execution; compares every returned row with its independently specified expected evidence; and checks 23 explicitly selected evidence facts. It separately checks manager/all-brand totals and the mixed-brand order. DuckDB external file/network access is disabled.

The successful run reports:

```text
Validated 11 examples, 14 SQL queries, 23 explicit evidence facts.
Offline synthetic evidence only; no live BigQuery, agent run or human approval.
```

The author also checked the prose arithmetic: status buckets sum to 2,674; 375/6 gives 62.50; 1/5 gives 20%; 175/375 rounds to 46.67%; and monthly revenue changes are -20% and +50%. The script checks result evidence, not the full semantics or readability of prose. Human review and held-out model evaluation remain necessary before publishing real knowledge. BigQuery parsing plus DuckDB execution does not establish live BigQuery compatibility; a separate BigQuery dry run is required during implementation. The checker is an offline asset validator, not the replacement runtime's SQL security boundary.

## How the agent chooses examples

The analyst uses two tools in its normal loop:

1. `list_golden(offset=0, limit=20)` lists short summaries of eligible examples. Each page contains at most 20 entries; the supplied bootstrap fits on one page. The response provides `next_offset` when more entries remain.
2. `read_golden(example_id)` returns a complete question, SQL, and answer for an eligible ID. The analyst decides which summaries are relevant, which examples to read, and whether to use any example at all.

The same LLM that investigates the user's question makes these choices. There is no separate retrieval model, keyword matching, stop-word list, or full-text index. Pagination limits the size of a tool response; it does not rank relevance.

Before either tool exposes content, application code checks approval, visibility, authorized data scope, schema and metric compatibility. The synthetic-demo flag is required for this corpus. Content hashes and publication metadata remain part of validation; permission to read an example never expands permission to query data. Returned content includes provenance and a reminder that stored numbers are historical or synthetic. It cannot override application instructions or authorize tools.

The LLM may adapt, combine, or ignore examples. It composes SQL for the current request, obtains fresh authorized evidence, and writes its own answer. A retrieved report is a writing example, never a source of current numerical claims. Tool records identify examples that were read; reading one does not prove that it influenced the answer.

Offline checks cover eligibility, pagination, and tool wiring. They do not measure whether model-selected examples improve relevance or answer quality. That requires model trials comparing answers with and without examples, using the same questions and data. Such evaluation should judge results rather than require a particular example ID or exact tool order.

One [live fixture smoke run](../../evals/rewrite/runs/golden-catalog-01/observations.md) exercised catalog selection, reading a relevant example, and querying fresh data. Its calculation matched the fixture facts, though the answer was verbose. This single run does not establish an improvement over keyword search.

## Production publication

Google's text-to-SQL discussion supports supplying relevant schema/business examples and returning deterministic parse or dry-run errors to the model for correction. [Google Cloud: Text-to-SQL techniques](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql)

Research on demonstration selection supports considering both similarity and diversity; it does not establish that one retrieval configuration will work best for this app. [Nan et al.: Few-shot Text-to-SQL prompt design](https://arxiv.org/abs/2305.12586)

For production population, propose sanitized drafts from analyst work or successful reviewed agent investigations, bind SQL/results to a known dataset snapshot and scope, run numerical/privacy/compatibility checks, then obtain editor/reviewer approval. Publish immutable revisions, add compatible approved versions to the catalog, and retire stale examples. A passing automated fixture check does not replace the human review accepted in the client Q&A. Persona publishing has its own automated gate and is a different workflow.

## Keep knowledge and evaluation separate

This corpus is allowed context for a demonstration; it is **never** the held-out test suite. Maintain separate development and held-out evaluation assets. Exclude held-out questions, answers, reference SQL, expected results and grader rubrics from the Golden catalog, prompts and model-visible files. Review near-duplicates by analytical family, not only exact text, and use changed data, dates, scopes and compositions to expose memorized patterns.

After a held-out failure is used to tune prompts or write a Golden example, move that case into the regression/development suite and create a fresh held-out case. A paraphrase of a retrieval seed is a useful smoke test, but insufficient evidence of generalization. Real model trials should measure task results, evidence grounding, useful presentation, and observable report-store changes; numerical/security assertions need deterministic checks, while readability and synthesis benefit from calibrated model/human rubrics. [Anthropic: Agent evaluation guidance](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)

Compare SQL results across distinguishing fixture variants, not exact SQL strings. A single dataset can make incorrect queries appear equivalent; semantic text-to-SQL evaluation research motivates multi-dataset checks. [Zhong et al.: Semantic evaluation with distilled test suites](https://arxiv.org/abs/2010.02840)
