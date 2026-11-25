# Retail Insight Agent

A retail analytics application built on Google ADK and Gemini, with a standalone analyst CLI and a local A2A system: retail, inventory, distribution and coordinator agents. Models choose tools, investigate evidence and compose Markdown answers. A tool-free reviewer checks every analytical candidate and returns revision feedback to the same agent loop.

## Local multi-agent stack

With Docker running and `GEMINI_API_KEY` configured in `.env`:

```bash
uv run retail-stack up --backend fixture
uv run agent-chat coordinator
```

Choose the agent explicitly when chatting with the running services:

```bash
uv run agent-chat coordinator
uv run agent-chat retail
uv run agent-chat inventory
uv run agent-chat distribution
```

`retail-stack` manages service startup, status and shutdown. `retail-agent chat` runs the standalone retail analyst locally; `agent-chat retail` connects to its Docker service.

This builds four agent images and the assistant-ui frontend, and reuses local Phoenix.
Open [localhost:8080](http://localhost:8080), choose an agent, and start a conversation.
The coordinator is selected initially. Answers render as Markdown with readable tables,
copy/CSV controls, saved follow-ups, and a Stop button. Browser authentication is automatic;
credentials stay in the gateway. All agents use A2A 1.0 (Python SDK 1.3.1).
Phoenix remains at [localhost:6006](http://127.0.0.1:6006).

For protocol debugging, add `--inspector` to the startup command and open
[localhost:8081](http://localhost:8081). Inspector is optional; assistant-ui is the default chat.

Fixture mode still calls Gemini. Use `--backend bigquery` with Google Cloud application credentials
for TheLook. Only distribution connects to Google Maps MCP; it needs `GOOGLE_MAPS_API_KEY` and
reports unavailable access explicitly when the key is absent. See the [stack guide](infra/agents/README.md)
for endpoints, authentication, persistence and shutdown.

To run the independent 20-question-plus-follow-up suites for each new agent:

```bash
uv run retail-stack up --backend fixture --evaluation-fixtures
uv run --group evaluation retail-eval run-multi-agent \
  --suite all --max-cost-usd 5 --deadline-seconds 7200
```

Evaluation runs default to a shared **$5 cap** and reject higher limits. Use `--only scenario-01` for a focused run; a full suite may stop early. See [evaluation spending limits](docs/evaluation.md#spending-limit).

The three suites contain 60 conversations and 120 answers. Phoenix receives separate inventory,
distribution and coordinator datasets and a shared `retail-multi-agent` trace project. References
come from independent raw-row calculations and never enter agent context. The suites now use full-dataset access; they have not yet been rerun live in this mode. Live Maps validation, human reference review and judge calibration remain separate outstanding checks.

See [evaluation instructions](docs/evaluation.md) and the [validation report](evaluation/multi_agent/RESULTS.md) for live BigQuery runs, observed failures, fixes and the limits of automatic grading. Maps is intentionally inactive in the current local deployment.

## Standalone retail CLI

```bash
uv sync --python 3.12
uv run retail-agent chat
```

New questions cover all brands unless you request a brand filter, for example, "Show Calvin Klein revenue in Q1 2026." Configure your Gemini key and Google Cloud application credentials first; see [Quick Start](QUICK_START.md). Current answers require fresh query evidence.

For real Gemini calls against a frozen synthetic dataset, without BigQuery credentials:

```bash
uv run retail-agent chat --backend fixture
```

The application provides schema discovery, warehouse queries, local result analysis, prior-answer access and private report management. Application services enforce permissions, privacy, budgets and deletion confirmation. Answers contain the model's reviewed Markdown; `/details` displays supporting SQL and evidence.

Runtime analytical skills are enabled by default. The analyst reads relevant methods on demand, and every evaluator call receives the review rubric. Each agent owns its definition, tool registration, prompt and skills under `src/retail_insight/agents/<role>/`. Shared tools live in `tools/`, execution and accounting in `runtime/`, completion review in `review/`, and external adapters in `integrations/`. See [how skills work](docs/architecture.md#skills-and-evaluation-assets) and [skill authoring](src/retail_insight/runtime/skills/README.md).

- [Architecture](docs/architecture.md): the agent loop, tools, data access and implementation limits.
- [Testing and evaluation](docs/evaluation.md): how tests, datasets, grading, and Phoenix work, with runnable commands.
- [Evaluation design](docs/plans/EVALUATION_REBUILD_PLAN.md): independent references, grading contracts, and remaining validation work.
- [Implementation results](docs/plans/EVALUATION_IMPLEMENTATION_RESULTS.md): verified checks, live trials, grader repairs and limitations.

```bash
uv run --group evaluation pytest
uv run ruff check .
uv run --group evaluation pyright
```

Saving requires an explicit request. Deletion requires an exact preview and confirmation in the same interactive chat. New sessions use the local `workspace` report owner. Stored ownership remains isolated: earlier owners' reports are retained without being merged into the workspace. Legacy import copies only records already owned by `workspace`, leaving the source unchanged.

The standalone CLI uses in-memory conversation context and SQLite report storage. A2A services persist owned tasks and conversation context in separate volumes. User selection and demo brand permissions have been removed. Read-only queries, privacy checks, service authentication and execution limits still apply. Evaluator approval does not guarantee correctness.

## Evaluation and Phoenix

The existing **Retail agent — 20 conversations** dataset and `retail-conversations-20` trace
project remain separate from the new multi-agent suites. Each scenario has an initial question
and a fixed follow-up. The historical baseline, recorded before demo users were removed, produced 37 PASS and three ERROR
answer grades, plus two unresolved trajectory checks; see the [evaluation guide](docs/evaluation.md)
for its capture and diagnosis. Historical local captures remain preserved. Current retail scenarios state requested brand filters explicitly; the migrated scenarios have not yet been rerun live.

Run new conversations with Gemini and BigQuery credentials configured and Docker running:

```bash
uv run --group evaluation retail-eval run-conversations \
  --max-cost-usd 5 --deadline-seconds 3600
```

The command starts or connects to local Phoenix, captures independent references, and runs the
agent against the same timestamp-pinned BigQuery tables. It prints experiment and trace links,
then publishes both answers and automatic scores after each conversation. Dataset Output contains
expected facts and criteria for both turns. Each scenario has isolated state; follow-ups retain
its conversation. The total budget includes execution, reference queries, and independent judges.

Numeric values are checked by code against Decimal/set references. Separate LLM judgments check
evidence, completeness, and tool use. Runtime approval is not an evaluation pass. Historical
assistant reviews remain separate; neither those reviews nor automatic judges are human-calibrated.

Retail run artifacts live under `.artifacts/manual/`; questions and publication history live in
`evaluation/scenarios/`. [Testing and evaluation](docs/evaluation.md) explains the dataset,
scores, evidence checks, reference versions, and unresolved evaluations.

The four repository prompt definitions remain available in
[Phoenix Prompts](http://127.0.0.1:6006/prompts). Synchronize without model calls with
`uv run --group evaluation retail-eval sync-prompts`.
Git remains authoritative; UI prompt edits do not change application behavior.

The separate controlled pilot retains 43 synthetic cases, independent Decimal/set
references, and 40 judge controls. Its automated answer/trajectory grading remains available
through `retail-eval run`, using a separate Phoenix endpoint such as port 6007. Pilot publication
and collector integration tests cannot use the main port 6006 workspace. The Phoenix pytest auto-publication
plugin is disabled. See [Phoenix setup](infra/phoenix/README.md#disposable-test-instance).

Evaluation references never enter analyst context. Human reference review, judge calibration, and a sealed holdout remain pending.

The CLI workflow expects a source checkout: runtime skills, Git metadata, and `uv.lock` are
resolved from the repository. The wheel supports reference validation but is not a standalone
distribution of the complete application.
