# Retail Analysis Assistant

A Python CLI for retail analysis with a single Google ADK/Gemini agent loop. The model selects tools, writes scoped SQL, interprets results and generates Markdown, including tables when appropriate. A tool-free evaluator reviews each candidate; revision feedback returns to the same analyst conversation.

```bash
uv sync --locked --python 3.12
uv run --locked retail-agent chat --user alice --golden-bootstrap
```

Configure your Gemini key and Google Cloud application credentials first; see [Quick Start](QUICK_START.md). `--golden-bootstrap` enables the repository's 11 synthetic reference methods. Current answers require fresh evidence. Without this flag, only eligible approved examples from the configured corpus are available.

For real Gemini calls against a frozen synthetic dataset, without BigQuery credentials:

```bash
uv run --locked retail-agent chat --user alice --backend fixture --golden-bootstrap
```

The application provides schema discovery, a Golden example catalog, warehouse queries, local result analysis, prior-answer access and private report management. The analyst selects examples from eligible summaries. Application services enforce permissions, privacy, budgets and deletion confirmation. Answers contain the model's reviewed Markdown; `/details` displays supporting SQL and evidence.

Runtime analytical skills are enabled by default. The analyst reads relevant methods on demand, and every evaluator call receives the review rubric. Model-facing functions live in `src/retail_agent/tools/`, their database/storage implementations in `services/`, and skill Markdown in `skills/library/`. See [how skills and Golden examples work](docs/architecture.md#knowledge-and-evaluation-assets) and [skill authoring](src/retail_agent/skills/README.md).

- [Architecture](docs/architecture.md): the agent loop, tools, data access and implementation limits.
- [Evaluation design](docs/plans/EVALUATION_REBUILD_PLAN.md): independent references, grading contracts, and remaining validation work.
- [Implementation results](docs/plans/EVALUATION_IMPLEMENTATION_RESULTS.md): verified checks, live trials, grader repairs and limitations.
- [Golden examples](knowledge/golden/README.md): provenance, offline validation and publication rules.

```bash
uv run --locked --group evaluation pytest
uv run --locked python scripts/validate_golden_bootstrap.py
uv run --locked ruff check .
uv run --locked --group evaluation pyright
```

Saving requires an explicit request. Deletion requires an exact preview and confirmation in the same interactive chat. Report libraries are owner-private, including against CEO access. Existing user data is preserved; explicit legacy import copies owned reports without modifying the source.

The local CLI uses simulated identities, in-memory conversation context and SQLite report storage. Nontechnical persona administration, inferred preference learning, production authentication and deployment infrastructure remain design-only. Evaluator approval does not guarantee correctness.

## Independent evaluation

`knowledge/golden/` contains optional runtime examples. `evaluation/datasets/golden/` contains
independent evaluation tasks and references; the analyst receives only the user steps and
its authorized environment. The pilot has 43 synthetic cases across nine fixtures, with
independent Decimal/set calculations and 40 paired judge controls. References are code-verified;
human review and judge calibration are still pending. There is no sealed holdout yet.

Install the evaluation dependencies and start local Phoenix:

```bash
uv sync --locked --group evaluation
uv run --locked --group evaluation retail-eval validate
docker compose -f infra/phoenix/compose.yaml up -d
uv run --locked --group evaluation retail-eval sync --suite pilot
```

Open [Phoenix](http://127.0.0.1:6006). It stores traces, datasets, experiments and scores locally.
Agent and judge inference still uses Gemini. The pinned server and privacy controls are
explained in [the Phoenix setup](infra/phoenix/README.md).

A bounded live experiment with three repetitions per case:

```bash
uv run --locked --group evaluation retail-eval run \
  --suite totals-q1,unsupported-cause --repetitions 3 \
  --max-cost-usd 3 --deadline-seconds 900 --allow-unreviewed --phoenix
```

Each repetition gets an isolated report store and frozen clock. Follow-ups retain conversation
context, while each prompt receives a fresh runtime budget. The experiment also has a total
cost ceiling and deadline. Missing usage retains its reservation; remaining trials are marked
`NOT_EXECUTED` when a limit prevents execution. No failed trial is automatically rerun.

Use the run directory printed by that command:

```bash
EVAL_RUN=.artifacts/evaluation/run-REPLACE-WITH-PRINTED-ID
uv run --locked --group evaluation retail-eval grade --run "$EVAL_RUN" \
  --max-cost-usd 3 --deadline-seconds 900 --phoenix
```

Grading creates a new `grades/grade-.../` directory with `summary.md`, `summary.json`, individual
findings and judge usage. It never reruns the agent. The default also grades first drafts and
revisions against the evidence available at that moment. `--code-only` skips LLM judgment and
marks unassessed semantic requirements as unresolved, rather than passing them.

| Check | Method |
|---|---|
| Numerical correctness | Extract entity/metric/period-bound facts; compare with independent Decimal references |
| Grounding | Judge atomic claims against observed evidence; separate unsupported, contradicted and unjudgeable claims |
| Task completion | Check every published turn, permitted outcome and frozen acceptance criteria |
| Report operations | Verify exact saved content, ownership, confirmation receipts and final state |
| Reliability | Preserve all repetitions, failures, incomplete groups, latency and accounted cost |

Other commands:

```bash
uv run --locked --group evaluation retail-eval cases --suite smoke
uv run --locked --group evaluation retail-eval calibrate --split validation \
  --max-cost-usd 3 --deadline-seconds 900
uv run --locked --group evaluation retail-eval publish --run "$EVAL_RUN"
uv run --locked --group evaluation retail-eval compare \
  --baseline /path/to/baseline/grades/grade-ID \
  --candidate /path/to/candidate/grades/grade-ID
```

Comparisons require matching references, grader versions and repetition coverage. Synthetic
control agreement is diagnostic; it does not establish human-calibrated accuracy or a release
gate. Phoenix publication failures preserve local artifacts and can be retried with `publish`.
Normal chat tracing is opt-in with `--phoenix` and captures metadata only.

The CLI workflow expects a source checkout: runtime knowledge assets, Git metadata and `uv.lock`
are resolved from the repository. The wheel includes evaluation cases/fixtures and supports
reference validation, but it is not a standalone distribution of the complete application.

To check the local collector with scripted models and no paid inference:

```bash
uv run --locked --group evaluation pytest tests/integration/test_phoenix_service.py -m phoenix
```
