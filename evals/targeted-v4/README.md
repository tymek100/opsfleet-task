# Portable targeted regression evaluation

This package preserves ten questions from the completed 25 October 2026 replay. `cases.json` contains their exact text and expectations. `recorded/` contains sanitized captured responses, settings, timing summary and independent SQL results. Report IDs, trace IDs and BigQuery job IDs are replaced with placeholders; public analytical rows, SQL, fingerprints and timings are preserved. These are recorded live results, not a newly executed run or synthetic analytical fixtures.

## Offline verification

From the repository root, after `uv sync --locked`:

```sh
uv run --locked python evals/targeted-v4/check.py evals/targeted-v4/recorded
```

Expected result: **55/55 checks passed**. Fifty original assertions check required intent fields, comparisons, answer content and report state. Four additional checks require analytical evidence; the final check compares all ten captured evidence sets against the independent SQL results. No credentials or network calls are needed. This is a bounded acceptance rubric, not a general semantic judge or an application language parser.

## Explicit live replay

Follow [credential setup](../../docs/setup.md). These commands incur provider usage and BigQuery work. Choose a new output directory for each attempt:

```sh
uv run --locked python evals/targeted-v4/run.py --live --output .retail-agent/reviewer-targeted-v4
uv run --locked python evals/targeted-v4/oracle.py --live .retail-agent/reviewer-targeted-v4
uv run --locked python evals/targeted-v4/check.py .retail-agent/reviewer-targeted-v4 --write
```

The runner refuses an existing directory and uses an isolated SQLite report library. It runs each question once; application-level bounded retries still apply. The oracle refuses to overwrite existing results. Preserve failures and use another directory for a new attempt. Generated local artifacts are ignored by Git.

The cancellation case seeds a synthetic report solely to test library state. Unlike the original local harness, this portable runner seeds it immediately before that case, avoiding confirmation-token expiry during earlier questions. Its synthetic revenue is never used as analytical evidence. The same ten user questions are retained. No hard deletion is performed by the runner.

Each application turn uses the configured per-question budget; ten questions do not share one cap. The independent oracle adds up to ten BigQuery queries, each capped at 100 MB billed bytes. Its SQL is handwritten independently of the application's compiler and scoped to this suite's public-data cases. Captured answers may change as the public dataset and model change; recorded numbers are not expected constants for a fresh run.

Historical final-run observations: 10/10 questions, 162.55 seconds total, median 14.145 seconds, no provider retries/repairs/fallbacks. These are not availability or latency guarantees. See [current evaluation](../../docs/evaluation.md) and the [full history](../../docs/audits/targeted-fixes-v4-2026-10-25.md).
