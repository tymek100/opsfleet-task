# Real-model smoke observations

The opt-in [runner](../../../scripts/evaluate_rewrite.py) executes English prompts against the replacement analyst, captures complete `TurnResult` records and writes `observations.md`. It uses a temporary, isolated report library. It never imports or modifies user reports.

The runner is ready; this README alone does **not** claim that any live prompt has passed. Completed run directories contain the actual evidence and manually reviewed observations.

## Run after installing the replacement environment

Inspect prompts offline:

```bash
uv run --locked python scripts/evaluate_rewrite.py --list-cases
```

Run a real Gemini model against the frozen synthetic warehouse fixture, explicitly enabling synthetic Golden retrieval:

```bash
uv run --locked python scripts/evaluate_rewrite.py \
  --live --backend fixture --golden-bootstrap \
  --output evals/rewrite/runs/fixture-smoke-01
```

Run selected cases against real BigQuery data with your configured credentials:

```bash
uv run --locked python scripts/evaluate_rewrite.py \
  --live --backend bigquery \
  --case rankings --case prose_aov --case monthly_table \
  --output evals/rewrite/runs/bigquery-smoke-01
```

Before the replacement is installed at the canonical package location, run the same script with `PYTHONPATH=rewrite/src .venv/bin/python` in place of `uv run --locked python`. That explicitly imports the fresh runtime. Do not run it against the legacy package.

`--case` may be repeated. Other options include `--user alice`, `--model MODEL`, `--timeout SECONDS` and `--max-model-calls COUNT`. Running all eight cases produces nine turns because report generation is followed by an explicit save. The `golden_method` case requires `--golden-bootstrap`; unrelated cases do not require retrieval. Output directories must be new or empty, preserving earlier captures.

The script loads the normal external `.env` configuration but records only a safe settings allowlist. Model and warehouse calls share the configured per-turn allowance; running multiple turns can consume several per-turn allowances. Reserved USD in results is conservative admission accounting, not actual billing.

## What to inspect

Each run writes:

- `run.json`: configuration/version/digest metadata and all completed observations.
- One JSON record per turn: exact prompt, complete result/evidence, traces, receipts and isolated report-store snapshots.
- `observations.md`: full published answers, timings, tool sequences, review outcomes, narrow smoke checks and a manual assessment section for each case.

For the unchanged synthetic fixture and `alice`, independently enumerated expected facts include Q1 revenue **375**, **6 orders**, **7 items**, **5 customers**, average order value **62.50**, and monthly revenue **125 / 100 / 150**. The expected-fact checks are disabled for other scopes, changed fixture hashes and BigQuery data. SQL evidence and the answer must be reviewed together; numeric-token presence alone cannot prove the right calculation or interpretation.

A runtime `approved` status is not automatically a successful analytical answer. Review completeness, numerical meaning, source scope, format suitability, unsupported explanations, evaluator corrections and actual stored report content. The runner leaves manual assessments pending so observed defects cannot be hidden behind approval counts.

These are development smoke/regression prompts, including prompts related to Golden examples. They do not measure held-out generalization, production reliability or latency percentiles. The separate [rewrite specifications](../README.md) describe the additional evaluation work.
