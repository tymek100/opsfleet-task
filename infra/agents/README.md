# Local agent stack

Four separate agent images expose A2A endpoints. The coordinator delegates to the retail, inventory and distribution specialists. A2A Inspector provides Agent Cards, chat and protocol inspection; the existing Phoenix service retains traces and evaluations.

## Start and stop

From the repository root:

```bash
uv run --locked retail-stack up --backend fixture
uv run --locked retail-stack status
uv run --locked retail-stack chat
```

Fixture mode uses local data but still calls Gemini. For TheLook on BigQuery, configure `GEMINI_API_KEY` and `GOOGLE_CLOUD_PROJECT` in `.env`, authenticate with `gcloud auth application-default login`, then use `--backend bigquery`.

For live Maps, enable the **Maps Experience agent tools** service for the key's Google Cloud project, configure its API access, and set `GOOGLE_MAPS_API_KEY` in `.env`. Follow [Google's setup instructions](https://developers.google.com/maps/ai/maps-experience-agent-tools#configure-llms-to-use-the-mcp-server), then rerun `retail-stack up` with the desired backend to refresh the distribution-only credential file. The client uses Streamable HTTP at `https://mapstools.googleapis.com/mcp`. This integration exposes route and weather tools with bounded Essentials options; it does not enable every Maps capability. Without a valid key, the agent reports Maps as unavailable.

For the independent multi-agent evaluation suite, start with `--backend fixture --evaluation-fixtures`. This adds read-only mounts containing only raw warehouse rows. Expected answers, grading criteria and oracle calculations remain outside every agent container. Return to ordinary runtime data by running `up` without `--evaluation-fixtures`; source profiles keep their persisted conversations, tasks and reports separate.

`up` prepares configuration, starts or reuses `infra/phoenix/compose.yaml`, builds four images, and waits for healthy services. It preserves Phoenix history and per-agent volumes. Stop only the agent stack with:

```bash
uv run --locked retail-stack down
```

Phoenix remains available on [localhost:6006](http://127.0.0.1:6006). Agent Compose reuses its `phoenix_default` network; do not start the agent Compose project alone before Phoenix exists. The startup helper can also be invoked directly:

```bash
uv run --locked python infra/agents/start.py --backend fixture
```

## Inspector

Open [localhost:8080](http://localhost:8080). The coordinator opens automatically; select any specialist in the shared catalog to inspect its Agent Card or chat directly. Authentication is configured automatically for the local workspace, including after a page reload. All agents can analyze every brand; brand-specific questions use explicit analytical filters. No login link, token copying or Bearer configuration is required.

The `gui` service fronts the pinned Inspector in hosted mode on a loopback-only port. It selects the coordinator at startup and supplies the workspace access token server-side when connecting to an approved catalog endpoint. Submitted cards and credential overrides are discarded; the real card is fetched from its configured service. Host and origin checks restrict browser access to the local GUI. Inspector is internal to Compose and returns only masked credential references. Browser sessions stay separate. The gateway adapts session cookies for local HTTP while retaining `HttpOnly` and `SameSite=Strict`; this configuration is a local demo, not a public deployment.

Inspector receives no Gemini key, so its optional host agent is disabled; conversations use this application's coordinator. `retail-stack token` remains available for manual API clients but is unnecessary for the GUI.

`catalog.json` is the approved endpoint source. Startup generates an AI Catalog at `.artifacts/agents/inspector-catalog.json`; Inspector loads it with `--catalog`. Cards advertise Docker service addresses, which Inspector resolves from its backend. Host callers use the loopback ports below and must explicitly select the external transport URL rather than following an internal card URL.

| Service | Host endpoint | Internal endpoint |
|---|---|---|
| Retail | `http://127.0.0.1:8001` | `http://retail:8000` |
| Inventory | `http://127.0.0.1:8002` | `http://inventory:8000` |
| Distribution | `http://127.0.0.1:8003` | `http://distribution:8000` |
| Coordinator | `http://127.0.0.1:8004` | `http://coordinator:8000` |
| Agent GUI | `http://localhost:8080` | `http://gui:8080` |
| Inspector backend | Internal only | `http://inspector:8080` |

All published ports bind to loopback. Override the corresponding `RETAIL_PORT`, `INVENTORY_PORT`, `DISTRIBUTION_PORT`, `COORDINATOR_PORT` or `INSPECTOR_PORT` environment variable if necessary.

## Images, credentials and persistence

The Dockerfile has four agent targets and a separate GUI gateway target, with distinct image tags. All use the `retail_insight` package: agents start through `retail_insight.a2a.server`, which selects the role from `agents/registry.py`; the GUI starts through `retail_insight.interfaces.gui`. Each role owns a directory under `agents/` and shares the ADK runtime and review implementation. Only runtime source and `knowledge/` enter the build context. Evaluation datasets, grader references, `.env`, credentials, artifacts and Git history are excluded. Python dependencies are installed from `uv.lock` without installing the repository evaluation package.

Startup creates `.artifacts/agents/secrets/` with owner-only directory permissions. Individual bind-mounted files are readable by the non-root container user; keep the enclosing directory private. The model profile reaches all four agents, warehouse credentials reach only specialists, and Maps credentials reach only distribution. The GUI mounts only the workspace access token; it has no signing key, model key or warehouse credentials. The coordinator and Inspector have no warehouse credentials. Secrets are loaded from read-only files, never baked into images. Re-running `up` refreshes provider profiles without rotating existing local service keys.

New chats and reports use the `workspace` owner. Existing report ownership is retained; earlier owners' reports and conversation history are not reassigned or merged.

Each agent owns its own `/data` named volume. Within it, persistent state lives under `/data/<backend>/<source-profile>/`: A2A tasks and conversation context in `a2a.sqlite3`, saved reports in `reports-v2.sqlite3`, and diagnostic events in `events-v2.jsonl`. The startup helper fingerprints the all-brand access mode, backend and source dataset; fixture profiles also include hashes of both the domain JSON and retail SQL. Normal fixtures, evaluation fixtures and BigQuery therefore do not reuse each other's answers, task cache or reports. The `workspace-all-brands-v1` access mode selects fresh state, so old persona-specific conversations cannot leak their implicit filters into new chats. Former profiles and their reports remain stored without relabeling or merging. Changing fixture contents or the warehouse source dataset selects another directory; returning to the same profile restores its history.

Always switch data sources through `retail-stack up`, which calculates the profile and rebuilds by default. Existing running images do not acquire this isolation from a source-code edit, and legacy files directly under `/data` are retained without automatic migration. Direct Compose/server launches must supply an appropriate `RETAIL_STACK_DATA_PROFILE`/`RETAIL_DATA_PROFILE`; the fallback `default` does not fingerprint source changes within one backend. A source profile is a storage boundary, not a frozen BigQuery snapshot; a conversation separately pins its business cutoff and optional snapshot timestamp.

Containers run as UID 10001 with a read-only root filesystem and a temporary `/tmp`. Do not use `down --volumes` unless you intend to discard all source profiles' task/report history. The public `/health` response contains service role, backend, a fixture content hash when applicable and Maps credential availability; it contains no credential values or local paths.

After successful startup, `.artifacts/agents/images.json` records the four immutable image IDs,
selected data profile and catalog hash so an evaluation can retain the exact deployed build.

Inspector is pinned to official `v1.0.0-alpha.2` and immutable digest `sha256:699e8eab72b5f46f9ce95d10acc7be51a99c3d9f3649da009e534889871083e2`. The published release is amd64-only; Docker Desktop emulates it on Apple Silicon. Its verified CLI supports A2A 0.3/1.0 and shared AI Catalogs. See the [official Inspector documentation](https://github.com/a2aproject/a2a-inspector/tree/v1.0.0-alpha.2) and [AI Catalog specification](https://ai-catalog.io/specification/).
