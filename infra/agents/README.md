# Local agent stack

Four separate agent images expose A2A endpoints. The coordinator delegates to the retail, inventory and distribution specialists. assistant-ui provides agent selection, conversations and Markdown tables; the existing Phoenix service retains traces and evaluations.

## Start and stop

From the repository root:

```bash
uv run retail-stack up --backend fixture
uv run retail-stack status
uv run agent-chat coordinator
```

Fixture mode uses local data but still calls Gemini. For TheLook on BigQuery, configure `GEMINI_API_KEY` and `GOOGLE_CLOUD_PROJECT` in `.env`, authenticate with `gcloud auth application-default login`, then use `--backend bigquery`.

For live Maps, enable the **Maps Experience agent tools** service for the key's Google Cloud project, configure its API access, and set `GOOGLE_MAPS_API_KEY` in `.env`. Follow [Google's setup instructions](https://developers.google.com/maps/ai/maps-experience-agent-tools#configure-llms-to-use-the-mcp-server), then rerun `retail-stack up` with the desired backend to refresh the distribution-only credential file. The client uses Streamable HTTP at `https://mapstools.googleapis.com/mcp`. This integration exposes route and weather tools with bounded Essentials options; it does not enable every Maps capability. Without a valid key, the agent reports Maps as unavailable.

For the independent multi-agent evaluation suite, start with `--backend fixture --evaluation-fixtures`. This adds read-only mounts containing only raw warehouse rows. Expected answers, grading criteria and oracle calculations remain outside every agent container. Return to ordinary runtime data by running `up` without `--evaluation-fixtures`; source profiles keep their persisted conversations, tasks and reports separate.

`up` prepares configuration, starts or reuses `infra/phoenix/compose.yaml`, builds four images, and waits for healthy services. It preserves Phoenix history and per-agent volumes. Stop only the agent stack with:

```bash
uv run retail-stack down
```

Phoenix remains available on [localhost:6006](http://127.0.0.1:6006). Agent Compose reuses its `phoenix_default` network; do not start the agent Compose project alone before Phoenix exists. The startup helper can also be invoked directly:

```bash
uv run python infra/agents/start.py --backend fixture
```

## Chat with a specific agent

```bash
uv run agent-chat coordinator
uv run agent-chat retail
uv run agent-chat inventory
uv run agent-chat distribution
```

In an interactive terminal, type `/` to show `/help`, `/new`, `/exit` and `/quit`. Keep typing to filter with matching characters highlighted, then use arrows and Enter or Tab to select. Selection fills the input; press Enter again to run the command. Piped input supports the same commands without the dropdown.

Each command connects to the named A2A service and retains conversation context for follow-ups. `/new` starts a new conversation; `/exit` ends the chat. Use `--context-id ID` to resume a conversation with the same agent. `--max-cost-usd` and `--deadline-seconds` bound each request.

The running services already send traces to Phoenix under `retail-multi-agent`; the chat client needs no tracing flag. `retail-agent chat` remains the standalone retail CLI, where tracing is enabled with `--phoenix`. The older `retail-stack chat --agent ROLE` command remains compatible, defaulting to coordinator.

## Web GUI and optional Inspector

Open [localhost:8080](http://localhost:8080). The sidebar selects Coordinator, Retail, Inventory or Distribution; each has its own conversation history. Answers come from the existing reviewed runtime. Tables scroll horizontally and support copy/CSV download. The Thinking indicator shows elapsed seconds; Stop cancels the remote task. GUI requests have a $1 admission cap and 180-second deadline, within service limits. These are per-prompt limits, separate from the evaluation suite's $5 cap.

The `gui` service serves the React application and proxies native A2A 1.0 HTTP+JSON/SSE through fixed catalog targets. Its gateway injects the workspace bearer credential server-side and rewrites Agent Cards to same-origin URLs. Host/Origin checks protect the loopback interface. Browser sessions use an opaque HttpOnly, SameSite=Strict cookie; conversations are isolated by that cookie, selected agent, and source profile. Clearing cookies removes browser access to earlier GUI conversations. Maps-derived turns are redacted before persistence. This is a local workspace UI, not a public multi-user deployment.

To include the optional protocol debugger:

```bash
uv run retail-stack up --backend bigquery --inspector
```

Open [localhost:8081](http://localhost:8081) for Inspector. Its separate gateway configures the approved catalog and workspace token automatically. The Inspector host agent remains disabled because our coordinator handles delegation. `retail-stack token` is only for manual API clients.

`catalog.json` is the approved endpoint source. Startup generates an AI Catalog at `.artifacts/agents/inspector-catalog.json`; Inspector loads it with `--catalog`. Cards advertise Docker service addresses, which Inspector resolves from its backend. Host callers use the loopback ports below and must explicitly select the external transport URL rather than following an internal card URL.

| Service | Host endpoint | Internal endpoint |
|---|---|---|
| Retail | `http://127.0.0.1:8001` | `http://retail:8000` |
| Inventory | `http://127.0.0.1:8002` | `http://inventory:8000` |
| Distribution | `http://127.0.0.1:8003` | `http://distribution:8000` |
| Coordinator | `http://127.0.0.1:8004` | `http://coordinator:8000` |
| assistant-ui | `http://localhost:8080` | `http://gui:8080` |
| Inspector GUI (optional) | `http://localhost:8081` | `http://inspector-gui:8080` |
| Inspector backend | Internal only | `http://inspector:8080` |

All published ports bind to loopback. Override the corresponding `RETAIL_PORT`, `INVENTORY_PORT`, `DISTRIBUTION_PORT`, `COORDINATOR_PORT` `INSPECTOR_PORT` (the existing main GUI port override), or `INSPECTOR_DEBUG_PORT` environment variable if necessary.

## Images, credentials and persistence

The Dockerfile has four agent targets, an assistant-ui gateway target, and an optional Inspector gateway target. A pinned Node 24 build stage runs `npm ci` and compiles `web/`; the final GUI container serves static assets with Python. All use the `retail_insight` package: agents start through `retail_insight.a2a.server`, which selects the role from `agents/registry.py`; the GUI starts through `retail_insight.interfaces.gui`. Each role owns a directory under `agents/` and shares the ADK runtime and review implementation. Only runtime/frontend source, packaged demo data and dependency/build files enter the build context; node_modules and local frontend outputs are excluded. Evaluation datasets, grader references, `.env`, credentials, artifacts and Git history are excluded. Python dependencies are installed from `uv.lock` without installing the repository evaluation package.

Startup creates `.artifacts/agents/secrets/` with owner-only directory permissions. Individual bind-mounted files are readable by the non-root container user; keep the enclosing directory private. The model profile reaches all four agents, warehouse credentials reach only specialists, and Maps credentials reach only distribution. The GUI mounts only the workspace access token; it has no signing key, model key or warehouse credentials. The coordinator and Inspector have no warehouse credentials. Secrets are loaded from read-only files, never baked into images. Re-running `up` refreshes provider profiles without rotating existing local service keys.

New chats and reports use the `workspace` owner. Existing report ownership is retained; earlier owners' reports and conversation history are not reassigned or merged.

The GUI owns `gui-data`, containing browser presentation history in `/data/gui/conversations.sqlite3`. Each agent owns its own `/data` named volume. Within it, persistent state lives under `/data/<backend>/<source-profile>/`: A2A tasks and conversation context in `a2a.sqlite3`, saved reports in `reports-v2.sqlite3`, and diagnostic events in `events-v2.jsonl`. The startup helper fingerprints the all-brand access mode, backend and source dataset; fixture profiles also include hashes of both the domain JSON and retail SQL. Normal fixtures, evaluation fixtures and BigQuery therefore do not reuse each other's answers, task cache or reports. The `workspace-all-brands-v1` access mode selects fresh state, so old persona-specific conversations cannot leak their implicit filters into new chats. Former profiles and their reports remain stored without relabeling or merging. Changing fixture contents or the warehouse source dataset selects another directory; returning to the same profile restores its history.

Always switch data sources through `retail-stack up`, which calculates the profile and rebuilds by default. Existing running images do not acquire this isolation from a source-code edit, and legacy files directly under `/data` are retained without automatic migration. Direct Compose/server launches must supply an appropriate `RETAIL_STACK_DATA_PROFILE`/`RETAIL_DATA_PROFILE`; the fallback `default` does not fingerprint source changes within one backend. A source profile is a storage boundary, not a frozen BigQuery snapshot; a conversation separately pins its business cutoff and optional snapshot timestamp.

Containers run as UID 10001 with a read-only root filesystem and a temporary `/tmp`. Do not use `down --volumes` unless you intend to discard all source profiles' task/report history. The public `/health` response contains service role, backend, a fixture content hash when applicable and Maps credential availability; it contains no credential values or local paths.

After successful startup, `.artifacts/agents/images.json` records the four immutable image IDs,
selected data profile and catalog hash so an evaluation can retain the exact deployed build.

Inspector is pinned to official `v1.0.0-alpha.2` and immutable digest `sha256:699e8eab72b5f46f9ce95d10acc7be51a99c3d9f3649da009e534889871083e2`. The published release is amd64-only; Docker Desktop emulates it on Apple Silicon. Its verified CLI supports A2A 0.3/1.0 and shared AI Catalogs. See the [official Inspector documentation](https://github.com/a2aproject/a2a-inspector/tree/v1.0.0-alpha.2) and [AI Catalog specification](https://ai-catalog.io/specification/).

## Frontend development and verification

Use Node 24 LTS and Python 3.12. From the repository root:

```bash
npm ci --prefix web
npm run --prefix web build
npm run --prefix web test
cd web
npx playwright install chromium
npm run test:e2e
```

Browser tests launch disposable scripted A2A services and the real gateway on port 8765. They do not call Gemini, BigQuery, or Phoenix. Screenshots and failure traces are written to `web/test-results/`. The offline Python suite also covers authentication, task storage, cancellation, gateway isolation and privacy. See [the implementation checklist](../../docs/plans/A2A_ASSISTANT_UI.md) for migration verification.

With the Docker gateway running, `npm run --prefix web dev` serves the frontend at
`http://127.0.0.1:5173` with a local API proxy. Only that development origin is translated;
foreign browser origins remain rejected. Keep the tab open during a request or use Stop before
leaving. Completed conversations resume after reload; automatic recovery of an in-flight
browser stream is not implemented.
