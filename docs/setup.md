# Setup and operational notes

Use [QUICKSTART](../QUICKSTART.md) for the shortest path. Tested environment: Python 3.12.12 on macOS ARM64; dependency versions are in `uv.lock`. Other supported Python 3.12+ machines should use the same lockfile; OS portability is not claimed as an executed test matrix.

## Install and authenticate

1. Install uv and the Google Cloud CLI. Clone the repository and run `uv sync --locked --python 3.12`.
2. Copy `.env.example` to `.env` and set your project ID and Gemini API key. Do not reuse the author's credentials. If `.env` already exists, edit it without overwriting it.
3. Run `gcloud auth application-default login`. The Python client uses Application Default Credentials; `gcloud auth login` alone is insufficient.
4. Ensure BigQuery API access and `bigquery.jobs.create` in your billing project (normally BigQuery Job User), plus public dataset read access. Dataset location is US. No raw-data write permission is needed.
5. Run `uv run --locked retail-agent doctor`, then `uv run --locked retail-agent chat --user alice`.

Optional pip route: from a clean Python 3.12 virtual environment, `pip install .` installs declared runtime dependencies and the `retail-agent` executable. This route resolves version ranges and is less reproducible than the tested uv lockfile route; uv is the recommended reviewer path.

## Configuration

All defaults are defined in `config.py` and documented in `.env.example`. Environment variables take precedence over `.env`. Important knobs: `GEMINI_MODEL`, `QUESTION_BUDGET_USD`, `MAX_QUERY_BYTES`, `MAX_MODEL_CALLS`, `MAX_QUERIES`, `TURN_TIMEOUT_SECONDS`, admission prices, and `DATA_DIR`. Changing models requires checking structured tools, quotas, rates and evaluations. Free-tier allowances do not disable application budgets.

Local runtime files default to `.retail-agent/` and are ignored by Git. SQLite holds private reports, sanitized answers, pending token hashes and content-free audit events. JSON diagnostic events are in `events.log`. The local machine owner is trusted; demo identity selection is not production authentication. `/new` starts a new in-memory conversation. Chats do not resume automatically across process restarts; saved reports remain accessible through their owner.

## Commands and examples

```sh
uv run --locked retail-agent users
uv run --locked retail-agent chat --user bob
uv run --locked retail-agent chat --user ceo
```

Inside chat, `/help` describes deterministic commands. Analysis examples:

- “Compare product 1316 and 23816 in Q1 2026.”
- “Show monthly revenue for 2026 so far.”
- “Show top customers by revenue in Q1 2026.”
- “What data is available and what can you analyze?”
- “Why did our churn rate spike last month? Verify whether it increased.”
- “Create a Q1 2026 report including insights and actions for Q2.”

Not every product belongs to every identity; a query may legitimately return no authorized matching data. The application explains unsupported requests instead of exposing raw SQL execution.

## Verification

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest --cov=retail_agent --cov-report=term-missing
```

Offline tests block network sockets (Unix sockets remain available for asyncio), use synthetic data/fake keys, and do not read `.env`. Live tests are excluded by default and require explicit marker selection AND networking:

```sh
uv run --locked pytest -m live --force-enable-socket -s tests/test_live.py
```

The live test runs four questions and may incur charges up to four configured question budgets. It uses temporary report storage and does not modify a user's existing report library. The public dataset changes, so exact numbers and timing may differ.

## Troubleshooting

| Symptom | Action |
|---|---|
| Python credentials unavailable | Run `gcloud auth application-default login`; verify the ADC account can create query jobs in your configured project. |
| Project/API access denied | Check project ID, BigQuery API enablement, location US, job permissions and quota project. No application code should print tokens. |
| Gemini key rejected | Replace the key locally in `.env`, verify API access and restrictions; never paste it into logs/issues. |
| Gemini 429/503 | One bounded retry is attempted. Wait and retry a smaller question, or deliberately select another evaluated model. Local library commands continue to work. |
| Scan/cost/call limit | Narrow period/dimensions; adjust an explicit limit only after reviewing expected spend. |
| Empty result | Check period, permitted brands and metric definition; do not infer zero for an undefined churn denominator. |
| Expired/stale confirmation | Request a new deletion preview. Never reuse a token or bypass ownership checks. |
| Local storage failure | Check disk/path permissions; do not assume a save/delete succeeded without its confirmation. |

The SDK may emit an experimental warning for ADK's structured final-response tool. It is a known framework dependency, not a live-data error. See the evaluation report for tested behavior and remaining limitations.
