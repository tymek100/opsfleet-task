# Retail Insight Agent

A Python CLI for retail analysis with a single Google ADK/Gemini agent loop. The model selects tools, writes scoped SQL, interprets results and generates Markdown, including tables when appropriate. A tool-free evaluator reviews each candidate; revision feedback returns to the same analyst conversation.

```bash
uv sync --locked --python 3.12
uv run --locked retail-agent chat --user alice --golden-bootstrap
```

Configure your Gemini key and Google Cloud application credentials first; see [Quick Start](QUICK_START.md). `--golden-bootstrap` enables the repository's 11 synthetic reference methods. Current answers require fresh evidence. Without this flag, only eligible approved examples from the configured corpus are available.

For real Gemini calls against a frozen synthetic dataset, without BigQuery credentials:

```bash
uv run --locked retail-agent chat --user alice --backend fixture --golden-bootstrap
```

The application provides schema discovery, a Golden example catalog, warehouse queries, local result analysis, prior-answer access and private report management. The analyst selects examples from eligible summaries. Application services enforce permissions, privacy, budgets and deletion confirmation. Answers contain the model's reviewed Markdown; `/details` displays supporting SQL and evidence.

Runtime analytical skills are enabled by default. The analyst reads relevant methods on demand, and every evaluator call receives the review rubric. Model-facing functions live in `src/retail_agent/tools/`, their database/storage implementations in `services/`, and skill Markdown in `skills/library/`. See [how skills and Golden examples work](docs/architecture.md#knowledge-and-evaluation-assets) and [skill authoring](src/retail_agent/skills/README.md).

- [Architecture](docs/architecture.md): the agent loop, tools, data access and implementation limits.
- [Testing and evaluation](docs/evaluation.md): how tests, datasets, grading, and Phoenix work, with runnable commands.
- [Evaluation design](docs/plans/EVALUATION_REBUILD_PLAN.md): independent references, grading contracts, and remaining validation work.
- [Implementation results](docs/plans/EVALUATION_IMPLEMENTATION_RESULTS.md): verified checks, live trials, grader repairs and limitations.
- [Golden examples](knowledge/golden/README.md): provenance, offline validation and publication rules.

```bash
uv run --locked --group evaluation pytest
uv run --locked python scripts/validate_golden_bootstrap.py
uv run --locked ruff check .
uv run --locked --group evaluation pyright
```

Saving requires an explicit request. Deletion requires an exact preview and confirmation in the same interactive chat. Report libraries are owner-private, including against CEO access. Existing user data is preserved; explicit legacy import copies owned reports without modifying the source.

The local CLI uses simulated identities, in-memory conversation context and SQLite report storage. Nontechnical persona administration, inferred preference learning, production authentication and deployment infrastructure remain design-only. Evaluator approval does not guarantee correctness.

## Evaluation and Phoenix

The main Phoenix workspace contains one dataset, **Retail agent — 20 conversations**, and one
trace project, `retail-conversations-20`. Each scenario has an initial question and a fixed
follow-up. Six named experiments preserve three complete runs and three targeted retests,
including failures, both answers, original traces, and existing assistant reviews.

Run new conversations with Gemini and BigQuery credentials configured and Docker running:

```bash
uv run --locked --group evaluation retail-eval run-conversations \
  --max-cost-usd 6 --deadline-seconds 3600
```

The command starts or connects to local Phoenix, captures independent references, and runs the
agent against the same timestamp-pinned BigQuery tables. It prints experiment and trace links,
then publishes both answers and automatic scores after each conversation. Dataset Output contains
expected facts and criteria for both turns. Each scenario has isolated state; follow-ups retain
its conversation. The total budget includes execution, reference queries, and independent judges.

Numeric values are checked by code against Decimal/set references. Separate LLM judgments check
evidence, completeness, and tool use. Runtime approval is not an evaluation pass. Historical
assistant reviews remain separate; neither those reviews nor automatic judges are human-calibrated.

Republish the saved historical answers and reviews without inference:

```bash
uv run --locked --group evaluation retail-eval publish-conversations
```

This requires the original local capture/review artifacts and Phoenix traces. Run artifacts
live under `.artifacts/manual/`; questions and publication history live in
`evaluation/scenarios/`. [Testing and evaluation](docs/evaluation.md) explains the dataset,
scores, evidence checks, reference versions, and unresolved evaluations.

The four repository prompt definitions remain available in
[Phoenix Prompts](http://127.0.0.1:6006/prompts). Synchronize without model calls with
`uv run --locked --group evaluation retail-eval sync-prompts`.
Git remains authoritative; UI prompt edits do not change application behavior.

The separate controlled evaluation suite retains 43 synthetic cases, independent Decimal/set
references, and 40 judge controls. Its automated answer/trajectory grading remains available
through `retail-eval run`, using a separate Phoenix endpoint such as port 6007. Fixture publication
and collector tests cannot use the main port 6006 workspace. The Phoenix pytest auto-publication
plugin is disabled. See [Phoenix setup](infra/phoenix/README.md#disposable-test-instance).

`knowledge/golden/` contains optional runtime methods; evaluation references never enter analyst
context. Human reference review, judge calibration, and a sealed holdout remain pending.

The CLI workflow expects a source checkout: knowledge assets, Git metadata, and `uv.lock` are
resolved from the repository. The wheel supports reference validation but is not a standalone
distribution of the complete application.
