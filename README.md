# Retail Analysis Assistant

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
- [Test prompt observations](evals/rewrite/runs/README.md): how to run examples and inspect captured answers, timings and review results.
- [Golden examples](knowledge/golden/README.md): provenance, offline validation and publication rules.

```bash
uv run --locked pytest
uv run --locked python scripts/validate_golden_bootstrap.py
uv run --locked ruff check .
uv run --locked pyright
```

Saving requires an explicit request. Deletion requires an exact preview and confirmation in the same interactive chat. Report libraries are owner-private, including against CEO access. Existing user data is preserved; explicit legacy import copies owned reports without modifying the source.

The local CLI uses simulated identities, in-memory conversation context and SQLite report storage. Nontechnical persona administration, inferred preference learning, production authentication and deployment infrastructure remain design-only. Evaluator approval does not guarantee correctness.
