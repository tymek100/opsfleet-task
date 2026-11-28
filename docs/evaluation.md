# Testing and evaluation

The project separates software regression tests, the runtime reviewer and independent quality evaluation. They answer different questions.

| Layer | What it checks | Requires paid model calls? |
| --- | --- | --- |
| Offline tests | Graph routing, tools, SQL boundaries, budgets, cancellation, memory, GUI and publication contracts | No |
| Runtime reviewer | Whether a proposed answer is supported and satisfies the current request | Yes, part of each agent prompt |
| Independent evaluation | Numerical correctness, grounding, task completion, operations and observed trajectory | Yes, agents plus separate judges |

## Offline checks

```bash
uv sync
uv run pytest -q
uv run retail-eval validate
uv run ruff check src evaluation tests
cd web
npm ci
npm test
npm run build
npm run test:e2e
```

Tests use scripted provider responses with real compiled LangGraph loops and warehouse fixtures. They validate software behavior, not the quality of a live Gemini response. Tests block external sockets by default. Install `uv sync --group foundry` to include the optional Foundry adapter tests.

## Run a bounded evaluation

Configure Gemini and [Foundry](cloud-connections.md). Every evaluation command defaults to a **$5 shared cap** and rejects higher values. The cap includes agents, delegated specialists, independent judges and reference query costs where applicable. Unknown usage retains its reservation. A full suite may stop before completion; the command reports unfinished cases explicitly. The deadline covers setup and execution as well as grading admission.

A small retail smoke run:

```bash
uv run --group evaluation retail-eval run --suite smoke --allow-unreviewed   --max-cost-usd 1 --deadline-seconds 600
```

The authored retail suite contains **20 initial questions and 20 follow-ups**. It captures an independent BigQuery snapshot, runs each conversation and publishes an experiment:

```bash
uv run --group evaluation retail-eval run-conversations   --only scenario-01,scenario-03 --max-cost-usd 1 --deadline-seconds 600
```

Omit `--only` for all 20. The inventory, distribution and coordinator suites each contain 20 two-turn scenarios:

```bash
uv run --group evaluation retail-eval run-multi-agent   --suite smoke --backend fixture --max-cost-usd 1 --deadline-seconds 600

uv run --group evaluation retail-eval run-multi-agent   --suite all --backend fixture --max-cost-usd 5 --deadline-seconds 7200
```

`--suite inventory`, `distribution` or `coordinator` selects one role; `--only scenario-01` selects a focused case. These evaluations invoke local graphs directly, so Docker services are unnecessary. Fixture mode still calls Gemini. The full command runs 60 conversations when time and budget permit; the retail 20 are a separate command. Use `--backend bigquery` only with configured ADC and sufficient query allowance.

## Data and saved results

| Asset | Location |
| --- | --- |
| Authored retail scenarios | `evaluation/scenarios/manual_20.json` (case IDs are `scenario-01`, etc.; filename retained for compatibility) |
| Diagnostic pilot and controls | `evaluation/datasets/golden/` |
| Role scenarios and independent fixture/oracle | `evaluation/multi_agent/` |
| Retail conversation outputs, references and judgments | `.artifacts/manual/<run>/` |
| Role conversation outputs and judgments | `.artifacts/multi-agent/<run>/` |
| Diagnostic runs and append-only grades | `.artifacts/evaluation/<run>/` (configurable artifact root) |

Each run prints its exact directory. JSON artifacts retain prompts, answers, usage, evidence and grades; manifests record source/configuration hashes and snapshot information. Foundry reference datasets contain facts and criteria; separate result datasets contain actual generated answers and detailed grades. References are supplied only to graders, never to analysts or runtime reviewers.

The diagnostic pilot contains synthetic cases with independent Decimal/set calculations and paired judge controls. Authored scenarios are development data, not a sealed holdout. `--allow-unreviewed` acknowledges that references have code verification but await human review; it does not disable safety or correctness checks.

## Hallucinations and traces

The answer judge identifies atomic claims and links each to exact source excerpts. Code verifies the attribution, evidence IDs, numerical facts, rankings, set membership, follow-up binding and reconciliation against independent references. Unsupported explanations, causal claims or recommendations can fail grounding even when every displayed number is correct. Missing evidence and malformed judgments become unresolved/error outcomes, not successful grades.

A separate trajectory judge examines actual tool calls, observations, revisions and completion. It checks tool selection, argument quality, use of evidence, adaptation and progress. Multiple valid tool paths are accepted; it does not require one predetermined sequence and cannot infer hidden reasoning. Runtime approval is just another observed event.

The code checks deterministic facts; LLM judges assess semantic requirements. Neither guarantees absence of hallucinations. Human reference review, judge calibration against labeled controls, repeated live runs and a sealed holdout remain necessary before using the scores as a release gate.

## Regrade and compare

```bash
uv run retail-eval grade --run .artifacts/evaluation/<run> --code-only
uv run retail-eval grade --run .artifacts/evaluation/<run> --max-cost-usd 1
uv run retail-eval calibrate --max-cost-usd 1
uv run retail-eval compare <baseline-grade-directory> <candidate-grade-directory>
```

These commands operate on diagnostic artifacts. Regrading does not rerun the analyst. Hash checks reject modified or unrelated execution artifacts. Local artifacts remain available when Foundry uploads fail. Exit code `0` means required checks passed; `1` indicates evaluated failures; `2` indicates incomplete execution, unresolved checks or publication failure.

## Foundry publication

The agent, runtime reviewer and independent answer/trajectory judges still use
Google Gemini. Deterministic checks compare extracted facts with independent
references. Foundry receives versioned reference and result datasets, then runs a
`string_check` evaluator over resolved PASS/FAIL statuses. Its metric is named
**Independent check passed**; each result row identifies the conversation and the
original metric. This mirrors existing assessments without another LLM call.

ERROR, UNJUDGEABLE and non-applicable checks are retained in the full result dataset
but excluded from binary quality scoring. The local summary reports unresolved
checks and remains authoritative for the exit code. Human calibration is pending.

Traces are exported as operations finish. A completed suite publishes one cloud
evaluation containing its checks; it does not create an experiment for every chat
turn. The CLI prints the portal/report link and writes `foundry.json` beside local
artifacts. If Azure rejects publication, answers and grades remain local.

The $5 cap covers accounted Google model and BigQuery work. It is not an Azure
spending limit: telemetry ingestion, storage and evaluation infrastructure can have
separate charges. No Azure model grader is enabled automatically.

Prompt provenance is local: `prompts.json` snapshots exact instructions and SHA-256
hashes, also attached to spans. `uv run retail-eval export-prompts` prints these
snapshots without calling a hosted prompt registry.
