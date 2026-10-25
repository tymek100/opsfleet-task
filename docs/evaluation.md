# Current evaluation evidence

The latest completed live replay (25 October 2026) passed **10/10 targeted questions**, **50 original acceptance assertions**, and **10 independent SQL evidence comparisons**. Runtime fingerprint: `6105cd2920f1c9fc`; prompt fingerprint: `80990c71abd431cd`; contract: `direct-plan-v4`. The runtime used Gemini 3.8 Flash with medium thinking.

These are targeted regression cases refined after observed failures, not a blind accuracy benchmark. The final batch took 162.55 seconds (median 14.145 seconds), with no provider retries, semantic repairs or fallback reports. Recorded paid-rate token estimates were $0.06974 for the batch and $0.31249 across all 38 attempts in that work session; these are not invoices or promised future costs. Earlier unsuccessful attempts remain in the [implementation and replay audit](audits/targeted-fixes-v4-2026-10-25.md).

## Reproduce the evidence

The [portable evaluation package](../evals/targeted-v4/README.md) includes the exact ten prompts, sanitized captured answers, independent SQL and oracle rows. Its offline checker performs 55 assertions: the original 50, four mandatory analytical-evidence checks, and one combined check of all ten SQL evidence sets. It requires no cloud credentials and makes no API calls:

```sh
uv sync --locked
uv run --locked python evals/targeted-v4/check.py evals/targeted-v4/recorded
uv run --locked pytest -q
```

The recorded run had 167 passing offline tests, with 17 live tests deselected. The documentation remediation adds no application behavior changes. Rechecking recorded artifacts verifies their consistency; it does not rerun Gemini or BigQuery. The package documents separate, explicitly opted-in live commands and isolated report state.

## Scope and limits

The ten cases cover reversed explicit baselines, disjoint periods, empty sales, report completeness, cancellation and ordered library operations, nonmutating help, unsupported metrics, and a monthly row limit. SQL agreement validates the observed raw evidence; separate checks validate derived comparisons and state transitions. Human review remains necessary for intent fidelity, useful recommendations and readability. A valid schema alone proves none of these.

Provider availability, arbitrary questions, production authorization, distributed deletion, production retrieval quality and hosted CI are not established by this sample. Use a fresh held-out set before claiming broader quality, and preserve unsuccessful first attempts.

See [historical evaluation records](audits/evaluation-history-through-2026-10-25.md) for earlier suites, failures and superseded implementations. Their test counts and design descriptions describe those historical versions, not the current runtime.
