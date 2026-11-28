# Google inference, Foundry observability

## Responsibilities

| Connection | Services | Authentication |
|---|---|---|
| Google | Gemini agents, runtime reviewer and independent judges | Existing `GEMINI_API_KEY` |
| Google warehouse | BigQuery / TheLook | ADC and `GOOGLE_CLOUD_PROJECT` |
| Azure | Foundry datasets, evaluation results and Application Insights | Entra ID for project APIs; monitoring connection for telemetry |
| Optional Azure inference | Azure OpenAI v1 endpoint | `AZURE_OPENAI_API_KEY`; not selected by the app |

The current Gemini connection uses the **Gemini Developer API**, explicitly with
`vertexai=False`. This preserves the existing key and billing route. BigQuery is a
separate GCP service; adding Azure does not redirect either Google connection.

## Local configuration

Keep the existing Google values in `.env` and add:

```dotenv
FOUNDRY_PROJECT_ENDPOINT=https://your-resource.services.ai.azure.com/api/projects/your-project
FOUNDRY_TRACING=true
FOUNDRY_AGENT_ID=retail-insight
TRACE_CONTENT_MODE=metadata
AZURE_AUTH_MODE=default
```

The Azure OpenAI endpoint/key are separate optional settings:
`AZURE_OPENAI_BASE_URL` and `AZURE_OPENAI_API_KEY`. A model API key cannot authorize
Foundry project operations. Do not put credentials in agent prompts or Agent Cards.

```bash
az login --tenant <your-project-tenant-id>
uv sync --group evaluation
uv run retail-stack connect-foundry
uv run retail-stack up
```

`connect-foundry` checks access to project datasets and discovers its existing
Application Insights connection. It writes that connection into the owner-only
`.env` without printing it. It does not create Azure resources or invoke models.
Connect an Application Insights resource in Foundry first if none exists.

The local Docker app reads an owner-only configuration file with Google and Azure
settings. It can export telemetry with the saved monitoring connection without
mounting your Azure CLI credential cache. If ingestion requires Entra, set
`AZURE_MONITOR_ENTRA_AUTH=true` and provide a suitable workload/service identity.
Project evaluation commands normally run on the host using `az login`.

## Chat and evaluations

```bash
uv run agent-chat coordinator
uv run --group evaluation retail-eval run-conversations \
  --only scenario-01,scenario-03 --max-cost-usd 1 --deadline-seconds 600
uv run --group evaluation retail-eval run-multi-agent \
  --suite inventory --backend fixture --max-cost-usd 1
```

See [evaluation](evaluation.md) for all suites and local artifacts. Open your
project at [Microsoft Foundry](https://ai.azure.com), then **Traces** or
**Evaluation**. Reference and result datasets are versioned separately.

The independent judges stay on Gemini. Foundry imports their resolved checks with
a non-LLM evaluator; it does not independently re-judge the text with an Azure
model. This preserves the existing numerical checks, calibration limitations and
shared model budget. The published data identifies this assessment method.

## Capture and failure behavior

Metadata-only tracing omits question, answer and tool payloads. Evaluation runners
explicitly opt into sanitized synthetic content. Secrets, bearer/confirmation
tokens and model thought parts are removed. Large JSON documents are stored in
numbered span attributes to respect Azure's per-property limit; the preview points
to those parts. Complete local captures remain in the evaluation artifacts.

Each model span records Google provider/model, token usage and application cost
estimates. Foundry's built-in price catalog may not price external Gemini models;
inspect the recorded `llm.cost.*` attributes for our estimates.

Ordinary chat remains available if tracing setup fails, with a visible warning.
Evaluations validate the Azure connection before spending model tokens and retain
local results when later uploads fail. The $5 application cap does not cap Azure
storage or monitoring charges. Existing conversations and warehouse permissions
are unchanged.

## Sources

- [External agents and observability](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/register-external-agent)
- [Client-side OpenTelemetry export](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-client-side)
- [Evaluate precomputed datasets](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-datasets)
- [Foundry evaluation REST contract](https://learn.microsoft.com/en-us/azure/foundry/reference/rest/evals-create-eval)
