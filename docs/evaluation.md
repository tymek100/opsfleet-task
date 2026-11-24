# Testing and evaluation

The main Phoenix workspace contains **20 authored retail conversations**, each with an initial
question and a fixed follow-up. Controlled fixture evaluations and collector integration tests
use a separate instance. Run commands from the repository root.

## What is in Phoenix

Open [Datasets & Experiments](http://127.0.0.1:6006/datasets) and select
**Retail agent — 20 conversations**. Each of its 20 rows contains:

- Input: scenario ID (`scenario-01` through `scenario-20`), identity, initial question, and follow-up.
- Output: independent reference facts and behavioral criteria for the initial question and
  follow-up, plus source timestamps and hashes. These define expected answers without requiring
  identical wording or tables. For example, a revenue fact identifies the expected value,
  brand, period, metric, unit, and rounding tolerance.
- Metadata: scenario intent and provenance.

Experiment output contains the actual two answers, runtime status, trace links, and automatic
grades. Observed model answers are never copied into reference truth.

Questions come from [manual_20.json](../evaluation/scenarios/manual_20.json). They are authored
scenarios executed against the configured BigQuery warehouse, originally public TheLook sample
data. They are not captured production traffic.

On 2026-11-23 the workspace was reset at the user's request: eight experiments and their old
trace project were deleted, and the 20 case IDs changed from `manual-NN` to `scenario-NN`.
Dataset/example IDs and the four registered prompts were preserved. Earlier dataset versions
retain their original content. A full database backup and migration receipts are under
`.artifacts/phoenix/cleanup/20261123-scenarios/`; earlier local run artifacts remain unchanged.
The [historical review report](plans/manual-conversation-review.md) describes the archived runs.

The fresh [20-conversation baseline](http://127.0.0.1:6006/datasets/RGF0YXNldDo5/compare?experimentId=RXhwZXJpbWVudDox)
published all 40 answers: 37 answer grades are PASS and three are ERROR. The report-evidence
validator omits singular `evidence_id` fields, incorrectly rejecting observed IDs in
`scenario-17` follow-up and both `scenario-18` turns. Separately, the trajectory judge returned
incomplete event coverage for `scenario-05` and `scenario-13`. The run therefore exits 2 with
five unresolved checks; it is not a complete quality pass. Accounted cost was $5.1886.
Captures, diagnoses and API verification are under
`.artifacts/manual/conversations-baseline-20261123T161732Z-296c97ba/`.

**Tracing** uses one project, `retail-conversations-20`, recreated for fresh evaluations.
Roots have `Scenario` and `Automatic answer evaluation` annotations. Each experiment output
links to both turn traces. Runtime approval never supplies an independent quality score.
Phoenix also retains its empty, protected `default` system project; it contains no evaluations.

### Reading the trace list

Evaluation spans expose standard Phoenix Input and Output fields. `retail.prompt` shows the
question and the approved Markdown answer, or an explicit failure summary when no answer was
generated. In synthetic evaluation capture, `retail.judge` shows the actual system instruction
and JSON evaluation input as System/User messages, together with the generation configuration
and specialized response schema. Prompt Template contains a readable System/User representation
of the registered template and its `context` variable, holding the sanitized JSON evaluation input.
Output contains the complete visible model response, including
JSON that failed validation. The compact assessment and validation diagnostics remain in metadata;
a provider failure without a response displays an explicit error summary. Raw model source IDs
are preserved in the output; the resolved assessment is saved separately in `judge_calls.json`.
Provider spans show safe request/result summaries and reported token usage. Their metadata
includes the run, scenario, phase, and initial/follow-up label where applicable. Hidden reasoning
and credentials are excluded. Automatic ADK payloads remain hidden. Normal chat tracing remains
metadata-only; visible evaluation content requires the existing synthetic capture mode.

The standard span status describes **execution**: OK means the operation completed; ERROR
means execution or validation failed. A completed judge may still assign a FAIL quality score.
Quality verdicts remain separate experiment/span annotations.

The `parent_id is None` filter shows only root operations. Repeated `retail.prompt` names are
the operation type, while Input identifies the actual question. Remove that filter to inspect
provider/tool spans. It also filters cost statistics: provider costs live on child spans, so a
root-only view can show $0 despite recorded model costs. Phoenix uses its registered model
pricing for those estimates; the application's budget ledger uses configured rates and retains
unknown-usage reservations. Neither is a provider invoice. Costs are never duplicated on roots
to make the filtered total nonzero.

Historical previews can be repaired from hash-verified saved captures. The narrowly scoped
offline maintenance utility is `evaluation/reporting/trace_backfill.py`; Phoenix 22's public
span-ingestion API cannot update existing span IDs. A repair requires a stopped service, a
consistent database backup, a reviewed plan, and unchanged source artifacts. It updates only
display attributes and execution status/error counts, preserving original IDs, parents,
timestamps, events, annotations, experiments, and cost records.

Repairs made before the workspace reset are archived under `.artifacts/phoenix/backfills/`.
New runs record judge messages, template variables, and responses directly.

## Run the 20 conversations

Configure `GEMINI_API_KEY` and Google Cloud application credentials as described in
[Quick Start](../QUICK_START.md), and keep Docker running:

```bash
uv sync --locked --python 3.12 --group evaluation
uv run --locked --group evaluation retail-eval run-conversations \
  --max-cost-usd 10 --deadline-seconds 3600
```

The command performs the complete evaluation:

1. Connect to Phoenix or start its local container.
2. Read authorized raw data independently of the agent's SQL and calculate expected facts with
   Decimal arithmetic and sets. Pin agent and reference queries to the same warehouse timestamp.
3. Update references in the existing 20-row dataset, preserving example IDs and old versions;
   synchronize all four prompts; create an experiment and print its URL before model calls.
4. Execute each initial question and follow-up in isolated conversation/report state.
5. Extract claims with an independent LLM, compare numbers with references in code, assess
   grounding/completeness and tool use, and check persisted report state.
6. Save local artifacts and publish answers and scores after each conversation, then write a summary.

Runtime Golden retrieval is disabled. Expected reference values never reach the analyst.
Completed spans appear during execution; enable trace streaming in Phoenix. Refresh the
experiment view for newly uploaded results. Neither view streams individual tokens.

New runs receive automatic grades rather than PENDING placeholders. Numerical checks, grounding,
and task completion appear separately for each turn, alongside Operations, Trajectory, and
Conversation quality. PASS scores 1; FAIL scores 0; ERROR, UNJUDGEABLE, and NOT_APPLICABLE have
no numeric score. A judge timeout, missing fact, or incomplete run cannot silently pass.
LLM extraction and judgments still need human calibration.

For a targeted retest, keep the questions fixed and select IDs:

```bash
uv run --locked --group evaluation retail-eval run-conversations \
  --only scenario-01,scenario-03 --phase recheck \
  --max-cost-usd 2 --deadline-seconds 600
```

Use `--reference <capture-directory>` to reuse a verified, timestamp-pinned capture within
BigQuery's time-travel window. A different data snapshot creates a new dataset version; compare
agent changes using the same reference capture when possible. Historical unpinned captures are
rejected for new automatic runs. Source changes during execution are rejected.

The advanced `python -m evaluation.runners.manual` entry point is capture-only. It does not run
the independent grader and is not the end-to-end evaluation command.

Each prompt receives a fresh runtime allowance shared by analyst and reviewer. The run also
has a total cost ceiling and deadline covering reference queries, execution, and independent
grading. Limits are caps, not estimates or completion guarantees.
Local artifacts survive interruptions and publication failures; incomplete capture is not
silently published as a complete experiment.

## Saved answers

```text
.artifacts/manual/conversations-<phase>-<timestamp>-<id>/
├── manifest.json                 # Model, source hashes, clock, data source, limits
├── scenarios.json                # Frozen questions and criteria
├── progress.json                 # Execution status, usage, captured-file hashes
├── prompts.json                  # Synchronized prompt version IDs
├── reference/                    # Frozen independent source rows, summary, manifest
├── references.json               # Both-turn reference specifications for all 20 cases
├── cases/scenario-01/turn-1.json    # Initial answer and observed execution
├── cases/scenario-01/turn-2.json    # Follow-up answer and observed execution
├── automatic/scenario-01.json      # Scores, extracted claims, resolved follow-up facts
├── judge_calls.json              # Sanitized judge requests/responses, span IDs, usage, diagnostics
├── summary.json                  # Machine-readable result and exit code
├── summary.md                    # Per-conversation results
└── phoenix-auto.json             # Dataset version, experiment URL, publication state
```

Turn files include `prompt`, `markdown`, evidence, tool observations, candidates, receipts,
usage, and original trace/span IDs. `captured` means collection finished, not that answers passed.
Existing reviews live under `.artifacts/manual/reviews/`.

Exit code 0 means all required work resolved without failures; 1 means resolved quality or
trajectory failures; 2 means unresolved checks, incomplete execution, or publication failure.
Trajectory remains a separate diagnostic and does not redefine answer correctness.

The legacy [manual_history.json](../evaluation/scenarios/manual_history.json) is an archive index.
Its experiments were removed from Phoenix; their frozen local captures keep the original IDs.
Do not republish that manifest into the reset workspace. New evaluations use `run-conversations`.

`run-conversations` collects and attaches references automatically. To attach an already captured
reference bundle without running models:

```bash
uv run --locked --group evaluation retail-eval sync-conversations \
  --reference .artifacts/manual-reference/reference-REPLACE-WITH-CAPTURE-ID
```

The command verifies captured file hashes and recomputes the summary before publication. It
preserves example IDs and old experiments. Original sequential captures remain explicitly
marked as unpinned; attaching one does not certify historical runs against a common data version.

Automatic runs use BigQuery's [historical table reads](https://docs.cloud.google.com/bigquery/docs/access-historical-data)
for products, orders, items, and users at one timestamp. Retained files preserve the reference
evidence after the source's time-travel window expires; new agent executions still need an
available table version. Dataset references are facts and criteria, not a single mandatory prose
answer. Ranking ties are accepted when numerically valid; dependent follow-ups use the products
or categories actually shown initially, not an arbitrary default tie choice.

## Automated tests and controlled evaluations

| Layer | Purpose | Model calls |
|---|---|---|
| `pytest` | SQL scope, tools, budgets, reports, protocol, capture, CLI, and evaluator code | Scripted only |
| `retail-eval validate` | Schemas, fixtures, reference facts, and judge controls | None |
| `retail-eval run` | Agent execution and independent grading on controlled fixtures | Agent and judges |
| `retail-eval calibrate` | Judge behavior on valid/flawed answer pairs | Judge only |

```bash
uv run --locked --group evaluation pytest
uv run --locked --group evaluation retail-eval validate
uv run --locked --group evaluation ruff check .
uv run --locked --group evaluation ruff format --check .
uv run --locked --group evaluation pyright
```

Offline tests block external sockets and credential discovery. CI runs these checks with
coverage. Tests marked `live` or `phoenix` are excluded by default. The Phoenix SDK pytest
plugin is disabled so tests cannot automatically create `tests/integration/...` datasets.

| Collection | Purpose | Analyst access |
|---|---|---|
| [knowledge/golden/](../knowledge/golden/README.md) | Optional analytical examples | Eligible examples when enabled |
| [evaluation/scenarios/](../evaluation/scenarios/README.md) | 20 authored conversations and behavioral criteria | Questions only; criteria remain hidden |
| [evaluation/datasets/golden/](../evaluation/datasets/README.md) | 43 controlled cases across nine fixtures | User steps and scoped tools; references remain hidden |

Controlled cases include 36 development and seven regression cases. Forty judge controls form
20 valid/flawed pairs: 24 development examples and 16 validation examples. References are
code-verified; human review, judge calibration, and a sealed holdout remain pending.

Use a **separate disposable Phoenix on port 6007** for fixture runs and collector tests; see
[service setup](../infra/phoenix/README.md#disposable-test-instance). Fixture publication rejects
port 6006 to protect the main workspace:

```bash
uv run --locked --group evaluation retail-eval run \
  --suite smoke --repetitions 1 --phoenix-url http://127.0.0.1:6007 \
  --max-cost-usd 5 --deadline-seconds 900 --allow-unreviewed
```

This workflow uses local synthetic databases, needs no BigQuery credentials, and automatically
grades answers, drafts, operations, and trajectory. `--allow-unreviewed` acknowledges unreviewed
references; it does not disable review. Use `cases --suite smoke` to inspect inputs,
`--suite pilot` for all 43 cases, comma-separated case IDs for a subset, and `--repetitions 3`
for repeated independent trials. Failed trials are retained.

Artifacts live under `.artifacts/evaluation/run-.../`: frozen cases/fixtures, `trials/*.json`
with `turns[].markdown`, and versioned `grades/grade-.../` summaries and judge calls.
The run budget/deadline includes execution and grading. Exit codes are 0 for resolved checks
without failures, 1 for resolved failures, and 2 for incomplete/unresolved work. These are
diagnostic results, not release gates.

```bash
EVAL_RUN=.artifacts/evaluation/run-REPLACE-WITH-PRINTED-ID
uv run --locked --group evaluation retail-eval grade --run "$EVAL_RUN" \
  --max-cost-usd 3 --deadline-seconds 900
uv run --locked --group evaluation retail-eval publish --run "$EVAL_RUN" \
  --grade "$EVAL_RUN/grades/grade-REPLACE-WITH-PRINTED-ID" \
  --phoenix-url http://127.0.0.1:6007
uv run --locked --group evaluation retail-eval calibrate \
  --split validation --max-cost-usd 3 --deadline-seconds 900
```

Regrading never reruns the analyst. `grade --phoenix` also requires the separate endpoint.
`grade --code-only` leaves semantic requirements unresolved. `compare --baseline <grade-dir>
--candidate <grade-dir>` requires compatible references, grader versions, and repetition
coverage. Synthetic control agreement is not human calibration.

## How correctness, hallucinations, and traces are checked

The runtime reviewer requests revisions before publication. Independent evaluation examines
saved execution afterward, including defects that reviewer approved.

Both the controlled fixture runner and new authored-conversation runner use these checks.
Historical assistant reviews remain a separate record.

| Check | Automatic evaluation |
|---|---|
| Numerical correctness | Judge extracts entity/metric/period-bound facts; code compares independent references |
| Grounding | Judge labels claims against evidence available at that point |
| Completeness | Required facts, criteria, permitted outcomes, and both conversation turns |
| Operations | Exact ownership, saved content, state, and applicable receipts |
| Trajectory | Separate judge checks tools, arguments, evidence use, recovery, and repeated actions |

The automated judge receives observations and fact definitions, but not expected numerical
values or reference answers. Code validates evidence IDs and excerpts before comparing extracted
facts. Correctness and grounding are separate: a correct number may still lack observed support.

Different product rankings alone do not establish that higher prices caused the difference.
An unsupported explanation can fail grounding even when both tables are correct. Automated
claim labels are `SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, `NOT_FACTUAL`, and `UNJUDGEABLE`.
Missing evidence or assessment remains unresolved.

Trace tests verify recording, attribution, ordering, token accounting, follow-up context, and
redaction. Protocol tests check recovery, revisions, invented evidence references, and publication
of the exact reviewed candidate. They use scripted models:

```bash
uv run --locked --group evaluation pytest \
  tests/integration/test_observability.py tests/integration/test_agent_protocol.py \
  tests/evaluation/test_grading.py tests/evaluation/test_visibility_metrics.py
```

Traces record observable execution, not private reasoning. The automated trajectory judge uses
local captured events and permits multiple valid tool paths. Its diagnostic scores do not alter
task success. Earlier evidence supports a follow-up only if still available or retrieved again.
The fixture pipeline does not automatically grade arbitrary historical Phoenix traces.

Passing tests cannot establish the absence of hallucinations. Inspect coverage, unresolved
checks, false acceptances, and source drift alongside pass rates. Both historical assistant
reviews and automated judges still require independent human validation.

## Prompt versions in Phoenix

Git remains authoritative. The four definitions are `retail-analyst`, `retail-reviewer`,
`retail-answer-judge`, and `retail-trajectory-judge`. They include instructions, model, generation
settings, and base output schemas. The reviewer includes its mandatory analytical-review skill.

```bash
uv run --locked --group evaluation retail-eval sync-prompts
```

This populates [Prompts](http://127.0.0.1:6006/prompts) without inference and starts Phoenix if
needed. Automatic conversation runs synchronize all four prompts; fixture runs do the same
in their separate instance. Unchanged definitions reuse versions; changed ones get
`code-<sha256>` tags. The `repository` tag identifies the last synchronized definition.

Provider/judge spans and artifacts record prompt hashes and synchronized IDs. Inputs, evidence,
and secrets never become templates. UI edits do not change application behavior: adopt changes
in Git, test, then synchronize. Optional analyst skills remain separate tool-loaded resources.

Playground needs its own provider configuration; synchronization does not copy credentials.
Supply appropriate JSON as `context`. Playground analyst calls cannot execute our ADK tools;
judge calls omit the application's additional attribution checks. The full agent suite runs
through our CLI, not the Phoenix GUI.

See [architecture](architecture.md), [service setup](../infra/phoenix/README.md), the
[authored evaluation validation](plans/AUTHORED_EVALUATION_VALIDATION.md), and the
[fixture implementation report](plans/EVALUATION_IMPLEMENTATION_RESULTS.md) for evidence and limits.
