# Evaluation generations

The active replacement has offline tests in `tests/` and explicit real-model runners in `scripts/evaluate_rewrite.py` and `scripts/calibrate_reviewer.py`. See [rewrite observations](../docs/rewrite-test-observations.md) and [captured runs](rewrite/runs/README.md) for actual answers, errors, timings and review results.

The 18 cases in [rewrite specifications](rewrite/README.md) are proposed acceptance specifications, not 18 passing holdout trials. The live runs are development smoke/regression observations. Their prompts and grader expectations are excluded from Golden retrieval.

All other directories, including [single-loop-live](single-loop-live/README.md), are historical captures for retired implementations. Some historical runners import removed `Intent`, metric contracts or result views. Their source implementation and old tests are preserved under `legacy/runtime-2026-11-20/`; do not run them against the replacement and assume they validate it.

```bash
uv run --locked pytest
uv run --locked python scripts/validate_golden_bootstrap.py
```

Offline tests use injected models, isolated storage and blocked sockets. Native ADK loop tests prove orchestration and boundaries, not real-model reasoning quality. Explicit live runners call Gemini and optionally the public TheLook BigQuery dataset, using temporary report storage. Runtime approval is not treated as proof of numerical correctness.
