# Proposed evaluations for the replacement agent

[holdout_cases.json](holdout_cases.json) contains **18 acceptance specifications, not executed tests or a sealed benchmark**. Known failures are marked `regression`; novel cases are marked `holdout_candidate`. Fixture variants, independent numerical oracles and the execution harness still need implementation. No new-agent pass rate is claimed.

These cases describe acceptance criteria for the current agent; see the [testing approach](../../docs/architecture.md#testing). They are separate from the [synthetic Golden retrieval corpus](../../knowledge/golden/README.md). Neither questions nor answers, expected results, oracle SQL or grader rubrics from this directory may enter the agent's retrieval index or runtime prompts. The user question is supplied normally when its case is executed.

## What the cases measure

- Analytical outcomes: independent revenue/customer rankings, distinct-order metrics, unseen metrics, scoped history, empty cohorts and corrected false premises.
- Presentation: model-authored prose, tables when requested, complete answers, and no automatic table/policy appendices.
- Adaptation: follow-ups preserve the selected population; changed data defeats copying numbers from Golden examples; irrelevant methods can be ignored.
- Completion: evaluator feedback leads to correction in the same analyst conversation; only the exact approved answer is finalized.
- Boundaries: retrieval eligibility, privacy before every model call, report ownership, explicit saving, exact confirmed deletion, shared deadlines and bounded recovery.

The runner must allow different successful tool sequences, SQL formulations and answer wording. Only explicit user format constraints should be checked as constraints; an optional table is not inherently better than prose.

## Before publishing evaluation results

1. Build distinguishing fixture variants with different leaders, denominators, periods and scopes. Keep these separate from the bootstrap fixture. Write independent arithmetic/set-based oracles; do not regenerate expected results by executing the agent's own SQL.
2. Use a development split for prompts, tool descriptions, retrieval tuning and reviewer calibration. Freeze untouched holdout candidates and their rubrics before scoring. Once a held-out failure influences implementation or Golden content, move it into regression/development and replace it for future generalization claims.
3. Test application permissions, persistence, outbound payloads and budgets deterministically. Check observed database state after writes; model prose is not proof that an action happened.
4. Grade analytical claims against independent facts. Calibrate the reviewer and presentation grader on correct and incorrect candidates, including unsupported causality and fabricated values. Report reviewer false accepts and false rejects separately from analyst task success.
5. Run repeated real-model trials for the selected task set and compare retrieval enabled/disabled on a development sample. Record model/version/settings, corpus version, fixture hash, attempts, timings, usage, outcome, selected tools and failure reasons. Scripted tool/reviewer outputs remain labelled harness tests.
6. Establish release thresholds before tuning against the held-out set. All required access/privacy/mutation assertions must pass. Publish denominators, skips and failures; a few successful examples do not establish a production percentile.

The replacement is now implemented. See [captured runs](runs/README.md) for real-model smoke/regression observations and [testing](../../docs/architecture.md#testing) for the offline checks. This specification collection remains separate from those observations and is not itself a passing holdout suite.

The [ranking interpretation regression cases](ranking_grounding_cases.json) replay a reported unsupported explanation and three authored controls using captured public evidence. Run them with `scripts/calibrate_reviewer.py --live --suite ranking_grounding --timeout 120 --output <new-output.json>`. The two-turn `ranking_followup` case in `scripts/evaluate_rewrite.py` exercises the analyst and reviewer together. See the [failed first replay](runs/ranking-grounding-01/observations.md) and [follow-up replay with limitations](runs/ranking-grounding-02/observations.md); expected labels remain outside model inputs and these cases are excluded from Golden retrieval.

The `skill_reference` case explicitly requests a runtime skill and its reference, without business queries. The [reference-loading capture](runs/runtime-skills-reference-01/observations.md) records that behavior; the [ranking replay](runs/runtime-skills-rankings-02/observations.md) records autonomous skill selection and its limitations. Runtime skills remain separate from both Golden examples and this evaluation corpus.
