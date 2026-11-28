# Quick start

1. Run `uv sync` from the repository root.
2. Configure `.env` from `.env.example` without overwriting existing credentials. Set `GEMINI_API_KEY`, `GOOGLE_CLOUD_PROJECT` and the desired model.
3. For BigQuery, run `gcloud auth application-default login`.
4. Start a terminal conversation with `uv run agent-chat coordinator`, or run `uv run retail-stack up --backend bigquery` and open http://127.0.0.1:8080.

For synthetic warehouse data, set `BACKEND=fixture` in `.env`, or pass `--backend fixture` to `retail-stack up`. This does not disable Gemini billing.

Foundry is optional for chatting. Follow [Cloud connections](docs/cloud-connections.md) to enable tracing, and [evaluation instructions](docs/evaluation.md) to run independent assessments. No Phoenix container or separately hosted specialist is required.
