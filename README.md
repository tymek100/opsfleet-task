# Retail Insight Agent

Retail analytics with a custom **LangGraph** multi-agent workflow, Gemini, BigQuery and assistant-ui. A coordinator delegates to retail, inventory and distribution specialists in the same process. Each agent chooses its tools and revises its answer against a tool-free reviewer before publication.

## Run

Configure `.env` using [.env.example](.env.example), then:

```bash
uv sync
uv run agent-chat coordinator
```

Other entry points: `uv run agent-chat retail`, `uv run agent-chat inventory`, and `uv run agent-chat distribution`. The terminal supports `/help`, `/new` and `/exit`. No containers are needed for CLI conversations.

For the web application, with Docker running:

```bash
uv run retail-stack up --backend bigquery
```

Open **http://127.0.0.1:8080**. Choose an agent, ask follow-ups, copy tables, or delete saved conversations. One container hosts all four agents and the UI. `retail-stack down` stops it and preserves storage. Historical A2A sessions remain in their old volumes; the new runtime starts separate conversations.

BigQuery requires `GOOGLE_CLOUD_PROJECT` and Application Default Credentials (`gcloud auth application-default login`). `--backend fixture` uses synthetic warehouse rows instead; **Gemini calls still cost money**. The distribution agent's optional Google Maps MCP integration remains unavailable until a Maps key is configured.

Example:

```text
Compare our Q1 2026 sales with current inventory. Which categories deserve a closer look?
```

Follow-up:

```text
Summarize that report in two short sentences. Preserve the main limitation and avoid unsupported recommendations.
```

## Architecture and operations

- [Architecture](docs/architecture.md): graph nodes, inheritance, delegation, tools and memory.
- [Cloud connections](docs/cloud-connections.md): optional tracing, Azure Monitor traces and evaluation results.
- [Evaluation](docs/evaluation.md): independent references, hallucination checks, offline tests and the $5 run cap.
- [Microsoft Foundry](docs/foundry.md): Agent Card, Responses adapter, durable checkpoints and deployment preparation.
- [Migration checklist](docs/plans/LANGGRAPH_MIGRATION.md): implementation and verification status.

There is no internal A2A transport, ADK runtime or Phoenix service. The implementation uses `StateGraph` directly, never LangChain's `create_agent`. LangChain Core supplies message types; the optional Foundry SDK has additional framework dependencies.

Runtime approval is not proof of correctness. Independent evaluation checks numerical facts, evidence support, task completion and observable agent behavior. Existing authored scenarios remain development data; human reference review, judge calibration and a sealed holdout remain outstanding.
