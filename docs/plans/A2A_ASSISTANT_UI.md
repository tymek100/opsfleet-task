# A2A 1.0 and assistant-ui implementation

Status: implemented and verified. Research verified on 2026-11-25. Work proceeds in the order below; checkboxes record completed verification, not intentions.

## Outcome

Replace the default Inspector chat with a local assistant-ui application. Users select Coordinator, Retail, Inventory, or Distribution, ask questions, continue conversations, and read formatted Markdown tables. All four existing services use the latest stable Python A2A SDK (1.3.1 at research time), implementing protocol 1.0. Agent decisions, reviewed completion, tool permissions, per-request budgets, and Phoenix tracing remain in the existing services.

## Research and decisions

- [A2A Python releases](https://github.com/a2aproject/a2a-python/releases/tag/v1.3.1): SDK 1.3.1 is the latest stable release found. SDK and protocol versions are different: this release implements protocol 1.0.
- [SDK migration guide](https://github.com/a2aproject/a2a-python/blob/v1.3.1/docs/migrations/v1_0/README.md): protobuf models replace Pydantic protocol types; message parts, enum values, card interfaces, request handlers, serialization, and HTTP routes change.
- [assistant-ui A2A runtime](https://www.assistant-ui.com/docs/runtimes/a2a/overview) and [client API](https://www.assistant-ui.com/docs/runtimes/a2a/client-and-hooks): use the actual React A2A adapter against protocol 1.0. Verify the installed package and its HTTP transport rather than assuming JSON-RPC compatibility.
- [Markdown rendering](https://www.assistant-ui.com/elements/markdown-text): render the agent's approved Markdown, including tables. Formatting is presentation; the model still chooses the answer structure.
- Local deployment follows the Sites skill's local-only workflow. No external hosting or cloud UI account is needed.

## Architecture

The browser loads a React/TypeScript application from the existing local GUI port. A same-origin Python gateway serves compiled assets, the four-agent catalog, and approved A2A routes. Credentials stay server-side. The gateway forwards to the selected service; coordinator delegation remains service-to-service A2A. Phoenix retains its current trace/evaluation role. Inspector remains a separate optional debugging interface.

The UI offers an agent list, conversation list, new conversation, Markdown answers, horizontally scrollable tables, copy/export controls, agent details, elapsed seconds with a Thinking indicator, cancellation, and explicit failure states. Conversation IDs belong to a selected agent and data profile. Changing agents cannot silently reuse another agent's context. Persisted UI history must retain the context needed for follow-ups without storing credentials or ephemeral Maps evidence.

## Contracts to preserve

- Publish final answer content only after runtime review. Status updates are not unreviewed answers.
- Preserve original user instructions and signed delegation metadata separately from evidence.
- Preserve workspace bearer authentication for user requests and signed service authentication for delegation. Never expose either secret to JavaScript.
- Preserve server-side budget/deadline enforcement, idempotent request IDs, task cancellation, trace propagation, and report authorization.
- Keep existing data profiles, reports, Phoenix history, and evaluation references. Migrate old task records without deleting volumes.
- Render tables without changing their values, inferring currency, or automatically printing every query result. Escape CSV exports appropriately.
- Keep the default local workflow plug-and-play: one stack startup command, then a browser URL, with no pasted credentials.
- Run offline and scripted integration checks first; any live smoke request must be explicitly bounded. Do not run the paid evaluation suites as part of this migration.

## Phase 1 — Baseline and compatibility

- [x] Inspect the current dependency versions, A2A client/server/store, Docker catalog, and GUI.
- [x] Verify upstream stable SDK release and assistant-ui's protocol requirement.
- [x] Inspect installed SDK migration APIs and assistant-ui packages; record exact frontend versions.
- [x] Confirm ADK and evaluation dependencies resolve with the new SDK.
- [x] Identify every old protocol assumption in runtime, CLI, evaluation tools, tests, and docs.

Exit: selected packages resolve and migration scope is recorded before frontend work.

## Phase 2 — Upgrade the protocol first

- [x] Pin SDK 1.3.1 and update the Python lockfile.
- [x] Replace old protocol types and serialization with the supported protobuf APIs.
- [x] Expose native protocol 1.0 Agent Cards and the HTTP transports required by our Python client and assistant-ui.
- [x] Update the Python A2A client, request metadata, streaming parser, errors, and cancellation.
- [x] Adapt authentication middleware to all new routes while retaining signature verification over the received request body.
- [x] Adapt task storage and migrate/read legacy 0.3 task records safely; preserve context and request records.
- [x] Verify replay protection, follow-up context, task lifecycle, cancellation, and caller isolation.
- [x] Update CLI and evaluation transport assumptions without changing evaluation questions or references.
- [x] Run focused transport/auth/storage tests and resolve regressions before starting the UI.

Exit: all four services and existing Python callers work with protocol 1.0 in offline integration tests.

## Phase 3 — Local GUI gateway

- [x] Retain the old Inspector gateway separately for optional debugging.
- [x] Serve a stable four-agent catalog with clear names and descriptions.
- [x] Proxy only allowlisted service routes with server-side bearer credentials; preserve SSE without buffering.
- [x] Enforce local Host/Origin boundaries, bounded requests, safe errors, and no arbitrary proxy targets.
- [x] Rewrite public card interface URLs to the same-origin gateway without altering agent capabilities.
- [x] Provide conversation persistence scoped to browser session, agent, and backend/data profile; redact Maps-derived content before persistence.
- [x] Test secret isolation, route allowlisting, browser boundaries, streaming, and persistence.

## Phase 4 — assistant-ui frontend

- [x] Create a dedicated `web/` React/TypeScript package with pinned dependencies and a lockfile.
- [x] Use assistant-ui primitives and its A2A adapter; do not add an extra LLM or agent loop in the UI.
- [x] Build a clear agent list with the coordinator selected initially; show agent capabilities in a details panel.
- [x] Implement new/resumed conversations, safe switching, and separate histories per agent.
- [x] Render reviewed Markdown with readable headings, links, lists, tables, code, and horizontal overflow.
- [x] Add table copy/CSV download without regenerating values; avoid spreadsheet formula execution in exports.
- [x] Show elapsed seconds and animated Thinking dots independently of transport progress.
- [x] Wire Stop to cancellation and distinguish canceled, incomplete, and failed outcomes.
- [x] Keep UI loading, offline, and empty states useful; support keyboard navigation and narrow screens.
- [x] Add focused frontend tests for table rendering, exported values, agent switching, and follow-up state.

## Phase 5 — Docker and documentation

- [x] Build static frontend assets in a Node stage and serve them through the Python gateway.
- [x] Exclude secrets, evaluation references, build caches, and node_modules from Docker context.
- [x] Add GUI storage and health checks; retain all existing agent/Phoenix volumes.
- [x] Make assistant-ui the default local URL and document optional Inspector access.
- [x] Update startup/status output, README, QUICK_START, architecture, and infrastructure docs.
- [x] Record exact installed versions and any migration limitations in this plan.

## Phase 6 — Verification and local rollout

- [x] Run Python lint, formatting, type checks, and the relevant offline test suite.
- [x] Run frontend type checks, tests, and production build.
- [x] Exercise real HTTP/SSE with scripted agents: initial question, follow-up, table, rejection/incomplete outcome, cancellation, and agent switching.
- [x] Verify browser rendering and responsive layout with screenshots if local browser tooling is available.
- [x] Rebuild/start the existing Docker stack using its current backend and data profile.
- [x] Check all four 1.0 cards, health endpoints, GUI assets, gateway routes, and Inspector compatibility.
- [x] Verify no model/warehouse credentials appear in browser responses or frontend assets.
- [x] Record test results, limitations, and the working local URL. Commit/push only when requested.

## Acceptance checks

1. Opening the local GUI shows all four agents without configuration or token entry.
2. Selecting an agent sends a native A2A 1.0 request to that service.
3. A follow-up uses the same selected agent and conversation context; reload/resume retains that context.
4. A reviewed answer containing two Markdown tables displays two readable tables with exact values.
5. Canceling a run stops its server task; unavailable services produce a recoverable error.
6. Analyst/reviewer behavior and Phoenix tracing remain exercised through the existing runtime.
7. Existing reports and histories survive the upgrade; old task formats are handled explicitly.
8. Runtime knowledge retrieval remains removed, and no new paid evaluation run is triggered.

## Execution notes

- Baseline: clean `main` at `02eca07`; existing stack uses A2A protocol 0.3 with SDK 0.3.x and Inspector on localhost:8080.
- Live backend and data-profile selection will be read from the saved stack configuration before rollout.

- Installed frontend versions: `@assistant-ui/react` 0.15.38, `@assistant-ui/react-a2a` 0.2.55, `@assistant-ui/react-markdown` 0.14.26, React 19.3.1, Vite 8.3.8. Exact transitive versions are recorded in `web/package-lock.json`; Docker builds with pinned Node 24.
- Native transport and gateway verification: 59 focused tests passed. The full offline Python suite passed: 619 tests, five external-service checks deselected. Frontend type-check/build and three focused rendering/export tests passed. Subsequent browser and Docker rollout checks passed; final totals are recorded below.
- Legacy tasks are converted through the SDK's official compatibility converter on read; contexts and request records retain their original schema. No volume is deleted or reassigned.

## Final verification

- Python: **622 passed**, five external-service tests deselected; Ruff lint/format, Pyright and `git diff --check` passed. No live evaluation suite was run.
- Frontend: TypeScript and production build passed; **3 Vitest checks** and **2 Playwright scenarios** passed. The browser scenarios exercise native HTTP/SSE, table values, reload/follow-up context, separate agent histories, mobile navigation, cancellation reaching the server, safe failures, and explicit incomplete outcomes.
- Browser screenshots were inspected at desktop and 390px mobile widths. Local artifacts: `web/test-results/workspace-desktop.png`, `answer-tables.png`, `answer-mobile.png`, and `docker-workspace.png` (ignored by Git).
- Docker: four agent services, assistant-ui gateway and optional Inspector gateway are healthy. All four cards advertise protocol 1.0 with JSON-RPC and HTTP+JSON. The existing BigQuery profile `bigquery-2fd4edddd4dca7f2ddd1` and named agent/Phoenix volumes are retained. The native task listing successfully reads the four pre-existing coordinator tasks in that profile.
- Local endpoints: assistant-ui `http://localhost:8080`, optional Inspector `http://localhost:8081`, Phoenix `http://localhost:6006`. Inspector successfully opened a native 1.0 coordinator connection without a model call.
- Browser responses were checked against the actual workspace token. The GUI image receives no model or warehouse credential files. Its Docker context excludes secrets and evaluation references.
- The initial Linux build found missing optional dependencies in the macOS-generated npm lock. Regenerating the lock from the pinned Node 24 image fixed `npm ci`; the Docker build now succeeds. Local frontend development also verifies allowed loopback origins and rejects foreign origins.
- Native incomplete Maps responses are redacted in task status/history as well as artifacts. Presentation history selects its leaf message by parent links, so out-of-order user/assistant writes cannot resume from the wrong message.

## Limits and operating notes

- Answer streaming means A2A task progress followed by the reviewed artifact. Unreviewed model tokens are not published.
- Completed conversations resume after reload. Keep the tab open while a request runs, or use Stop before leaving; recovering an in-flight browser stream after reload is not implemented. Server deadlines still bound the work.
- GUI history uses its own browser cookie and volume. Clearing cookies loses browser access to those conversations. Old Inspector UI sessions are not imported; existing agent contexts, reports and tasks remain stored.
- The full model/warehouse evaluation suites were deliberately not rerun. Verification used scripted model boundaries and real protocol/gateway/browser execution. **No paid model or warehouse queries were made for this migration.**
- The production bundle is approximately 260 KB gzipped; Vite reports an advisory chunk-size warning. Two existing Python dependency warnings remain (Starlette TestClient's httpx deprecation and ADK's experimental function-schema feature).
- Changes are local and have not been committed or pushed; neither was requested for this task.
