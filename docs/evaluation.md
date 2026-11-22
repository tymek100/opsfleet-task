# Testing and evaluation

This guide describes the implemented testing and evaluation workflow for Retail Insight Agent.
Run commands from the repository root. All test conversations use English.

## What each layer checks

| Layer | Purpose | Real model calls? | How to run |
|---|---|---|---|
| Automated tests | Verify SQL scope, tools, budgets, report operations, agent protocol, CLI behavior, and the evaluation code itself | No; model responses are scripted | `pytest` |
| Dataset validation | Check case schemas, fixture integrity, reference facts, and judge controls | No | `retail-eval validate` |
| Agent evaluation | Execute the real agent and independently assess answers, actions, and trajectory | Yes | `retail-eval run` |
| Judge calibration controls | Check whether the offline judge distinguishes valid answers from deliberately flawed answers | Yes, judge only | `retail-eval calibrate` |

The **runtime reviewer** is part of the application: it reviews a candidate answer and can ask
the analyst to revise it before publication. The **offline evaluator** assesses saved executions
afterward. Runtime approval does not count as an independent evaluation pass.

The offline judge uses a separate prompt and model call. By default it uses the configured
`GEMINI_MODEL`, which can also be the analyst's model; `run --judge-model` or
`grade --judge-model` overrides it.
Separate evaluation does not imply a different model family or provider.

## Setup and offline checks

Use a source checkout with `uv` and Python 3.12:

```bash
uv sync --locked --python 3.12 --group evaluation
uv run --locked --group evaluation pytest
uv run --locked --group evaluation retail-eval validate
```

These checks require no Gemini or BigQuery credentials. Installing dependencies may require
network access; the tests themselves block external network sockets by default.

Tests live in `tests/cli/`, `tests/contracts/`, `tests/integration/`, and `tests/evaluation/`.
Integration tests exercise real local components with scripted models and synthetic data.
The default pytest selection excludes tests marked `live` or `phoenix`.

The remaining CI checks are:

```bash
uv run --locked --group evaluation ruff check .
uv run --locked --group evaluation ruff format --check .
uv run --locked --group evaluation pyright
```

[GitHub CI](../.github/workflows/ci.yml) runs these checks, pytest with coverage, and dataset
validation. It does not run paid agent evaluations. To validate the separate runtime Golden
Knowledge examples, use `uv run --locked python scripts/validate_golden_bootstrap.py`.

## Run an evaluation end to end

Set `GEMINI_API_KEY` in your environment or the repository's `.env` file; see
[`.env.example`](../.env.example). Have Docker with Compose available and the Docker daemon running.
The analyst and independent judges call Gemini; analytical queries use synthetic local database
fixtures, so BigQuery credentials are unnecessary.

One command runs the smoke suite and evaluates its results:

```bash
uv run --locked --group evaluation retail-eval run \
  --suite smoke --repetitions 1 \
  --max-cost-usd 5 --deadline-seconds 900 --allow-unreviewed
```

The smoke suite has four cases, including a conversation with three questions.
`--allow-unreviewed` acknowledges that the synthetic references still await human review;
it does not disable the application's runtime reviewer. Inspect the selected cases with
`uv run --locked --group evaluation retail-eval cases --suite smoke`.

The command performs the complete workflow:

1. Validates the selected references.
2. Connects to local Phoenix or starts the pinned Compose service if it is unavailable.
3. Freezes the cases and fixtures in a new run directory, creates the experiment, and prints its
   URL and a trace-view URL before the first model call.
4. Runs each case in an isolated conversation and report store with an authorized identity and
   fixed reporting clock. Follow-ups retain that case's conversation context.
5. Captures and publishes each completed trial, then independently grades its answers, drafts,
   report operations, and trajectory and publishes those scores.
6. Prints the final summary and local artifact paths.

There is no separate `sync`, `grade`, or `publish` step for this normal workflow. The agent
receives user questions and access to authorized tools and data. It never receives expected
answers, reference values, or grading criteria. For example, Alice's queries are scoped to
Calvin Klein even when the fixture also contains another brand.

Open the printed URLs while the command runs. Enable trace streaming in Phoenix to see completed
spans appear automatically after ingestion. Trial outputs and scores are uploaded incrementally,
but refresh the experiment view to display them: pinned Phoenix 22.0.1 does not automatically
refresh externally published experiment results. Neither view streams individual answer tokens.

The command saves `.artifacts/evaluation/run-<timestamp>-<id>/` and a nested
`grades/grade-<timestamp>-<id>/summary.md`. Open `summary.md` for the overall result and the
individual grading JSON files for detailed findings. A startup failure aborts before model
spending. Later publication failures preserve local artifacts for recovery.

The exit code describes this diagnostic experiment:

| Code | Meaning |
|---|---|
| `0` | Task and trajectory checks resolved without failures; requested draft grading and publication completed |
| `1` | A resolved task or trajectory check failed |
| `2` | Setup, execution, grading, or publication is incomplete or unresolved |

Incomplete results take precedence over observed failures, including when a failed task also
has unresolved required checks. A diagnostic trajectory failure can return `1` even when all
task outcomes pass; it does not change `task_success`. These codes do not establish production
release readiness.

Drafts and revisions are graded by default to expose mistakes the runtime reviewer accepted
or corrected. Missing or unresolved requested draft judgments return `2`; a resolved draft
failure is diagnostic and does not itself fail the published answer. Add `--no-candidates`
to skip those extra answer judgments; the final answers and trajectory are still assessed.
Keep this setting consistent when comparing runs.

## Where the data and answers live

### Authored conversations against the configured warehouse

The separate [20-conversation set](../evaluation/scenarios/README.md) exercises the real agent
with 20 initial questions and 20 fixed follow-ups against the configured BigQuery source.
It complements the controlled fixture suite. These are authored scenarios on public TheLook
sample data, not captured production conversations or a representative traffic sample.

```bash
uv run --locked --group evaluation python -m evaluation.runners.manual \
  --backend bigquery --phoenix --phase baseline \
  --max-cost-usd 6 --deadline-seconds 3600
```

This requires the application's Gemini and BigQuery credentials. The optional `--phoenix`
flag publishes traces and prints the project link. Each case gets an isolated report store;
follow-ups retain its conversation. Runtime Golden retrieval is disabled in this set.
The runner captures answers, actual observations, drafts, reviews and report state under
`.artifacts/manual/manual-<phase>-<timestamp>-<id>/cases/manual-XX/`, including `transcript.md`
and `turn-1.json` / `turn-2.json`. It freezes questions and runtime sources and rejects source
changes during a run. `captured` means collection completed, not that answers passed review.

Review each answer against its observed evidence and an independent reference capture:

```bash
uv run --locked --group evaluation python -m evaluation.manual_reference \
  --output-root .artifacts/manual-reference
```

The reference utility reads scoped source rows independently of the agent's generated SQL and
calculates metrics using Decimal arithmetic and sets. It does not supply answers to the agent.
Live warehouse reads are not a transactional snapshot; compare capture hashes for source drift.
Preserve baseline outputs, keep questions unchanged, and use `--phase recheck` after a correction.
Supply the same `--clock-utc` when comparing time-relative questions.

This capture workflow does not automatically assign independent quality scores. The
[conversation review report](plans/manual-conversation-review.md) records assistant review of
every answer, numerical verification, observed failures and recheck results. Assistant review
is not human approval or a sealed holdout.

### Controlled evaluation datasets

There are two distinct collections called "golden":

| Location | Contents | Available to the analyst? |
|---|---|---|
| [`knowledge/golden/`](../knowledge/golden/README.md) | Optional reusable analytical examples and methods | Yes, when enabled and eligible |
| [`evaluation/datasets/golden/`](../evaluation/datasets/README.md) | Evaluation questions, reference facts, acceptance criteria, and reference answers | Only the user steps; references remain outside the agent context |
| [`evaluation/fixtures/`](../evaluation/fixtures/README.md) | Synthetic raw records and corresponding SQL databases | Through scoped data tools |
| `evaluation/datasets/judge_calibration/` | Valid and deliberately flawed answers for checking the judge | No |

Each evaluation case controls whether runtime Golden examples are enabled. `run` does not
accept the interactive CLI's `--golden-bootstrap` flag.

The current pilot contains **43 synthetic cases**: 36 development cases and seven regression
cases, across nine fixtures. Expected numerical facts are calculated independently from raw
records using Decimal arithmetic and sets in [`evaluation/oracles/retail.py`](../evaluation/oracles/retail.py).
They are not generated from the agent's SQL or answers.

Each run preserves its own inputs and outputs:

```text
.artifacts/evaluation/run-<timestamp>-<id>/
├── manifest.json               # Configuration, versions, hashes, usage, execution status
├── cases/                      # Frozen questions, criteria, and reference facts
├── fixtures/                   # Frozen raw JSON and SQL data
├── trials/
│   └── totals-q1-r1.json       # One case/repetition, including all conversation turns
├── phoenix.json                # Experiment/trace links and incremental publication status
└── grades/
    └── grade-<timestamp>-<id>/
        ├── manifest.json       # Grader configuration and version hashes
        ├── trials/             # Per-trial scores and findings
        ├── judge_calls.json    # Judge calls and usage, when a judge is used
        ├── summary.json        # Structured metrics
        └── summary.md          # Readable summary
```

In a trial JSON file, **`turns[].prompt` contains the question and `turns[].markdown` contains
the published answer**. Follow-ups are additional turns in that file. Draft answers are stored
separately in `turns[].candidates`; ordered execution observations are in `turns[].timeline`.
A failed or incomplete turn may have no published answer.

Grading verifies hashes before using saved cases, fixtures, and trials. Editing the canonical
dataset affects future runs; it does not alter an existing run's references. Regrading creates
a new grade directory. These local artifacts are Git-ignored. Use `run --artifact-root` to
choose a different output directory.

## What grading measures

| Check | Current method |
|---|---|
| Numerical correctness and completeness | The judge extracts facts bound to entities, metrics, periods, and units; Python compares them with independent reference values and tolerances |
| Grounding | The judge classifies factual claims as supported, unsupported, contradicted, or unjudgeable against evidence available at that point |
| Evidence references | Validate referenced evidence IDs and exact source excerpts; invented references are rejected |
| Task completion | Check requested facts, semantic criteria, permitted outcomes, and applicable conversation steps |
| Tool and report behavior | Check scope-sensitive evidence and exact report state, ownership, saved content, and operation receipts |
| Trajectory quality | Judge tool selection, argument use, evidence use, recovery, and progress against recorded steps; diagnostic scores do not change task success |
| Reliability and efficiency | Report success, unresolved coverage, repeated-run reliability, elapsed time, and accounted cost |

The judge sees the actual answer, observed evidence, fact definitions, and semantic criteria.
Expected numerical values and the reference answer are withheld from its input; Python performs
the comparison after extraction. The reference answer remains available for human inspection.

Read statuses and coverage together:

| Status | Meaning |
|---|---|
| `PASS` | Required applicable checks passed |
| `FAIL` | A required check found a defect |
| `ERROR` | Execution, capture, or grading failed |
| `UNJUDGEABLE` | The available evaluation cannot establish a result |
| `NOT_APPLICABLE` | A conditional step or check legitimately does not apply |
| `NOT_EXECUTED` | A planned trial or step did not run; recorded in execution artifacts |

The summary reports success over planned trials, resolved and unresolved counts, numerical
accuracy and grading coverage, factual claim precision, affected-answer rates, repetition coverage,
and separate trajectory results and coverage. `unresolved_required_checks` includes unresolved
checks within failed tasks; `candidate_grading` reports requested draft-grading coverage.
Inspect these counts before interpreting any percentage. These diagnostic results are not a
validated production release gate.

## Testing traces and tool behavior

A trace records observable execution: model calls, tool interactions, review, and completion.
It is not a record of the model's private reasoning. We test both the recording mechanism and
selected behaviors visible in the execution.

**Trace capture tests** verify:

- Separate prompt traces and a shared conversation identifier for follow-ups.
- Correct analyst/reviewer attribution, call ordering, and token accounting without duplication.
- Accurate snapshots of tool responses, candidate answers, and review decisions.
- Redaction of credentials, hidden thoughts, and deletion confirmation tokens. Normal chat traces
  contain metadata; evaluation capture can include synthetic prompts, evidence, and answers.
- Export failures and bounded shutdown do not prevent an otherwise available answer.

Run these offline tests with scripted models:

```bash
uv run --locked --group evaluation pytest tests/integration/test_observability.py
```

The [Phoenix section](#phoenix-inspect-and-compare-results) also provides an integration test
that verifies actual local ingestion and retrieval of traces, experiments, and annotations.

**Agent protocol tests** exercise behaviors such as recovering from query errors, revising after
review feedback, rejecting unknown evidence references, and publishing the exact reviewed answer:

```bash
uv run --locked --group evaluation pytest tests/integration/test_agent_protocol.py
```

During live evaluation, grading reads captured context and tool observations from local trial
files; it does not need to retrieve traces from Phoenix. Each draft is assessed using evidence
visible when it was submitted. A row observed in an earlier turn cannot support a follow-up if
it is no longer in the current context and the agent has not retrieved it again. Capture errors
are recorded as evaluation errors rather than treated as complete evidence.

**Trajectory evaluation** adds a separate LLM assessment of the complete captured conversation.
It considers available tools, requests, tool arguments and results, review feedback, and subsequent
actions. Findings refer to recorded steps and events so they can be inspected alongside the trace.
It assesses tool selection, argument appropriateness, use of observed evidence, recovery after
errors, and progress without unjustified repeated actions.

The rubric permits multiple valid tool paths. Clarification, refusal, and reuse of an already
available answer do not require an arbitrary extra query. A correct final answer can coexist
with a poor trajectory, such as repeated identical queries after a permanent schema error.

Trajectory judgments are diagnostic while human calibration is pending: they are reported
separately and do not change `task_success`. Missing capture or insufficient evidence remains
unresolved. Neither an LLM trajectory score nor passing protocol tests establish that every
choice was optimal. Evaluation uses the captured local execution, not arbitrary historical
Phoenix traces whose required context may be missing.

## Testing hallucinations

We check **correctness against independent facts** and **support in observed evidence** separately.
A correct number can still be unsupported if the agent never obtained evidence for it.

| Failure | How it is assessed |
|---|---|
| Wrong value, entity, period, or missing required metric | LLM extraction binds each fact to its meaning; code compares it with independent references |
| Plausible but unsupported explanation | The judge checks factual claims against the evidence actually available to the agent |
| Claim contradicting a query result | The judge labels it `CONTRADICTED` |
| Fabricated evidence IDs or answer excerpts in the judge's output | Code rejects the attribution and records a grading error |
| Incomplete claim assessment or insufficient evidence to judge | Results remain unresolved rather than receiving a clean pass |

For example, different revenue and customer rankings do not alone establish that higher prices
caused the difference. A statement asserting that cause is unsupported unless additional evidence
establishes it. Correct ranking tables do not make the explanation valid.

The judge labels extracted claims `SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, `NOT_FACTUAL`, or
`UNJUDGEABLE`. Material unsupported or contradicted claims fail the grounding check. Draft grading
also records disagreements with the runtime reviewer, including flawed candidates it approved.
A later correction does not erase an earlier incorrect published answer from the evaluation.

Run the grading and evidence-visibility regression tests without model calls:

```bash
uv run --locked --group evaluation pytest \
  tests/evaluation/test_grading.py tests/evaluation/test_visibility_metrics.py
```

To test actual model behavior, run cases such as `unsupported-cause`, `ranking-overlap`,
`false-churn-spike`, and `tool-value-injection` using the live commands above. To test the judge
itself against known valid/flawed answers, use `calibrate` below.

These mechanisms cannot prove that an answer contains no hallucinations. The judge may miss or
misclassify claims, and human validation of claim-extraction coverage is still pending.
`--code-only` does not perform these semantic checks. Review grounding scores together with
coverage, numerical checks, and the recorded evidence.

## Suites, repetitions, and budgets

| `--suite` | Selection |
|---|---|
| `smoke` | Four cases for a quick check; the default suite |
| `pilot` or `all` | All 43 current cases |
| `dev` | 36 development cases |
| `regression` | Seven cases covering previously observed failure patterns |
| `challenge` | Three cases covering missing values, offsetting changes, and paginated results |
| `totals-q1,unsupported-cause` | Explicit comma-separated case IDs |

List any selection with `retail-eval cases --suite <selection>`. There is no sealed holdout yet.

To run the entire pilot once:

```bash
uv run --locked --group evaluation retail-eval run \
  --suite pilot --repetitions 1 \
  --max-cost-usd 20 --deadline-seconds 7200 --allow-unreviewed
```

This includes answer and trajectory grading and Phoenix publication. The example amount is
a cap for the entire run, not an estimated price or a guarantee that every case will finish.

`--repetitions 3` executes each case three times with fresh isolated state, which helps reveal
inconsistent behavior. One repetition is the default.
Failed trials are retained, not automatically rerun until they pass.

There are two execution limits:

- **Per prompt:** a fresh application allowance shared by the analyst, runtime reviewer, and
  their retries. Defaults include $1 and 120 seconds, configured through `QUESTION_BUDGET_USD`
  and `TURN_TIMEOUT_SECONDS`.
- **Per run:** `--max-cost-usd` and `--deadline-seconds` cover the entire workflow, including
  agent execution, runtime review, independent answer/draft grading, and trajectory grading.
  A prompt is also limited by what remains in that run. Unstarted work is recorded as
  `NOT_EXECUTED`; evaluations that cannot finish remain unresolved.

No second judge budget is added automatically. Running the optional `grade` or `calibrate`
commands later starts a separate bounded operation with its own cost and time allowance.
Costs use configured token rates, and unknown usage retains conservative reservations;
accounted cost is not an exact provider invoice.

## Phoenix: inspect and compare results

`run` uses Phoenix by default and automatically starts the local service when needed. Open the
experiment and trace URLs printed at startup, or [http://127.0.0.1:6006](http://127.0.0.1:6006).
The experiment contains individual answers, numerical/grounding scores, and diagnostic trajectory
scores. Traces show the execution that produced those answers. Local artifacts are saved as well.

Initial service readiness and experiment creation must succeed before model calls begin.
Automatic startup uses the pinned configuration at `infra/phoenix/compose.yaml` for the default
local endpoint. A custom `--phoenix-url` must already be running. The CLI does not install or
start the Docker daemon.

**The full ADK suite is launched from the CLI, not the Phoenix GUI.** Phoenix stores and presents
the experiment; Python runs our isolated agent and custom evaluators. Gemini inference uses the
provider API even though Phoenix stores data locally.

To retry publication after an outage, use the paths printed by the run:

```bash
EVAL_RUN=".artifacts/evaluation/run-REPLACE-WITH-PRINTED-ID"
EVAL_GRADE="$EVAL_RUN/grades/grade-REPLACE-WITH-PRINTED-ID"
uv run --locked --group evaluation retail-eval publish \
  --run "$EVAL_RUN" --grade "$EVAL_GRADE"
```

This publishes saved data without rerunning the agent or judges. Without `--grade`, it uploads
executions without grade scores. The advanced `retail-eval sync --suite pilot` command only
uploads the dataset. Consult `phoenix.json` for publication status and links.

For manual service management or the optional collector test:

```bash
docker compose -f infra/phoenix/compose.yaml up -d
uv run --locked --group evaluation pytest tests/integration/test_phoenix_service.py -m phoenix
docker compose -f infra/phoenix/compose.yaml down
```

The test uses scripted models and the running local collector, with no paid inference. `down`
retains the named data volume. See [Phoenix setup](../infra/phoenix/README.md) for capture modes
and persistence.

## Regrading, judge controls, and comparisons

Normal runs already include independent grading. To assess saved executions with a changed
judge configuration, or finish grading after an exhausted budget, create a new grade version:

```bash
EVAL_RUN=".artifacts/evaluation/run-REPLACE-WITH-PRINTED-ID"
uv run --locked --group evaluation retail-eval grade \
  --run "$EVAL_RUN" --max-cost-usd 3 --deadline-seconds 900 --phoenix
```

`grade` verifies frozen inputs and outputs and never reruns the analyst. It prints the new
`summary.md` path. `--phoenix` publishes the new scores; without it, regrading remains local.
Previously saved grade versions remain available. Trajectory evaluation is enabled by default;
use `--no-trajectory` only when intentionally producing answer-only grades, and compare grades
with matching settings.

For checks that require no LLM judge:

```bash
uv run --locked --group evaluation retail-eval grade \
  --run "$EVAL_RUN" --code-only --max-cost-usd 1 --deadline-seconds 60
```

The CLI still requires both limit arguments, but this mode makes no judge calls. It checks
available structural and operation contracts. It does not perform LLM fact extraction or
semantic assessment; unanswered grading requirements and trajectory assessment remain
`UNJUDGEABLE`.

To check the judge against the validation controls:

```bash
uv run --locked --group evaluation retail-eval calibrate \
  --split validation --max-cost-usd 3 --deadline-seconds 900
```

There are 40 controls in total: 20 valid/flawed pairs, split into 24 development and 16 validation
examples. This command evaluates the 16 validation examples without running the analyst. Results
are saved under `.artifacts/evaluation/calibration-<timestamp>-<id>/`, including `summary.json`,
individual control outcomes, and judge calls. Inspect false acceptances, false rejections, errors,
and claim coverage. Agreement with these synthetic labels is not human calibration.

To compare two independently generated and graded agent runs:

```bash
uv run --locked --group evaluation retail-eval compare \
  --baseline .artifacts/evaluation/run-BASELINE/grades/grade-ID \
  --candidate .artifacts/evaluation/run-CANDIDATE/grades/grade-ID
```

Use the same frozen dataset, repetitions, and grading configuration. The comparator checks
compatibility and withholds paired comparison when outcomes remain unresolved. To compare an
agent change, execute a new run; regrading the same answers only measures a grading change.

## Current limits

The pilot's references are independently checked in code, but human reference review, human
judge calibration, and a sealed holdout remain pending. Synthetic fixtures test selected failure
patterns; they do not represent production traffic or establish live BigQuery correctness.

Use these results to identify regressions and inspect failures, alongside human review.
Implementation evidence and remaining work are recorded in the
[implementation report](plans/EVALUATION_IMPLEMENTATION_RESULTS.md) and
[evaluation design](plans/EVALUATION_REBUILD_PLAN.md).
