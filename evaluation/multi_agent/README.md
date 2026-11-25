# Multi-agent evaluations

Three independent development suites contain **20 conversations each**, with an initial question and one follow-up: inventory, distribution, and coordinator. The existing retail dataset is preserved. These are authored scenarios, not production traffic or a sealed holdout.

`scenarios.py` defines requests and acceptance criteria. `fixture.json` and `retail_fixture.sql` contain the same frozen source rows in the two runtime formats. Agent containers receive only these raw sources, never this package's references or judges. Runtime Golden Knowledge uses separate fixtures and examples.

`oracle.py` derives expected facts directly from raw rows using Decimal arithmetic and sets. It does not call the runtime query compiler or copy agent outputs. References include numeric bindings, criteria and illustrative prose for both turns; exact wording is not graded. The cutoff is `2026-04-01T00:00:00Z`. A table snapshot version, when used, is recorded separately.

Requests for more than 90 **complete days** use whole elapsed-day counts greater than 90; a 90.5-day unit is excluded while a 91-day unit is included. Separate contract tests cover these fractional-day boundaries, null costs, exact sale cutoffs and Unknown-center reconciliation. Optional background calculations are cached per immutable source and identity; callers receive independent copies.

## Run

Start the stack with the evaluation fixture configuration before executing these commands. All four agents must use the same two raw fixture files. The runner rejects a backend mismatch rather than silently evaluating a different source.

```bash
# Start agents against the independent raw evaluation fixtures.
uv run retail-stack up --backend fixture --evaluation-fixtures

# Publish all three 20-conversation datasets without calling any agents.
uv run --group evaluation python -m evaluation.multi_agent --publish-only

# Two conversations per suite, including both follow-ups.
uv run --group evaluation python -m evaluation.multi_agent \
  --suite smoke --max-cost-usd 5 --deadline-seconds 900

# All 60 conversations / 120 turns.
uv run --group evaluation python -m evaluation.multi_agent \
  --suite all --max-cost-usd 40 --deadline-seconds 7200

# A focused rerun creates a new experiment and retains earlier attempts.
uv run --group evaluation python -m evaluation.multi_agent \
  --suite inventory --only scenario-05,scenario-19 \
  --max-cost-usd 3 --deadline-seconds 600
```

The local stack's signing key authenticates test identities. Requests go through real A2A HTTP endpoints. Every conversation has its own context; the follow-up reuses that context with a fresh per-prompt allowance. A separate run ceiling covers concurrent agent requests and independent judges. Unknown usage retains its full reservation. Limits cap execution; they do not guarantee completion.

`--backend bigquery` independently captures raw tables across all brands at one version and forwards that snapshot timestamp to agents. All servers must already be configured for BigQuery. Reference capture is bounded to 1,000,000 rows and 500 MB billed per source query; exceeding either bound aborts instead of truncating. The primary reproducible baseline uses the frozen fixture.

For complete process inspection of public synthetic TheLook data, start with `RETAIL_STACK_TRACE_MODE=synthetic uv run retail-stack up --backend bigquery`, then run the evaluation with `--backend bigquery`. Ordinary startup defaults to metadata-only tracing. Select different cases per role with `--only inventory/scenario-05,coordinator/scenario-08`. A source switch selects a separate persisted conversation/report profile.

## Grades and Phoenix

The independent answer judge extracts values from exact answer excerpts. Code compares them with oracle facts and verifies attribution. The judge separately checks unsupported claims, uncertainty, scope, temporal consistency, and task coverage using actual evidence. Grader-only background facts also constrain optional numerical assertions, so an incorrect tool aggregation cannot justify an extra wrong number. Their omission is allowed. A second tool-free judge evaluates observable tool use, delegation, recovery and completion; it cannot inspect hidden reasoning. Neither judge treats runtime approval as proof of correctness.

The answer judge receives the published answer, authorized prior context, actual tool observations and selected evidence. Superseded candidate answers and reviewer verdicts are excluded from that input; full observations remain available to the trajectory judge and in local artifacts. Numerical checks accept independently verified disjoint Unknown subgroups when they reconcile to the required total, without requiring one table layout. Large live catalogs retain all required facts and select optional product background by explicitly mentioned entities; selection metadata is retained and missing coverage must remain unresolved.

Schema and skill observations receive distinct local O identifiers; actual result E identifiers are retained. The answer judge can cite only observed source IDs, and the process judge can cite only captured event IDs. These constraints prevent invented attribution; they do not prove the model's interpretation is correct.

Phoenix contains three stable datasets named `Inventory agent - 20 conversations`, `Distribution agent - 20 conversations`, and `Coordinator agent - 20 conversations`. Dataset Output contains references; experiment Output contains actual responses and grades. The runner prints experiment links before the first question. Traces use the `retail-multi-agent` project and are published as spans complete.

Each run saves source rows, requests, references, answers, full visible judge exchanges, grades, usage and a manifest under `.artifacts/multi-agent/<run-id>/`. Old runs are retained. `ERROR`, `UNJUDGEABLE`, unexecuted turns and publication failures cannot count as passes. The command exits with status 2 if any required result remains unsuccessful.

Reference calculations have contract tests. **Human reference review and human calibration of the judges remain pending.** Behavioral scenarios test reasoning around missing inputs and forbidden actions; they do not substitute for injected network-failure, cancellation or concurrent budget contract tests. Live Maps requests require credentials; unavailable Maps must produce an explicit limitation, never fabricated routes or weather. The fixture does not freeze external Maps observations.

The [validation report](RESULTS.md) preserves full and targeted runs, paired judge controls, automatic/manual disagreements and deployment hashes. The answer judge receives the published answer and actual tool evidence; superseded drafts and review verdicts belong to the separate trajectory judge. Observation IDs and event IDs are constrained to captured sources. Exact numerical grading accepts complete, correct disjoint partitions without requiring a particular table layout.

See [RESULTS.md](RESULTS.md) for preserved baseline scores, manual inspections, evaluator defects and candidate reruns. A high supported-claim score is not proof of hallucination absence: the initial automatic judge missed substantive overclaims detected during manual inspection.

Completed assistant inspections appear in Phoenix as separate `Initial / Assistant inspection` and `Follow-up / Assistant inspection` scores. They are labeled LLM-origin and are not human calibration. To validate mappings or republish the documented historical inspections without changing automatic grades:

```bash
uv run --group evaluation python -m evaluation.multi_agent.inspections --dry-run
uv run --group evaluation python -m evaluation.multi_agent.inspections
```

This importer covers only the completed reports bundled with this implementation. New runs need their own independently inspected report and explicit mapping; it does not copy an earlier run's verdict to a new answer.

## Full-access workspace revision

All 60 conversations now run under the same workspace identity and include every brand. Former
persona-access refusal scenarios now require supported all-brand answers. Independent Decimal/set
oracles and optional-claim controls include the full captured dataset; the capture SQL has no brand
allowlist. Historical captures keep their original references and scores. New definitions have not
been live-run or human-reviewed merely because the offline reference checks pass.
