# Live debugging: long-running answers

Date: 19 November 2026. Model: `gemini-3.8-flash`. Identity: `alice` / Calvin Klein. Real Gemini and BigQuery were used, with read-only queries, isolated temporary SQLite storage and the unchanged USD 1 / 120-second turn limits. [Machine-readable results](results.json) retain all thirteen turns, including intermediate failures and source/prompt fingerprints.

## Reproduction and changes

The exact reported question was:

> Show our top five products by revenue and, separately, by distinct customers in Q1 2026.

The first reproduction finished in 65.9 seconds, so it did not establish an infinite loop. The user's trace showed an answer-reference rejection followed by another model call. Silent progress, default thirteen-second pacing, medium thinking and long duplicated output made the turn appear stuck.

Further real CLI testing exposed valid grouped citations (`[E1, E2]`) being rejected as numerical claims. The category comparison and report also hit the conservative USD 1 reservation ceiling with 8,192 output tokens reserved per model call. The category investigation tried alternative definitions after obtaining valid zero repeat rates.

The fixes normalize grouped citations, preserve source validation, accept list ordinals/exact source labels, provide actionable reference feedback, show progress and elapsed time, default to low thinking with 4,096 output tokens and no fixed pacing, and communicate the remaining allowance to the agent. Instructions require accepting valid zero results and distinguish qualifying sales, new customers and unverified seasonal assumptions. Runner/client asynchronous cleanup is bounded. Review and authorization gates remain enabled.

## Observed results

| Scenario | Configuration/stage | Seconds | Outcome |
|---|---|---:|---|
| Exact rankings prompt | Original defaults | 65.9 | Approved, but slow |
| Category comparison | Intermediate low-thinking CLI, 8,192 tokens | 35.9 | Incomplete: cost limit |
| Report | Intermediate low-thinking CLI, 8,192 tokens | 64.1 | Incomplete: cost limit |
| Exact rankings prompt | Final CLI profile, 4,096 tokens | 16.8 | Approved |
| Ranking overlap follow-up | Same CLI conversation, before grouped-citation fix | 25.3 | Approved after two reference repairs |
| Category repeat rates | Same CLI conversation | 12.9 | Approved; one query, zero rates accepted |
| Q1 report with Q2 actions | Same CLI conversation | 50.6 | Approved after a reference repair |
| Exact rankings prompt | Final code and actual local settings | 20.8 | Approved; two queries, no reference repair |
| Standalone Q1 report | Final code and actual local settings | 31.0 | Approved; one invalid-query repair, no reference repair |

The CLI run completed all four analysis turns, then saved exactly one report only on `/save`, listed it, displayed `/help`, and exited with status zero. The final standalone report did not save anything. Final ranking evidence contained two five-row tables. Final report evidence covered categories, months and quarter totals. These smoke checks and inspection are not an independent exhaustive numerical oracle or a calibrated semantic evaluation; model approval can still miss analytical mistakes. Timings vary with providers, quotas and question complexity.

## Offline regression checks

263 tests passed; seventeen live tests were deselected from the offline suite. Ruff lint/format, strict Pyright and diagram synchronization passed. New tests exercise actual ADK cancellation during the first model call, after a query and during evaluator review; stalled cleanup; continued CLI use after a deadline; visible progress; grouped citations; source labels; and budget room for six small queries plus submission/review. Their short deadlines are test-only; normal settings retain the 120-second default.

To repeat only the exact live example (may incur charges):

```sh
uv run --locked pytest -m live --force-enable-socket -s tests/test_live.py::test_live_exact_quick_start_prompt
```

For the interactive path, restart the CLI so it loads updated code and `.env` settings:

```sh
uv run --locked retail-agent chat --user alice
```

Settings used for final checks: `THINKING_LEVEL=low`, `MAX_OUTPUT_TOKENS=4096`, `MODEL_MIN_INTERVAL_SECONDS=0`; reviewer output remains capped at 2,048 tokens. Higher thinking effort and optional pacing remain configurable. Cost values in the JSON are conservative admission reservations, not provider invoices.
