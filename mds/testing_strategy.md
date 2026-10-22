# Testing strategy

Status: planned. The application has not been implemented, so this document does not claim that application tests exist or pass. Build meaningful tests alongside each implementation phase, not as a large cleanup exercise at the end.

The objective is confidence in correct analysis, enforced boundaries, and reliable state changes. Use [client Q&A](q&a.md) as the specification and [implementation_plan.md](implementation_plan.md) for delivery order. The installed `python-testing-patterns` skill provides pytest techniques; `retail-agent-evaluation` defines the agent-specific checks.

## Tools and isolation

| Tool | Purpose |
|---|---|
| pytest | Parameterized behavior tests, fixtures, clear failures |
| pytest-asyncio | Actual async agent/provider workflows; configure mode and fixture scopes explicitly |
| Hypothesis | A small set of generated invariants and deletion-state sequences |
| pytest-cov | Branch-coverage visibility to identify untested policy/failure paths |
| Standard-library mocks and small fake adapters | Controlled model/query responses, exceptions, usage, and retries |
| Temporary SQLite databases | Exercise real persistence, ownership, transactions, and deletion |
| Typer test runner | CLI input, cancellation, confirmation, errors, exit behavior |
| Ruff | Formatting/linting; useful but not a substitute for behavior tests |

Use supported versions in the development dependency group and lock them. Do not install dependencies merely because they appear in an upstream example. Prefer an injected clock and sleeper to real delays; use timezone-aware UTC timestamps. pytest supplies isolated temporary paths and environment patching through its [built-in fixtures](https://pytest.org/en/stable/builtin.html). For async fixtures, follow the configured [pytest-asyncio mode](https://pytest-asyncio.readthedocs.io/en/stable/concepts.html).

Default test execution must not read the real `.env`, discover ADC, submit provider requests, or modify the user's reports. Inject explicit test configuration, use temporary directories/databases, and block outbound network for offline tests. An unexpected provider call must fail the test, not silently succeed using local credentials. Patch dependencies at the external boundary while keeping real permission, query-admission, and persistence logic in the tested path.

## Three complementary layers

| Layer | What it establishes | What it cannot establish |
|---|---|---|
| Offline deterministic and generated tests | Policy decisions, metric logic, actual report-store effects, failure budgets, controlled workflow behavior | Gemini answer quality or BigQuery dialect correctness |
| Opt-in BigQuery integration | Real job submission, SQL dialect/semantics, dry runs, bytes limits, result contracts | Stable expected totals from a changing public dataset |
| Opt-in Gemini/ADK evaluations | Real tool selection, multi-turn behavior, answer usefulness, observed cost/latency | Universal safety or production reliability from a small sample |

Use registered markers such as `live_bigquery` and `live_model`, plus explicit enabling options/configuration. A marker alone does not prevent network calls. Live tests should be skipped by default and unavailable unless deliberately enabled. Once a required live run is enabled, missing credentials or unexpected skips must fail that run or be reported as incomplete—not turn a release gate green.

## A small fixture that exposes real errors

Create synthetic rows representing the four required table schemas, with hand-derived expected values. Include:

- Two brands, two managers with distinct permissions, and a CEO.
- A customer buying across brands and an order containing both brands.
- Repeat purchases by the same customer, tied products, a sale price different from retail price, cancelled and returned items, and documented order/item status cases.
- Purchases just before, at, and after period/churn boundaries; no prior customers; a customer returning after inactivity; a later purchase that must not affect an earlier as-of calculation.
- State groups without individual-to-state output; synthetic name/email/address/coordinate canaries for outbound-data checks.
- Reports owned by different users, matching entity names, changed versions, and new matching reports created after preview.

Expected results must be calculated independently of the implementation. Do not call the same metric/authorization helper to build the expected answer: that can reproduce the bug in the oracle.

For actual BigQuery semantic tests, prefer small read-only SQL fixture relations using typed arrays/CTEs and an injected trusted relation resolver over creating permanent cloud datasets. Validate this harness without weakening the production gateway. A fake BigQuery result or a SQLite-translated query does not prove generated BigQuery SQL is correct. Use the public dataset for bounded smoke queries with schema/invariant assertions, not permanently hardcoded row totals.

## Critical test matrix

| Area | Representative tests | Evidence to assert |
|---|---|---|
| Brand authorization | Mixed-brand orders, shared customers, nested relations, CTE shadowing, unions, forged CEO claim | Actual executor input remains scoped; unauthorized queries never execute |
| Privacy | PII in projection, predicate, function, alias, user prompt, tool error, Golden text | Captured model requests, outputs, stored reports, and logs contain no prohibited canaries; unresolved free-text detection limits remain documented |
| Geographic policy | Customer IDs combined with state; small groups under the configured proposed threshold | Block individual-state association before model access; policy threshold is configurable and not represented as a confirmed client number |
| Metrics | Sale versus retail price, repeated customers, join fan-out, zero denominator, time boundaries | Correct values at the correct grain, with definitions and scope |
| Multi-turn context | Change period/product, ask a ranking follow-up, switch demo users | Recompute affected evidence; no cross-user/scope history leakage; access-revocation lifecycle tests are out of scope per Roi |
| Report persistence | Generate without save, explicit save, owner/CEO read attempts, storage error | Accurate database state and truthful UI outcome |
| Confirmation | Cancel, wrong owner, expiry, replay, stale version, newly matching report | No unintended deletion; valid confirmation affects exactly the approved set |
| Atomicity | Failure during deletion transaction; two attempts to consume the same token | Rollback or exactly one committed effect, never partial unrelated loss |
| Recovery | Syntax error then repair, repeated error, genuine empty result, 429, timeout, malformed tool output | Bounded attempts, unchanged permissions, usable session, clear outcome |
| Cost | Over-budget dry run, long output request, retry after partial spend | No new call exceeding the configured admission budget; usage reconciled |
| Job recovery | Submission timeout followed by status lookup | Reuse known job identity; do not duplicate the query blindly |
| CLI | Help, missing configuration, user cancel/interrupt, confirmation input | Understandable output, appropriate exit behavior, no secret printing |

Inspect full serialized provider requests, including history and tool/error messages, not only the final prompt. Use synthetic canaries, never real customer PII, in privacy tests. Test runtime authentication separately from the explicit local identity simulation.

## Property-based tests with a concrete purpose

After the explicit boundary tests work, add a few [Hypothesis properties/stateful checks](https://hypothesis.readthedocs.io/en/latest/stateful.html):

1. Adding purchases for a completely unauthorized brand leaves a manager's scoped result unchanged. Fix the reporting period/as-of clock so unrelated changes cannot shift the query window.
2. Reordering the same input rows leaves aggregate results unchanged. Repeated eligible purchases by an existing customer can increase revenue but cannot increase that product's distinct-customer count.
3. For accepted generated query variants, resolved base relations remain in the allowed relation set and protected parameters remain application-owned. Generate from the supported grammar; do not claim random strings prove the entire SQL language safe.
4. Generate report actions such as save, preview, cancel, advance time, confirm, and replay. Compare real temporary SQLite state with a small independent reference model. No sequence may delete another owner's report or an unconfirmed report.

Limit example counts/runtime for the normal suite. Preserve minimized failures as readable regression cases. Full state-machine fuzzing is a useful extension, not a reason to delay explicit confirmation tests or mandatory deliverables.

## Model evaluation

Use the three client-priority scenarios plus held-out paraphrases, a follow-up, an ambiguous period, a false churn-spike premise, and an unsupported/unauthorized request. Keep these separate from Golden seed examples.

Grade objective claims with code and controlled evidence: numbers, scope, period, evidence references, and actual saved/deleted state. Evaluate relevance, clarity, limitations, and action-item usefulness with a written rubric and human review; an LLM judge can supplement this, with its own failures and cost recorded. Accept multiple valid SQL/tool paths when they satisfy the required safety and outcome checks.

Do not automatically retry a failed evaluation until it passes and report only the successful attempt. Record every trial, model ID, prompt/configuration versions, token/byte usage, elapsed time, and errors. Treat latency targets as goals until measured, and never infer p95 production reliability from a few calls. A fresh public dataset may produce different values; use a fixed as-of period and preserve sanitized evidence for interpretation.

## CI and release gates

The normal pull-request workflow installs the lockfile, runs Ruff, and executes offline tests including focused property tests and branch-coverage reporting. It must work without cloud secrets. Do not expose credentials to untrusted PR code. Keep live checks in a separately enabled trusted workflow or a documented local command with an explicit overall spend cap and bounded queries; include evaluator calls in that budget.

For the submission, require:

- All mandatory deterministic authorization/privacy/confirmation/failure tests pass. Do not hide known failures behind skips or expected-failure markers.
- Any critical guard regression is shown to be detectable: temporarily remove a brand check, ownership condition, or token-consumption check in an isolated test copy and confirm the relevant test fails. Targeted mutation checks are sufficient; a full mutation-testing platform is optional.
- Actual BigQuery and Gemini priority-scenario runs have recorded results, or any unexecuted checks are explicitly reported as limitations. No “passed” claim for a run that never happened.
- Reviewer setup succeeds in a clean environment, with external credentials and a credential-free offline suite.

Coverage percentage is diagnostic, not the release criterion. Inspect uncovered branches in access control, confirmation, and failure handling; avoid tests that merely mirror implementation or trivial code. After relevant checks pass, broaden only for new changes or unresolved risks.

## Suggested layout and sequencing

Planned layout, to adjust to real module names during implementation:

```text
tests/
  conftest.py
  fixtures/
  unit/             # Pure policy and metric contracts
  integration/      # Real local store + workflow, fake provider boundary
  properties/       # Small Hypothesis invariants/state model
  live/             # Explicit opt-in BigQuery and Gemini checks
evals/
  cases/            # Held-out questions and grading criteria
```

Start with one allowed analysis and one prohibited analysis in phase 1. Add metric fixtures with analytical capabilities, persistence/confirmation tests with reports, and fault tests with retries. Add the highest-value properties once those services exist. Finish with real integrations, model evaluations, clean setup, and a concise results document linked from the README.

## Planned Python tooling

Use uv for dependency management, Ruff for linting/formatting, and Pyright in strict mode for type checking. Keep dependency declarations and all tool settings (including pytest and coverage) in `pyproject.toml`, with resolved versions in `uv.lock`. Use a modular `src/retail_agent` layout. See [Python development](python_development.md) for the proposed commands and module boundaries. This is a plan only; tooling and application scaffolding have not been added.
