# Local Phoenix

Status: Phoenix 22.0.1, client 3.7.0, OTel 0.16.0, exporter 1.42.1 and Google ADK instrumentor 1.1.9 validated with ADK 2.12.0. Two fake-provider turns were exported and retrieved after a container restart: two separate prompt traces, one conversation, four provider attempts, and no prompt/answer/credential canaries in metadata mode.

```bash
docker compose -f infra/phoenix/compose.yaml up -d
# GUI: http://127.0.0.1:6006
docker compose -f infra/phoenix/compose.yaml down
```

The named `phoenix-data` volume persists SQLite data. `down` preserves it; `down -v` deletes it. The unauthenticated service is bound only to `127.0.0.1:6006`. Automatic telemetry, external-resource fetches and model-price updates are disabled. Do not add provider credentials to this container.

Enable normal CLI tracing with `uv run --locked --group evaluation retail-agent chat --user alice --phoenix` or add `--phoenix` to `retail-agent ask`. Tracing is opt-in. Normal application traces contain metadata; synthetic evaluation content requires explicit synthetic capture. Every outgoing span passes an exporter allowlist. Raw automatic ADK payloads, exception descriptions, hidden thoughts and confirmation tokens are excluded. Export failure does not alter answers, and shutdown has a bounded wait. Budget records remain authoritative; only `retail.provider_attempt` spans retain usage attributes to avoid duplicate ADK accounting.

Dependencies are installed with `uv sync --locked --group evaluation`. The OTel pin intentionally preserves ADK's compatible SDK version. The tracing API is `configure_tracing(endpoint, project=..., mode="metadata"|"synthetic")`; close its returned session in a `finally` block. Collector ingestion is asynchronous, so immediately querying a new project can briefly return 404.

References: [Phoenix configuration](https://github.com/Arize-ai/phoenix/blob/main/src/phoenix/config.py), [Phoenix self-hosting](https://arize.com/docs/phoenix/self-hosting/deploying-phoenix), [OpenInference Google ADK instrumentation](https://github.com/Arize-ai/openinference/tree/main/python/instrumentation/openinference-instrumentation-google-adk).
