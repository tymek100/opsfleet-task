# Audit remediation — 25 October 2026

This records implementation following the [original audit](audit-2026-10-25.md). The original remains a historical record of the baseline. No claim about a “top 1%” ranking can be substantiated.

## Changes and evidence

| Finding | Implementation | Verification and remaining limits |
|---|---|---|
| A1: response-category bypass | Schema, clarification, library and unsupported messages are fixed application text. All fresh evidence goes through the narrative gate regardless of the model's chosen category. | Real ADK-loop regressions inject an unsupported revenue claim into all four non-analysis categories; none publishes it. |
| A2: wrong period / incomplete answer | `intent.py` derives periods and required outputs independently of model plans. Requests must match before execution. Completeness requires monthly rows, both requested rankings and available ranking rows, report total/month/product evidence, and churn snapshots/comparison. | Wrong-quarter regression returns only corrected Q1 evidence. Independent tests reject total-only reports and missing rankings/rows. **Bounded English parsing, not general intent equivalence.** |
| A3: action and follow-up context | Typed intent retains analysis/action periods. Explicit “without actions” removes the action requirement. Missing years and ambiguous rollover require clarification. | Follow-up, year clarification, no-action report and period holdout tests. Arbitrary action scheduling and restart-resumed sessions remain unsupported. |
| A4: non-atomic save | One transaction stores report, audit and idempotency key. Identical save retries return the existing ID. | Injected audit failure leaves no report or key; retry succeeds exactly once, with one audit entry. |
| A5: diagnostics/storage failures | File logging degrades to in-memory diagnostics with a visible warning. Mutation auditing fails closed. Initialization and local I/O failures become controlled errors; client cleanup is protected. Plan-correction and empty-result diagnostic counts are application-enforced. | Actual log-file append failure still yields a validated answer. CLI storage failure gives an actionable message. Existing retry, deadline and deletion rollback tests remain passing. |
| A6: missing durable intent/version | Persisted answers contain minimized intent, source/prompt fingerprints and model/compiler/intent versions. Trace events include intent and version metadata. | Saved-report round-trip preserves intent and fingerprints; original questions and rejected model prose are not added to logs. Fingerprints identify bytes, not an archived deployment or full conversation replay. |
| A7: generic findings | Comparable adjacent totals expose deterministic volume and unit-value revenue contributions, rendered as arithmetic attribution. Existing churn denominator and premise checks remain. | Independent oracle: revenue 800 → 600, volume contribution +160 and unit-value contribution −360. This does not establish causes. Category decomposition, broader recommendations and business-user usefulness remain future work. |
| A8: executive UX / scenario isolation | Default output groups findings and retains definitions. `/details [REPORT_ID]` reveals Rich tables and diagnostics. Churn live test is independent of rankings/follow-up. Added independent period and adversarial completeness cases. | Renderer/CLI tests and three successful live tests covering four analytical turns. No executive-user study or statistical quality estimate was performed. |

The HLD now identifies the application answer-quality gate and selects a concrete production gateway-to-entitlement-execution-identity mapping with restricted safe views. This is a proposal; no production IAM was deployed.

## Checks actually run

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest --cov=retail_agent --cov-report=term-missing -q
uv build
uv run --locked pytest -m live --force-enable-socket -q -s tests/test_live.py
```

- Offline: **110 passed**, three live tests deselected; sockets disabled.
- Ruff and strict Pyright: passed.
- Coverage snapshot before the final definition-display adjustment: **87%** combined statement/branch coverage. The subsequent full offline suite also passed; coverage is not a business-correctness score.
- Source distribution and wheel built successfully.
- Live: **3 passed**, four analytical turns, **87.14 seconds** overall.
- ADK emits its existing experimental structured-response-schema warning. Tests do not suppress it.
- No GitHub push, hosted CI run, deployment, load test or human UX study was performed in this remediation.

### Live observations

Model: `gemini-3.5-flash`, actual Gemini and BigQuery, Alice's Calvin Klein scope. Times come from trace events; amounts are conservative reservations, **not invoiced charges**.

| Scenario | Queries | Model calls | Turn time | Reserved USD | Outcome |
|---|---:|---:|---:|---:|---|
| Top 10 by revenue and customer count, Q1 2026 | 2 | 2 | 17.70 s | 0.173979 | Validated |
| Same-quarter total and monthly follow-up | 2 | 3 | 35.94 s | 0.312235 | Validated |
| Q1 report with Q2 actions | 3 | 2 | 17.61 s | 0.167761 | Validated |
| Last-month churn premise check | 1 | 2 | 15.34 s | 0.150788 | Validated |

All four used the normal CLI runtime quality gate; none needed tool-free narrative repair. These are small-sample development observations. The follow-up exceeds the proposed 30-second simple-question target under current free-tier pacing; this does not establish production latency compliance.

After the live run, presentation was adjusted to keep effective metric definitions visible by default; the offline suite was rerun. No inference/query behavior changed afterward.

## Review and remaining limits

Start with `src/retail_agent/intent.py` for request/completeness checks, `quality.py` for evidence-bound metrics and rendering, `reports.py` for transactions, and `agent.py` for runtime enforcement. Regressions are in `tests/test_intent.py`, `test_agent.py`, `test_quality.py`, `test_reports.py` and `test_cli.py`.

The strongest remaining limitation is semantic breadth: an enumerated contract cannot prove that every arbitrary English question or subtle filter was interpreted correctly. Supported demo cases now have independent offline oracles and successful live checks. Production authentication, learning, persona publication and Golden retrieval remain design-only, as agreed.
