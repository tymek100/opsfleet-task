# LangGraph migration

Date: 27 November 2026. Status: implemented and verified locally. Cloud deployment/publication not performed.

One application hosts a coordinator and retail, inventory and distribution specialists. Each inherits a custom StateGraph model/tool/review loop. No LangChain create_agent, ADK or inter-agent A2A transport remains. Preserve SQL safeguards, evidence, report authorization, independent evaluation references, the CLI and assistant-ui. Replace Phoenix with Foundry observability (the initial LangSmith step was superseded by the Google/Azure connector decision). Expose one descriptive Agent Card and prepare the compiled workflow for the official Foundry Responses hosting adapter.

## Checklist

- [x] Inspect current code and official LangGraph, LangSmith and Foundry documentation.
- [x] Implement the custom graph loop, model boundary and reviewed completion.
- [x] Migrate agents to local specialist subgraphs with bounded shared budgets.
- [x] Preserve context isolation, cancellation and trusted evidence handling.
- [x] Migrate tracing and evaluation publication; see [Google/Foundry connectors](GCP_FOUNDRY_CONNECTORS.md) for the final destination.
- [x] Replace CLI/UI A2A transport with one application API.
- [x] Add workflow export, Agent Card and Foundry hosting/deployment files.
- [x] Remove obsolete ADK, A2A and Phoenix runtime/deployment dependencies.
- [x] Adapt regression tests, run offline checks, build UI and verify Docker startup.
- [x] Write setup instructions and state remaining cloud verification requirements.

## Validation and boundaries

Use scripted providers with real compiled graphs and existing independent fixtures. No paid Gemini calls by default. Cloud publication requires configured credentials; Azure deployment is not part of local verification. Check weekly Codex remaining usage during sustained work; stop at 60%.

An Agent Card describes capabilities; it does not deploy code. Do not advertise unsupported A2A endpoints. The optional Foundry hosting package may depend on LangChain, but application graphs must never use a prebuilt agent factory.

## Sources

- https://docs.langchain.com/oss/python/langgraph/quickstart
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/langsmith/annotate-code
- https://docs.langchain.com/langsmith/evaluate-llm-application
- https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/langchain-hosted-agents

## Verified result

- 521 Python regression tests passed, including real LangGraph loops, concurrent local delegation, reviewed completion, independent references, LangSmith serialization/publication, browser ownership, and the official Foundry Responses adapter with a follow-up.
- Pyright: zero errors; Ruff and `git diff --check`: clean.
- Frontend unit tests and production build passed; all four browser scenarios passed (tables, follow-ups, agent switching, persistence, deletion, cancellation and interrupted streams).
- Independent diagnostic dataset: 43 valid cases, nine fixtures, 40 judge controls. Human review and sealed holdout remain absent.
- Built and started `retail-workflow-app-1`; health, UI, catalog and Agent Card return HTTP 200 at localhost:8080. The runtime contains LangGraph/LangSmith and no ADK/A2A/Phoenix package.
- Stopped the old project's A2A/Inspector/Phoenix containers. Their volumes and historical artifacts remain intact; old sessions are not imported into the new runtime.
- Gemini/BigQuery inference and Azure/LangSmith cloud publication were not invoked for migration verification. Gemini token spend: $0. One SDK-related DNS attempt was blocked by pytest-socket; no external test connection was allowed.
- Last weekly Codex check: 76% remaining, above the requested 60% threshold.

## Remaining external setup

Google inference and Foundry telemetry/evaluation are configured separately; see
[cloud connections](../cloud-connections.md). The hosted-agent adapter is prepared,
but the application has not been deployed to Azure. The verification results above
record the original framework migration, before the subsequent connector work.
