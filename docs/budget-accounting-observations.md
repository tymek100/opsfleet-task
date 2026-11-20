# Per-prompt budget accounting regression

This investigation concerns a reported two-turn conversation: a Q1 2026 versus Q4 2025 performance comparison, followed by a category-level explanation of the revenue change. Each user prompt creates its own budget; conversation history does not carry consumed allowance into the next prompt.

## Reported failure

The local trace for conversation `25525bec7935` recorded the comparison as approved in **33.398 seconds**. Its follow-up stopped with **`cost_budget` after 25.028 seconds**, rather than reaching the 120-second deadline. The follow-up made six analyst model calls and three successful warehouse queries; those queries took **5.264 seconds** combined. No reviewer call began, and no provider retry or query failure was recorded.

The old ledger permanently accumulated each model call's conservative reservation: serialized request bytes priced as input tokens plus the maximum output allowance. It separately recorded actual token counts but did not release unused reservation amounts. The follow-up therefore held **USD 0.683827** in accumulated reservations. Its logged 41,264 input tokens and 1,217 output tokens correspond to **USD 0.097132 at the application's configured rates**, excluding warehouse charges; this arithmetic is not a verified provider invoice. A further USD 0.168576 was protected for review under those settings, and the next model-call estimate could not fit.

The trace records event names, timings, statuses and evidence IDs rather than SQL or arguments. It establishes where the run stopped, but does not establish whether the three queries were redundant or whether a completed answer would have been correct.

## Regression prompts

The reusable `quarterly_category_followup` case in [the observation runner](../scripts/evaluate_rewrite.py) uses the exact reported prompts:

1. Compare our Q1 2026 performance with Q4 2025. Show qualifying revenue, distinct customers, distinct orders, and average order value, including percentage changes.
2. Identify the three product categories contributing most to the revenue change. Show the remaining categories as “Other” so contributions reconcile to the total change.

The live replay command is:

```bash
uv run --locked python scripts/evaluate_rewrite.py --live --backend bigquery --user alice \
  --golden-bootstrap --case quarterly_category_followup \
  --output evals/rewrite/runs/budget-accounting-02
```

This retains the configured per-prompt USD 1 cap and 120-second deadline, uses temporary isolated report storage, and does not modify the user's report library. Synthetic Golden methods may be retrieved, but answers must come from fresh authorized warehouse evidence. Frozen fixture expectations are not used to judge BigQuery results.

Choose a new output directory for another replay; the runner refuses to overwrite existing observations.

## Accounting interpretation

The updated ledger separates `spent_usd` (reported model usage priced at configured rates) from `reserved_usd` (outstanding or unknown model attempts plus conservative query holds). `accounted_usd` is their sum; `remaining_usd` is the unconsumed portion of that prompt's cap. Completed model calls replace their own reservations with measured input, output and thinking-token usage. Input admission still uses the conservative serialized-byte ceiling, but excess reservations for both input and output are released when reliable usage arrives. Query reservations retain their maximum-byte estimate.

These fields are application accounting, not verified invoices. Missing or unreliable usage must retain its conservative reservation. Model-call, tool-call, query-count, reviewer and deadline controls continue to apply, and a new follow-up prompt receives a fresh budget.

## Verification

The complete offline suite passed: **202 tests in 5.56 seconds**, with the two existing SDK/socket warnings. Ruff checks, formatting and Pyright passed. Budget/provider tests cover refunding only the completed attempt, duplicate settlement, accounting for thinking tokens, unknown usage, retries, partial-response failures, concurrent reservations, cap enforcement and fresh follow-up budgets.

The first [sandbox attempt](../evals/rewrite/runs/budget-accounting-01/observations.md) failed to connect to the model service. Both prompts recorded two `ConnectError` attempts, zero reported tokens and zero database queries; unknown attempts retained their conservative holds. This is an environment connectivity observation, not an analytical trial. The authorized network retry was captured separately rather than overwriting those artifacts.

The [live BigQuery replay](../evals/rewrite/runs/budget-accounting-02/observations.md) completed both prompts with the unchanged USD 1 cap and 120-second deadline. It used `gemini-3.8-flash`, low analyst thinking and medium reviewer thinking, with synthetic Golden methods enabled. No reports were saved or read from the user's library.

| Prompt | Seconds | Model calls | Warehouse queries | Reviewer decisions | Reported model USD | Conservative query holds USD |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| Quarterly performance comparison | 28.913 | 5 | 1 | approve | 0.076086 | 0.000568 |
| Category contribution follow-up | 66.067 | 9 | 4 | revise, approve | 0.230582 | 0.002274 |

Every model call produced exactly one settlement event. The follow-up completed with USD 0.767144 remaining after reported model cost and conservative query holds. Its first reviewer decision at 44.506 seconds requested a grounding revision; the agent obtained additional category evidence and was approved at 66.065 seconds. The persisted trace records the issue category but not the rejected candidate or full feedback, so the exact rejected claim is not established. This replay demonstrates that correction and final review can complete after the point where the old accumulated-reservation ledger stopped; it does not demonstrate lower latency for this prompt.

### Numerical inspection

The comparison reproduced the reported figures: qualifying revenue **10,469.10 → 11,168.60**, customers **155 → 167**, orders **155 → 167**, and AOV **67.54 → 66.88**. Its SQL used the correct UTC half-open quarter boundaries over the scoped qualifying `sales` relation. AOV and displayed percentage changes agree to the requested precision.

The final follow-up selected the three largest **positive** category changes:

| Category | Q4 2025 revenue | Q1 2026 revenue | Change |
| --- | ---: | ---: | ---: |
| Outerwear & Coats | 1,724.73 | 2,657.15 | +932.42 |
| Tops & Tees | 358.00 | 630.99 | +272.99 |
| Pants | 519.36 | 712.98 | +193.62 |
| Other: remaining 19 categories | 7,867.01 | 7,167.48 | -699.53 |
| Total | 10,469.10 | 11,168.60 | +699.50 |

The [post-run arithmetic checks](../evals/rewrite/runs/budget-accounting-02/arithmetic-checks.json) recomputed differences and group sums from the captured evidence using decimal arithmetic. All 12 checks matched, including exact reconciliation to the first answer, the top-three selection, category growth rates, accounting totals, one settlement per model call and no report mutations. These checks use recorded query outputs; they are not an independently re-queried warehouse oracle.

The model interpreted “contributing most” as the largest positive increases, not the largest absolute movements. Rounded contribution percentages in its final answer sum to **100.01%**, while monetary contributions reconcile exactly. The final output is also more verbose than the request requires. These are recorded presentation/interpretation limitations; this fix changes cost accounting rather than the analytical prompt or rendering. Runtime approval alone is not a correctness grade, and this two-prompt replay is not a production reliability estimate.
