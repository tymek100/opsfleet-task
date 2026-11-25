# Local multi-agent implementation

> Historical configuration note (2026-11-25): demo users and assigned-brand permissions described below are superseded by [full dataset access](FULL_DATASET_ACCESS.md). Current commands have no `--user` option. Historical findings and captures retain their original scope.

Status: implemented and running on BigQuery. The full fixture baseline, targeted rechecks and live validation are complete. Remaining semantic errors are documented below and in Phoenix. This checklist tracks execution of [the architecture proposal](LOCAL_A2A_RETAIL_AGENTS_PLAN.md). Existing retail conversations and Phoenix history remain intact.

## Scope and decisions

- Four independently deployable Google ADK services: retail, inventory, distribution and coordinator.
- A2A transports reviewed answers, evidence, limitations, conversation context and usage. The existing complete analyst runtime remains the execution boundary.
- The coordinator chooses specialist calls dynamically. Specialists do not recursively delegate. All model calls, tool calls and reviews have bounded execution.
- Only distribution uses external MCP: Google's managed Maps Experience endpoint, with route/weather tools and explicit failure when credentials or data are unavailable.
- A2A Inspector supplies the GUI, Agent Cards and protocol inspection. Phoenix supplies traces, evaluation datasets and experiments.
- Each new role receives 20 independent two-turn evaluation scenarios. References and grading code stay outside agent images and prompts.
- Initial reproducible evaluations use independently calculated fixture references. Live BigQuery and Maps checks are reported separately; synthetic success is not a claim of live integration success.

## Execution checklist

### 1. Verify contracts and dependencies

- [x] Inspect existing runtime, tool boundaries, budget accounting and evaluation integration.
- [x] Check installed ADK and official A2A/MCP/Inspector interfaces.
- [x] Confirm model credentials, BigQuery ADC and existing Phoenix availability without exposing secrets.
- [x] Verify the actual BigQuery inventory and distribution schema. Two bounded, scoped live aggregate queries succeeded.
- [x] Record Maps as unavailable pending `GOOGLE_MAPS_API_KEY`; the native MCP protocol is tested with an isolated local server.

### 2. Shared runtime and A2A

- [x] Add runtime extension points for role prompts, tools, skills and budget creation; retain retail behavior.
- [x] Implement authenticated, scoped A2A services and discoverable cards.
- [x] Persist conversation ownership, terminal tasks and idempotency; isolate follow-up contexts. Interrupted requests are not automatically replayed.
- [x] Propagate business as-of, warehouse snapshot and root deadline to specialists; keep actual reporting time separate.
- [x] Reserve child cost allowances before delegation and settle measured usage once; keep unknown costs reserved.
- [x] Enforce cancellation, timeout, no recursive delegation and bounded parallel child calls. A real HTTP/SSE cancellation test passes.
- [x] Validate specialist scope/time and remap evidence IDs with source provenance; review the combined final answer.
- [x] Propagate trace context and capture sanitized input/output/status with distinct role span names.

### 3. Domain agents and knowledge

- [x] Inventory: scoped products, inventory records and modeled unsold stock at the business cutoff.
- [x] Distribution: scoped center attribution, inventory distribution, missing-center reconciliation and facility locations.
- [x] Maps: MCP discovery, allowlist, argument validation, timeout, attribution and explicit unavailable results. Provider content remains ephemeral.
- [x] Coordinator: role discovery, dynamic delegation, evidence combination and explicit limitations.
- [x] Add role instructions, runtime skills for each new agent.

### 4. Evaluation

- [x] Create 20 questions and 20 follow-ups for each new role with independent reference facts and acceptance criteria.
- [x] Cover numerical correctness, scope isolation, temporal semantics, uncertainty, unsupported claims and follow-up behavior.
- [x] Include Maps-unavailable and local MCP transport cases separately from live Maps validation.
- [x] Publish three clearly named Phoenix datasets with reference outputs.
- [x] Run scenarios through real A2A services, save immutable local artifacts, grade answers and inspect failures.
- [x] Recheck observed failures after fixing runtime boundaries, role guidance and evaluation defects.
- [x] Record pass/fail/error results and unresolved limitations honestly; runtime approval is not an evaluation grade.

### 5. Containers, GUI and documentation

- [x] Build four runtime images without evaluation references or secrets.
- [x] Start services, Inspector and the existing Phoenix through Compose; bind public ports to loopback.
- [x] Open the GUI at a fixed localhost URL with automatic Alice authentication for all four agents, including browser refresh and renewed sessions.
- [x] Verify cards, GUI catalog, authenticated chat, follow-up context and trace visibility.
- [x] Run focused boundary tests and existing retail regression checks: 486 passed, five external-service pytest checks deselected. Actual Docker/A2A/BigQuery/Phoenix validation is recorded separately.
- [x] Document startup, chat, evaluation, credentials, shutdown and actual validation results.

## Acceptance evidence

Completion requires running services and observable evaluation results, not only source files. Each unresolved dependency is recorded below with its exact effect. The final validation report will include commands, dataset/experiment links, failed scenarios and live integration status.

- Deployment: `.artifacts/agents/images.json` and `verification.json` contain the image IDs, fixture hashes and catalog checks.
- Full baseline: `.artifacts/multi-agent/a2a-20261124T191812Z-f59d6715/`, 60 conversations / 120 turns, bounded by $40 and 7,200 seconds.
- [Evaluation findings](../../evaluation/multi_agent/RESULTS.md) retain the initial smoke failures and the discovered false-positive judge result. Corrected optional-claim controls were checked against the observed bad answer and an independent valid answer before the full baseline.
- Fixed a provider timeout that remained active while ADK ran completion review; a regression test proves review can consume its reserved time.
- Baseline completed in 1,632 seconds at $21.279905 accounted cost. Automatic grades: 115 PASS, four FAIL, one ERROR. Manual review found additional unsupported assertions, so these scores do not establish hallucination absence.
- Candidate fixes include a provenance-based public-facility coordinate exception, strict age thresholds, stock/source semantics and isolated persistence profiles for changed data sources.
- Targeted fixture runs completed 42 and 18 further turns. Original failures, regrades and judge controls remain separate immutable artifacts.
- Live BigQuery run: `.artifacts/multi-agent/a2a-20261124T202152Z-276d3486/`, six conversations / 12 turns on one physical warehouse snapshot. All requested numbers were correct; automatic grades were 12 PASS, while assistant inspection was nine PASS and three FAIL.
- Live complete-day aging distinguishes five fractional-day boundary units: 4,635 units older than 90 complete days versus 4,640 older than 90 elapsed days. The independent oracle and runtime were checked against this distinction.
- Ruff and targeted Pyright checks passed. The final running stack has four A2A services, Inspector on port 8080 and Phoenix on port 6006, with source-profile isolation and inactive Maps.
- Phoenix contains 192 separately identified assistant-inspection annotations across the baseline and three later runs. Each was read back for verification; automatic grades remain unchanged. These are explicitly LLM-authored, not human reviews.

## Known dependencies

- Maps is intentionally inactive for this deployment, as requested by the user. The client, local MCP protocol tests and explicit unavailable behavior are implemented; authenticated Google Maps calls are not claimed as verified.
- A2A SDK 0.3.26 is selected for compatibility with installed ADK 2.12 and Inspector's supported protocol versions. A future protocol-major upgrade needs separate interoperability tests.
- Existing Phoenix is reused; no datasets, experiments, volumes or old traces are deleted.
- Automatic reviewers still miss some unsupported explanatory clauses. Three live coordinator follow-ups imprecisely restated stock membership, made an unsupported causal denial about weather, or described modeled inventory as physical on-hand stock. These are recorded failures, not hidden behind automatic passes. Human reference review and human judge calibration remain pending; no sealed holdout was used.

## Primary references

- [ADK A2A](https://google.github.io/adk-docs/a2a/)
- [A2A Python SDK](https://github.com/a2aproject/a2a-python)
- [A2A Inspector](https://github.com/a2aproject/a2a-inspector)
- [Maps Experience agent tools](https://developers.google.com/maps/ai/maps-experience-agent-tools)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Phoenix tracing](https://arize.com/docs/phoenix/learn/tracing/how-tracing-works)
