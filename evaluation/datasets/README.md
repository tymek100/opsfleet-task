# Evaluation data

**Status:** 43 synthetic pilot cases and 40 paired judge controls are implemented and independently checked in code. Human reference review, human judge calibration, and a sealed holdout remain pending. These assets support diagnostics; they do not establish production accuracy.

`golden/` contains evaluation tasks and trusted references. It is separate from runtime `knowledge/golden/`, which provides reusable methods to the analyst. Only identity and user steps enter the task adapter. The harness configures frozen SQL fixtures, the clock, report seeds, faults, and Golden Knowledge availability; reference answers, facts, and criteria remain grader-only.

- `golden/dev/`: 36 development cases, including three focused challenges.
- `golden/regression/`: 7 synthetic reproductions of reported failure families.
- `golden/holdout/`: intentionally empty until independently reviewed and sealed.
- `judge_calibration/development/`: 24 code-authored controls from 12 families.
- `judge_calibration/validation/`: 16 controls from 8 separate families. Labels are provisional, not human annotations.

Cases freeze raw fixture hashes and typed per-turn references. `evaluation.data.validate_dataset()` checks schemas, fixture hashes, deterministic SQL derivation, oracle facts, and calibration span integrity without a model call. `oracle_verified` means programmatic reference consistency; it does not mean human admission. The `smoke` suite selects four cases, including the three-turn category-summary regression.

The independent oracle uses raw rows, Decimal arithmetic, and sets; it imports no application query compiler or gateway. Gateway queries are used only in differential tests. Nine fixture variants distinguish scope, mixed-brand orders, repeat purchases, item/order statuses, UTC boundaries, ties, category contributions, empty periods, zero baselines, changed leaders, and untrusted text. The `challenge` suite additionally covers nullable source fields, offsetting category changes with zero net growth, and 25-row results exceeding the initial 20-row preview. The pagination reference procedure is tested through the actual query and bounded-read tools.

Pilot v2 adds these three cases without changing the original 40 case files or six raw/SQL fixture pairs. Existing experiment artifacts remain comparable against their frozen v1 inputs; whole-suite v1/v2 scores have different denominators.

Pilot v3 aligns mandatory grading with explicit requests. Ranking prompts request IDs and metric values; overlap requests its count and precise word limit; causal, cohort, and inactivity prompts request every required aggregate. The category-summary follow-up explicitly requests its signed category contributions and combined remainder. The quarter-boundary criterion no longer demands an unasked July explanation. Fixtures, numerical truth, case IDs, and suite counts are unchanged.

Frozen v1/v2 experiments retain their original prompts and references. A failure caused solely by one of these former extra requirements is a case-validity finding, not evidence of poorer agent quality. Report that limitation and use newly frozen v3 runs for comparisons; do not silently repair historical run inputs.

The authoring recipes are retained for reproducibility:

```bash
uv run python -m evaluation.fixtures.build_challenges
uv run python -m evaluation.datasets.build_pilot
uv run python -m evaluation.datasets.build_calibration
uv run retail-eval validate
```

Regeneration changes canonical assets and must precede a newly pinned baseline/candidate comparison. Never regenerate references from an agent answer or accept runtime review as truth. Every generated record explicitly sets `human_reviewed=false`; review must be recorded before claiming verified pilot or holdout results.
