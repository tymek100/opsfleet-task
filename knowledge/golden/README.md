# Golden Knowledge bootstrap

This collection contains **11 LLM-authored Question → SQL → Analyst Report examples**, backed by **14 reference queries** against a frozen synthetic fixture. They are available only with `--golden-bootstrap` and remain ineligible for production retrieval. The collection is illustrative, not an evaluation result or live-agent record.

Examples illustrate analytical methods and presentation choices, including tables and prose. They define no fixed tool sequence, intent enum or report template. The analyst selects its approach and generates an answer from fresh evidence.

## Files and provenance

- [bootstrap.json](bootstrap.json): questions, SQL, exact fixture results, LLM-authored analyst-report Markdown, method notes and publication metadata.
- [bootstrap.schema.json](bootstrap.schema.json): strict JSON Schema for this illustrative collection.
- [retail_seed_v1.sql](../fixtures/retail_seed_v1.sql): frozen synthetic rows, adapted from the repository's earlier small fixture and extended to distinguish item and order grain and include an unsold product.
- [validate_golden_bootstrap.py](../../scripts/validate_golden_bootstrap.py): standalone offline checker. It imports neither the application nor its tests and does not load credentials.

Codex authored the questions, SQL and reference prose; no company analyst supplied or approved them. The field name `analyst_report_markdown` does not imply human authorship. Provenance records `human_reviewed: false` and `live_application_model_run: false`.

Every example has status `synthetic_fixture_validated_not_human_approved` and visibility `synthetic_demo_only`. The loader requires explicit demonstration mode, and the bootstrap schema rejects approved status. Enabling the corpus does not publish approved company knowledge. Production publication should record reviewer identity, review time, compatibility and visibility.

The fixture includes two brands, a shared customer, a mixed-brand order, repeated purchases, two eligible items in one order, item-level and order-level exclusions, an unsold product, empty periods, and period-boundary purchases. It contains no customer contacts or geography. All values are synthetic. The collection records the fixture digest; changed rows require renewed validation and review before their evidence is accepted.

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

Presentation is illustrative, not an exact-match target. The short report uses three reference queries; other valid investigations may obtain equivalent evidence.

Independently enumerated Q1 Calvin Klein totals are **375 revenue, 7 items, 6 orders and 5 distinct customers**. The mixed-brand order contributes 125 to Calvin Klein and 900 to Levi's. These values intentionally differ from the earlier application fixture. Revenue uses item sale prices; currency is unspecified.

## Validate offline

From the repository root, using the locked environment including development dependencies:

```bash
uv sync
uv run python scripts/validate_golden_bootstrap.py
```

The locked environment includes DuckDB, SQLGlot and JSON Schema validation. With dependencies already installed:

```bash
.venv/bin/python scripts/validate_golden_bootstrap.py
```

The validator checks the schema and fixture digest, builds scoped `sales`, `transactions` and `products` views, parses BigQuery SQL, and transpiles it for synthetic DuckDB execution. It compares every returned row with independently specified expectations and checks 23 selected evidence facts, plus manager/all-brand totals and the mixed-brand order. DuckDB external file and network access is disabled.

The successful run reports:

```text
Validated 11 examples, 14 SQL queries, 23 explicit evidence facts.
Offline synthetic evidence only; no live BigQuery, agent run or human approval.
```

The author also checked the narrative arithmetic: status buckets total 2,674; 375/6 = 62.50; 1/5 = 20%; 175/375 rounds to 46.67%; monthly revenue changes are -20% and +50%. The script validates result evidence, not complete narrative semantics or readability. Production publication still requires human review and held-out model evaluation. DuckDB execution does not establish BigQuery compatibility; separate BigQuery dry-run validation is required. Asset validation is independent of runtime SQL security controls.

## How the agent chooses examples

The analyst uses two tools in its normal loop:

1. `list_golden(offset=0, limit=20)` returns eligible summaries in pages of at most 20 entries, with `next_offset` when more remain. The bootstrap fits on one page.
2. `read_golden(example_id)` returns the complete question, SQL and answer for an eligible ID. The analyst selects relevant examples and may use none.

The analyst LLM determines relevance. Retrieval uses no separate model, keyword matching, stop-word list or full-text index. Pagination bounds response size without ranking entries.

Before disclosure, the catalog checks approval, visibility, authorized scope, schema/metric compatibility, content integrity and applicable publication metadata. This corpus requires synthetic-demo mode. Responses include provenance and a historical/synthetic-data warning. Examples cannot expand query permissions, override instructions or authorize tools.

The LLM may adapt, combine or ignore examples, then compose SQL and generate its answer from fresh authorized evidence. Reference reports cannot support current numerical claims. Tool records identify examples read, not whether they influenced the answer.

Offline checks cover eligibility, pagination and tool integration. Relevance and answer-quality improvements require model trials with and without examples on identical questions and data. Evaluate outcomes without prescribing example IDs or tool order.


## Production publication

Google's text-to-SQL discussion supports supplying relevant schema/business examples and returning deterministic parse or dry-run errors to the model for correction. [Google Cloud: Text-to-SQL techniques](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql)

Research on demonstration selection supports considering both similarity and diversity; it does not establish that one retrieval configuration will work best for this app. [Nan et al.: Few-shot Text-to-SQL prompt design](https://arxiv.org/abs/2305.12586)

The proposed production workflow creates sanitized drafts from analyst work or reviewed agent investigations, binds SQL/results to a dataset snapshot and scope, runs numerical/privacy/compatibility checks, and obtains editor/reviewer approval. Publish immutable revisions, add compatible approved versions to the catalog and retire stale examples. Automated fixture checks do not replace the human review required by the client Q&A. Persona publication uses a separate automated gate.

## Keep knowledge and evaluation separate

This demonstration corpus must remain separate from development and held-out evaluation assets. Exclude held-out questions, answers, reference SQL, expected results and grader rubrics from the Golden catalog, prompts and model-visible files. Check overlap by analytical family as well as text; vary data, dates, scopes and task composition to expose memorized patterns.

Once a held-out failure informs a prompt or Golden example, move it to regression/development and replace it in the holdout. Seed paraphrases are useful smoke tests, not evidence of generalization. Model trials should measure task outcomes, grounding, presentation and persisted report state. Use deterministic numerical/security checks and calibrated model/human rubrics for readability and synthesis. [Anthropic: Agent evaluation guidance](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)

Compare SQL results across distinguishing fixture variants, not exact SQL strings. A single dataset can make incorrect queries appear equivalent; semantic text-to-SQL evaluation research motivates multi-dataset checks. [Zhong et al.: Semantic evaluation with distilled test suites](https://arxiv.org/abs/2010.02840)
