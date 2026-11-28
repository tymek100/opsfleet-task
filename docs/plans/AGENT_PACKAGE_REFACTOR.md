> Historical plan or validation record. The current implementation is documented in [architecture.md](../architecture.md); ADK, A2A and Phoenix instructions below are superseded.

# Agent package refactor

Updated: 2026-11-25.

## Objective

Consolidate application code into `src/retail_insight/`. Make retail, inventory, distribution and coordinator implementations discoverable in separate agent directories while sharing execution, review, transport and integrations. Preserve analytical behavior, authorization, storage formats, CLI command names and A2A endpoints.

## Implementation

- [x] Move application modules into one package and update imports.
- [x] Give each role an explicit `agent.py`, `tools.py`, `prompt.md` and `skills/` directory.
- [x] Replace runtime role switches with explicit agent construction through `agents/registry.py`.
- [x] Separate shared runtime, review, tools, integrations, A2A and interfaces.
- [x] Update packaging, console entrypoints, Docker module paths and fixture paths.
- [x] Update architecture and setup documentation.
- [x] Verify offline contracts, integration tests, lint, formatting and type checks.
- [x] Verify installed console entrypoint targets and runtime resource inclusion in the built wheel.
- [x] Smoke-test each CLI command and A2A entrypoint after composition changes.

The wheel build and editable installation pass offline. The wheel includes all four agent definitions, prompts, role skills, shared review/writing skills and runtime fixtures, with no legacy source packages. Implementation and verification are complete. The four agent containers and GUI were rebuilt and started on the existing BigQuery backend. Agent Cards, service health, the GUI and Phoenix respond successfully. Phoenix history and agent volumes were retained.

## Ownership

Each agent selects its own prompt, skills and tools. `runtime/` handles the ADK loop, state and budgets. `review/` implements the shared completion protocol. `integrations/` owns BigQuery, Maps MCP, Phoenix and local storage. `a2a/` exposes the selected agent as a service. `interfaces/` supplies the CLI and GUI gateway.

Shared skill composition preserves existing availability; relocating guidance does not change its instructions. Independent evaluation datasets remain in `evaluation/` and outside agent images.

## Validation scope

Use deterministic model doubles and fixture data to check query/review/revision behavior, agent tool selection, A2A authentication, persistence and cancellation. Check package resources and every command entrypoint after the move. Live model evaluations are not required to establish a structural refactor and must not be represented as newly run without execution evidence.

## Verification results

- `uv run --group evaluation pytest -q`: 512 passed, 5 live/Phoenix tests deselected; two dependency warnings.
- Ruff lint and formatting pass; Pyright reports zero errors and warnings.
- The existing `retail-agent`, `retail-stack` and `retail-eval` commands load; A2A server module startup works with the new package.
- The built wheel contains each agent's definition, tools, prompt and skills, plus shared review resources and warehouse fixtures. Legacy Python packages are absent.
- Docker Compose rebuild/start passes for retail, inventory, distribution, coordinator and GUI. All four Agent Cards and health endpoints respond; GUI and Phoenix return HTTP 200.
- No live model evaluation was rerun for this structural change.

Regression coverage includes agent capability separation and the distinction between the frozen warehouse business cutoff/snapshot and the operational clock used for timestamps and expiry. Prompt bodies and existing skill instructions were preserved.
