# Microsoft Foundry hosting

The repository includes a compiled LangGraph workflow, a descriptive Agent Card and an adapter using Microsoft's `ResponsesHostServer`. The adapter and follow-up persistence are tested locally with scripted models. No Azure resources have been created or deployed by this migration.

For the active local app with Google models and Foundry telemetry/evaluation, use [cloud connections](cloud-connections.md). Hosting the app in Azure is a separate, optional step.

## What gets hosted

One hosted agent runs the coordinator and all three specialist graphs in its process. The Responses endpoint is the external interface; there are no internal A2A services. `FoundryCheckpointSaver` persists graph messages and approved conversation contexts. The platform's request user ID partitions application memory; hosted requests without that identity fail closed. Local development uses a local owner.

The app continues to use Gemini. Hosting in Foundry does not change the model to an Azure deployment. `azure.yaml` starts with synthetic warehouse fixtures so the initial deployment does not require GCP warehouse credentials. Gemini calls still incur charges.

## Verify the adapter locally

```bash
uv sync --group foundry
uv run --group foundry pytest -q tests/integration/test_foundry.py
uv run --group foundry python -m retail_insight.integrations.foundry.host
```

The last command starts the host on port `8088` and uses your `.env`. With `FOUNDRY_PROJECT_ENDPOINT` configured, requests must include an authenticated platform user context; a bare local curl request is rejected. The offline adapter test supplies this context explicitly. Use `BACKEND=fixture` if you do not want BigQuery queries. The offline test uses no paid model; invoking the running host does.

```bash
curl http://127.0.0.1:8088/responses \
  -H 'Content-Type: application/json' \
  -d '{"input":"Compare sales and stock definitions.","stream":false}'
```

Use the returned response ID for a follow-up:

```bash
curl http://127.0.0.1:8088/responses \
  -H 'Content-Type: application/json' \
  -d '{"input":"Summarize that in two sentences.","previous_response_id":"<response-id>","stream":false}'
```

Keep `store` enabled (the default); the SDK rejects `store:false` when using a checkpointer. Locally, Foundry state lives under `~/.agentserver/state_stores`; `AGENTSERVER_STATE_ROOT` can change it. On Foundry protocol 2.0.0, the saver uses the platform State Store.

## Prepare a deployment

```bash
uv run python infra/foundry/package.py
azd ext install azure.ai.agents
azd auth login
```

The packaging script copies only application source and dependency metadata into `.artifacts/foundry-source`. It excludes credentials, chat history, evaluation datasets and local artifacts. Regenerate it after source changes. `azure.yaml` points to that directory, declares the Responses protocol and uses Python 3.13 source deployment.

Use Foundry Toolkit or the `azd` hosted-agent initialization flow to select your subscription, region and existing Foundry project. You need the Foundry Project Manager role. Configure the values referenced in `azure.yaml`: `GEMINI_API_KEY`, `GEMINI_MODEL`, `FOUNDRY_PROJECT_ENDPOINT` and `APPLICATIONINSIGHTS_CONNECTION_STRING`. Store secrets in the selected azd environment or a project connection; do not paste them into the YAML. The hosted managed identity needs telemetry ingestion permissions when `AZURE_MONITOR_ENTRA_AUTH=true`.

After the project/environment is selected and reviewed:

```bash
azd deploy
```

Provisioning a new project is optional and incurs Azure charges; use `azd provision` only if that is the intended deployment. The manifest has been prepared from the official schema, but deployment still requires validation in your Azure tenant, including supported region, SDK previews, network egress and permissions.

To use BigQuery in Azure, provide workload identity federation or another managed credential mechanism granting read-only access and query execution. Set `BACKEND=bigquery`, `GOOGLE_CLOUD_PROJECT` and the trusted warehouse dataset. Do not ship your workstation's ADC file. Google Maps remains optional.

## Persistence scope

The hosted checkpoint preserves approved conversational state. Saved report records still use local SQLite; the prepared manifest puts that working database in `/tmp`. Before relying on saved report tools across hosted instance replacement, configure a durable report store. Checkpointing does not make local filesystem writes durable or resume an interrupted external operation. The localhost Docker application uses a persistent volume for these files.

## Agent Card

The local application exposes `/agent-card.json`; [agent-card.json](../agent-card.json) is the corresponding repository artifact. It describes the coordinator and its skills. It is not an A2A card, a substitute for deployment, or an authentication configuration. Foundry hosts the graph using `azure.yaml` and the Responses adapter.

## Sources

- [Host LangGraph agents](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/langchain-hosted-agents)
- [azure.yaml reference](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/azure-yaml-reference)
- [Source deployment and dependencies](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent-code)
