# Local workflow container

From the repository root, run `uv run retail-stack up --backend bigquery` and open http://127.0.0.1:8080. Use `--backend fixture` for synthetic warehouse rows; Gemini still requires a key and incurs charges.

One non-root container serves assistant-ui and all four local LangGraph agents. Configuration is prepared under `.artifacts/workflow`: the secret directory has mode 0700 and `runtime.env` has mode 0600. The original GCP ADC file is mounted read-only without copying it. The image uses your local UID/GID so it can read those files without broadening permissions. No secrets are copied into image layers.

`retail-stack status` reports health. `retail-stack down` stops the application without deleting its named storage volume. Re-run `up` after configuration or code changes. Foundry observability is external. Google retains inference and warehouse access; see [cloud connections](../../docs/cloud-connections.md). No local observability container is required.

The stack binds only to loopback. Its signed browser sessions are for a local workspace, not public internet authentication. Use the separate Foundry adapter for platform hosting; see [Foundry setup](../../docs/foundry.md).
