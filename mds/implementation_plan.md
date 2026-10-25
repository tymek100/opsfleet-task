# Implementation plan

> Implementation update: the prototype and reviewer documentation now live in `src/`, `tests/`, and [docs](../docs/README.md). This file preserves planning context; use the submission documents and evaluation report for current behavior and executed checks.


Status: planned, not implemented. The initial BigQuery CLI connection has been verified; Python application credentials, Gemini access, application behavior, and performance still need verification. Research and requirements work already performed must be counted honestly alongside implementation time.

## Objective and sources of truth

Deliver a small, reproducible retail analysis assistant and a detailed production design that demonstrate business understanding, engineering judgment, and observable correctness. A strong interview submission should be easy to run, inspect, and explain; no technology choice guarantees a ranking among candidates.

- [Original assignment](task/assignment.md): deliverables and prototype scope.
- [Client Q&A](q&a.md): confirmed decisions and unresolved questions.
- [Architecture](architecture_proposal.md): components, boundaries, and production behavior.
- [Research and quality strategy](1-percent.md): rationale, analytical pitfalls, evaluation ideas, and suggested time allocation.
- [Testing strategy](testing_strategy.md): fixtures, offline/live isolation, critical behavior matrix, property-based tests, and release evidence.

Client answers supersede proposed defaults. Keep implementation status and test evidence separate from intended behavior.

## Questions that do not block starting

Send these in the next client update; continue independent implementation while waiting:

1. Request the referenced FAQ and confirm the submission deadline.

Roi confirmed on 22 October 2026: use existing data for ad-hoc, user-triggered analysis, with no cron-based analysis. Brand access-revocation handling is out of scope. These answers supersede the earlier daily-ingestion and historical-content reauthorization proposals.

Other remaining questions are recorded in the Q&A. Do not repeat answered questions or make low-impact implementation choices depend on another client response.

## Technology decisions

| Area | Choice and verification |
|---|---|
| Runtime | Supported Python version compatible with the chosen dependencies; record and test that version |
| Agent | Google ADK with one conversational agent and explicit application services; pin a tested release |
| Model | Configurable current stable Gemini candidate; verify account availability, ADK/tool compatibility, correctness, latency, and cost before pinning the default |
| Analytics | BigQuery Python client; SQLGlot for parsing a restricted SQL subset and application-owned authorization checks |
| Contracts | Pydantic schemas for tools, evidence, and report structures; schema validity does not establish authorization or truth |
| Local persistence | SQLite with transactions for sessions, reports, and confirmation actions |
| CLI | Typer and Rich, with clear scope, progress, errors, and explicit confirmation |
| Configuration | Environment variables and local `.env`; BigQuery ADC configured externally; no secrets in source or logs |
| Dependencies | `pyproject.toml` and `uv.lock`; a documented pip route or exported pinned requirements for reviewers |
| Verification | pytest for meaningful behavioral checks; Ruff for lint/format checks; small live integration and model-evaluation suites |
| Test support | pytest-asyncio for async paths, pytest-cov for branch visibility, and a few Hypothesis properties; keep provider calls outside generated/offline tests |
| Observability | Structured JSON events locally; OpenTelemetry/Google Cloud observability in the production design |

Use maintained, compatible versions. Prefer a stable model that passes the task evaluations over a newer model selected only by release date. Do not add orchestration layers, vector services, or deployments without a concrete need.

## Phase 1 — Foundation and first safe end-to-end question

- [ ] Create the package, CLI entry point, configuration schema, dependency lock, and secret-free `.env.example`.
- [ ] Define two demo managers with different brand assignments and a CEO role; label authentication as simulated.
- [ ] Verify Python ADC can submit a bounded BigQuery job, independently of CLI login. Verify Gemini key/model access without exposing credentials.
- [ ] Define the initial allowed SQL relations, columns, functions, and constructs. Make unsupported queries fail closed.
- [ ] Implement one question end to end: user request → Gemini/tool call → scoped SQL validation → BigQuery dry run/execution → privacy validation → evidence-backed answer.
- [ ] Add minimal correlation logging, execution limits, and tests for permitted versus forbidden scope alongside the first query path.

**Exit evidence:** one live dynamic query succeeds; a cross-brand or prohibited-column query is rejected before execution; captured model requests contain no prohibited customer data. A fixture-only result must be labelled as such.

## Phase 2 — Analytical coverage and conversation

- [ ] Document revenue status rules, distinct-customer counting, churn population/denominator/as-of semantics, UTC boundaries, and override handling.
- [ ] Implement separate top-10 product rankings by revenue and customer count, with deterministic ties and explicit periods.
- [ ] Investigate monthly churn using authorized-brand purchase history; verify a spike before explaining it and distinguish measured drivers from hypotheses.
- [ ] Generate a Q1 report with Q2 actions, clarifying the year when material. Connect actions to evidence and proposed success measures.
- [ ] Support meaningful follow-ups, product comparisons, time-based metrics, customer rankings by permitted ID, and safe schema explanations.
- [ ] Keep customer-ID rankings separate from aggregate state demographics; inspect filters and intermediate results as well as final columns.
- [ ] Attach safe evidence with scope, definition version, period, result values, query/job identifiers, and freshness. Render factual numeric tables from validated data.

**Exit evidence:** all three priority scenarios and a follow-up for each work on defined test cases; fresh SQL produces the answers rather than hardcoded demo responses. Additional required capabilities have representative checks.

## Phase 3 — Private reports and permanent deletion

- [ ] Separate report generation from explicit saving. Persist owner, conversation, underlying brand scope, definitions, and durable sanitized evidence.
- [ ] Enforce owner checks for listing, reading, matching, and deleting; CEO analytics permissions do not override report privacy.
- [ ] Implement deterministic deletion preview/confirm/cancel with owner-bound exact IDs and versions, expiry, and a single-use token.
- [ ] Recheck and consume/delete transactionally. Handle replay, changed records, and new matches without expanding the confirmed set.
- [ ] Hard-delete approved report content and application-managed copies; retain content-free audit events. Document backup semantics in the HLD.
- [ ] Keep access-revocation lifecycle handling out of scope as confirmed by Roi; retain normal brand authorization and report ownership checks.

**Exit evidence:** inspect actual database state after valid confirmation, cancellation, wrong-owner attempts, expiry, replay, and stale preview. “Deleted” text alone is not evidence.

## Phase 4 — Bounded failures, cost, and diagnostics

- [ ] Share model calls, SQL attempts, tokens, bytes, retries, and time budgets across each turn; default the configurable question budget to USD 1 under the documented cost-accounting assumption.
- [ ] Estimate query work before execution and set maximum bytes billed on the actual job. Bound model output and result volume.
- [ ] Repair syntax errors within limits; check genuine empty results without silently changing scope or the requested period.
- [ ] Handle provider 429s, timeouts, and transient errors with bounded backoff. Recover BigQuery job status using job IDs to avoid duplicate submission.
- [ ] Keep the conversation usable after failure; report save failures accurately and keep confirmation independent of model availability.
- [ ] Record sanitized event relationships, versions, job IDs, timings, token/byte usage, retries, and outcomes. Exclude raw PII, secrets, and hidden reasoning.

**Exit evidence:** controlled faults produce bounded behavior, understandable errors, and a trace explaining the failure. Label fault injection in the demo.

## Phase 5 — Evaluation and production explanation

Follow the [testing strategy](testing_strategy.md); start boundary tests in earlier phases instead of postponing all testing until this phase. Default CI is offline and credential-free; live BigQuery and Gemini runs require explicit activation and spend limits.

- [ ] Build distinguishing synthetic cases: shared customers, mixed-brand orders, repeated purchases, returns, ties, empty periods, and temporal boundaries.
- [ ] Test query scope escapes, malicious instructions, prohibited data in outbound model requests, ownership, deletion, budget rejection, and recovery.
- [ ] Use BigQuery integration checks for dialect/job behavior; local SQLite tests alone cannot establish BigQuery compatibility.
- [ ] Evaluate answer relevance, numeric correctness, evidence coverage, limitations, useful actions, and conversational clarity. Do not use an LLM judge as the sole correctness/security oracle.
- [ ] Record actual case counts, failures, model versions, trial counts, timings, and costs; disclose limits of small samples.
- [ ] Complete the HLD for all eight requirements: identity, on-demand access to existing data, trust boundaries, tools, stores, protocols, scaling, learning, evaluation, retention, and failure paths.
- [ ] Describe non-technical persona editing with automatic quality-gated publication and rollback; retain a separate human editor/reviewer workflow for Golden examples.
- [ ] Define the Trio format and seed a few clearly illustrative examples. Implement lightweight retrieval only after mandatory checks pass.

**Exit evidence:** a requirement-to-code/test/design map, an evaluation report grounded in executed checks, and a production design consistent with client answers.

## Phase 6 — Reviewer experience and interview preparation

- [ ] Verify installation in a clean environment using external credentials; test the documented commands, including the pip route if supplied.
- [ ] Separate credential-free tests from live checks. Make configuration diagnostics useful without exposing values.
- [ ] Create editable architecture sources and document previews: draw.io/SVG for the main HLD, Mermaid for request and confirmation flows. These artifacts are planned, not yet created by this document.
- [ ] Keep a concise README with setup, scope, representative transcript, evaluation results, limitations, and links to the detailed design.
- [ ] Check tracked artifacts for credentials, local databases, and sensitive logs before public submission.
- [ ] Rehearse a short demo covering business questions, follow-up context, a denied request, explicit saving, deletion cancellation/confirmation, and controlled recovery.
- [ ] Prepare explanations of the SQL, security boundary, framework choice and actual experience, a significant tradeoff, and what would improve with another week.

**Exit evidence:** another person can follow the documented setup and inspect the claims. Publication and client messaging remain separate user-authorized actions.

## Completion standard and scope control

Finish mandatory functionality, focused evidence, and all required design sections before optional polish. Keep the advertised SQL subset and limitations explicit. Do not cut privacy, authorization, confirmation, recovery, or observability to make room for additional features.

The final submission should demonstrate correct business answers, rules enforced independently of model behavior, exact confirmed deletion, understandable failures, and reproducible results. These are the acceptance criteria for quality; newer technology alone is not an acceptance criterion.

## Planned Python tooling

Use uv for dependency management, Ruff for linting/formatting, and Pyright in strict mode for type checking. Keep dependency declarations and all tool settings (including pytest and coverage) in `pyproject.toml`, with resolved versions in `uv.lock`. Use a modular `src/retail_agent` layout. See [Python development](python_development.md) for the proposed commands and module boundaries. This is a plan only; tooling and application scaffolding have not been added.
