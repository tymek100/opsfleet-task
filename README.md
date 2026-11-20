# Retail Analysis Assistant

A Python CLI that answers retail questions using one Google ADK/Gemini agent loop. The model chooses tools, writes scoped SQL, interprets results and writes the complete answer in Markdown, including any tables it considers useful. A tool-free evaluator reviews the candidate; corrections return to the same analyst conversation.

```bash
uv sync --locked --python 3.12
uv run --locked retail-agent chat --user alice --golden-bootstrap
```

Supply your Gemini key and Google Cloud application credentials first; see [Quick Start](QUICK_START.md). `--golden-bootstrap` explicitly enables the 11 synthetic reference methods supplied with the repository. They guide analysis; current answers require fresh evidence. Omit it to use only eligible approved knowledge from your configured corpus.

For real Gemini calls against a frozen synthetic dataset, without BigQuery credentials:

```bash
uv run --locked retail-agent chat --user alice --backend fixture --golden-bootstrap
```

The application provides schema discovery, Golden search/read, warehouse queries, local result analysis, prior-answer access and private report management. Permissions, privacy, budgets and confirmed deletion are enforced by application services. Normal answers contain the model's reviewed Markdown; `/details` reveals the supporting SQL and evidence on request.

Runtime analytical skills are enabled by default. The analyst reads relevant methods on demand, and every evaluator call receives the review rubric. Model-facing functions live in `src/retail_agent/tools/`, their database/storage implementations in `services/`, and skill Markdown in `skills/library/`. See [how skills and Golden examples work](docs/architecture.md#skills-and-golden-examples) and [skill authoring](src/retail_agent/skills/README.md).

- [Architecture](docs/architecture.md): the agent loop, tools, data access and implementation limits.
- [Test prompt observations](evals/rewrite/runs/README.md): how to run examples and inspect captured answers, timings and review results.
- [Golden examples](knowledge/golden/README.md): provenance, offline validation and publication rules.

```bash
uv run --locked pytest
uv run --locked python scripts/validate_golden_bootstrap.py
uv run --locked ruff check .
uv run --locked pyright
```

Generating a report does not save it. Ask explicitly to save. Deletion requires an exact preview and confirmation in the same interactive chat. Libraries are private to their owners, including from the CEO. Existing user data is preserved; migration of owned legacy reports is explicit and leaves the source unchanged.

The local CLI uses simulated identities, in-memory conversation context and local SQLite reports. Nontechnical persona administration, inferred preference learning and production identity/infrastructure remain design-only. Evaluator approval is a quality check, not proof that every answer is correct.
