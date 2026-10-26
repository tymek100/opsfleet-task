# Quick Start Guide

Set up the local CLI, try analytical conversations and follow-ups, and save a report. For implementation and evaluation details, see [technical reasoning](docs/technical_reasoning.md); for the proposed production system, see [architecture](docs/architecture.md).

[Setup](#setup) · [Configuration](#configuration) · [Example conversations](#example-conversations) · [Verification](#verification) · [Troubleshooting](#troubleshooting)

Run the shell commands below from the repository root.

## Setup

Run locally with Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install). Gemini and BigQuery run remotely. Use your own credentials.

```sh
uv sync --locked --python 3.12
test -e .env || cp .env.example .env
```

Edit `.env`: set `GEMINI_API_KEY` from Google AI Studio and `GOOGLE_CLOUD_PROJECT` to your project ID. Keep the default model unless your account requires another supported model.

```sh
gcloud auth application-default login
uv run --locked retail-agent doctor
uv run --locked retail-agent chat --user alice
```

`doctor` checks configuration presence only. CLI login (`gcloud auth login`) alone does not configure Python Application Default Credentials. Your project needs BigQuery job creation permission and access to the public dataset; enable the BigQuery API if needed. No dataset download is necessary.

Choose one of the seven [example conversations](#example-conversations) below. Each prompt has its own copyable block.

Use **↑ / ↓** at the chat prompt to recall earlier prompts and slash commands, edit them, and press Enter to submit. Input history lasts for the current CLI process only and is not written to a history file. It is separate from the agent’s conversation context; `/new` resets that context but keeps the terminal input history.

The default view shows findings and definitions without source footers or evidence IDs. Ask which data was used for a plain-language source explanation. Use `/details` for tables and query diagnostics, or `/details REPORT_ID` for a saved report.

Example report titles exist in your library only after you save them; evaluation runs use separate test storage. If a deletion request finds no matching report, use `/reports` to check your saved titles.

Deletion is permanent. The preview shows the exact report IDs and titles; the token expires in five minutes. Nothing is saved until `/save` (or the explicit natural-language request “save this report”). `/help` lists all commands.

Demo identities: `alice` → Calvin Klein; `bob` → Levi's; `ceo` → all brands. Reports remain private to their creator. These identities simulate authentication for the assignment.

Tested environment: Python 3.12.12 on macOS ARM64; dependency versions are in `uv.lock`. Other supported Python 3.12+ machines should use the same lockfile; OS portability is not claimed as an executed test matrix.

Optional pip route: from a clean Python 3.12 virtual environment, `pip install .` installs declared runtime dependencies and the `retail-agent` executable. This route resolves version ranges and is less reproducible than the tested uv lockfile route; uv is the recommended reviewer path.

## Configuration

All defaults are defined in `config.py` and documented in `.env.example`. Environment variables take precedence over `.env`. Important knobs: `GEMINI_MODEL`, `QUESTION_BUDGET_USD`, `MAX_QUERY_BYTES`, `MAX_MODEL_CALLS`, `MAX_QUERIES`, `TURN_TIMEOUT_SECONDS`, admission prices, `DATA_DIR`. Changing models requires checking structured tools, quotas, rates and evaluations. Free-tier allowances do not disable application budgets.

Local runtime files default to `.retail-agent/` and are ignored by Git. SQLite holds private reports, sanitized answers, pending token hashes and content-free audit events. JSON diagnostic events are in `events.log`. The local machine owner is trusted; demo identity selection is not production authentication. `/new` starts a new in-memory conversation. Chats do not resume automatically across process restarts; saved reports remain accessible through their owner.

Use `retail-agent users` to list identities or `chat --user bob` / `chat --user ceo` to switch sessions. `/help` lists commands; `/clear` clears only the screen and `/new` starts another conversation. Customer/product-ID filters may correctly return no authorized matching data. The conversations below cover rankings, follow-ups, inactivity checks and report saving. Use `/help` for the complete command list, including deletion preview, cancellation and exact-token confirmation.

## Example conversations

Run `uv run retail-agent chat --user alice` for the Calvin Klein demo scope. **Copy one block, submit it, and wait for the answer before copying the next block.** Keep each set in the same conversation. Before starting a different set, reset the context:

```text
/new
```

If a provider timeout occurs, retry that prompt before continuing to a dependent follow-up. These examples use English. Amounts are unscaled source price units; the dataset does not specify a currency. Public data can change, so check relationships and calculations rather than memorizing numbers. Conversational wording can vary; writing and review share the configured question budget.

### 1. Find products that win on two measures

Compare revenue leaders with products bought by the most customers.

**Ask:**

```text
Show our top 5 products by revenue and, separately, by distinct customers in Q2 2025.
```

**Follow-up 1:**

```text
Which products appear in both rankings?
```

**Follow-up 2:**

```text
For just those shared products, show revenue and distinct customers side by side.
```

**What to look for:** The follow-ups should keep only products present in both displayed lists, without fetching a different population.

### 2. Explore customer value

Start with high spenders, then compare the value of their orders.

**Ask:**

```text
Show our top 5 customers by revenue in 2025, using customer IDs.
```

**Follow-up 1:**

```text
Add their order counts and average order value.
```

**Follow-up 2:**

```text
Keep the three customers with the highest average order value among these five.
```

**What to look for:** Average order value means revenue divided by distinct orders. The final selection comes from the five shown customers, not a new global ranking.

### 3. Find peak months and reorder the result

Find the strongest months while keeping the original figures intact.

**Ask:**

```text
Show our monthly revenue, orders and distinct customers for 2025.
```

**Follow-up 1:**

```text
Keep the three months with the highest revenue, including their revenue and order counts.
```

**Follow-up 2:**

```text
Show those same three months in chronological order instead.
```

**What to look for:** The last turn should change only the order of the selected months, preserving their values and columns.

### 4. Compare categories and ask how the answer was calculated

Use a natural-language follow-up, then ask the analyst to explain the arithmetic.

**Ask:**

```text
Show our top 8 product categories by revenue in 2025. Include revenue, orders, distinct customers, and revenue per order.
```

**Follow-up 1:**

```text
Which of those categories had the highest revenue per order, and how many orders did it have?
```

**Follow-up 2:**

```text
How did you work that out? Explain the calculation in plain English.
```

**What to look for:** The short answer and explanation are written by Gemini from verified facts. The explanation should use the selected category's revenue and orders, with no fresh database query.

### 5. Compare quarters fairly

Distinguish a change in total sales from a change in revenue per calendar day.

**Ask:**

```text
Compare our total revenue in Q1 2026 with Q4 2025. Show the absolute and percentage change, using Q4 2025 as the baseline.
```

**Follow-up 1:**

```text
Add average daily revenue and the number of calendar days for both quarters.
```

**Follow-up 2:**

```text
Explain how you calculated the revenue percentage change and why the daily comparison can differ.
```

**What to look for:** The baseline must remain Q4 2025. Daily revenue uses calendar days, including days with no sales; the explanation should not invent a cause for the change.

### 6. Investigate inactivity without assuming a spike

Check the premise, then change the inactivity definition explicitly.

**Ask:**

```text
Did our customer inactivity rate increase during Q4 2025? Use a 90-day inactivity threshold and show eligible and inactive customer counts at both quarter boundaries.
```

**Follow-up 1:**

```text
Repeat the same analysis with a 60-day inactivity threshold.
```

**Follow-up 2:**

```text
Explain what this inactivity percentage means and which customers are included.
```

**What to look for:** The agent should verify the direction from the data, preserve the quarter, and apply the new 60-day definition. An empty eligible cohort is undefined, not a zero-percent rate.

### 7. Draft a report, then save it explicitly

Prepare an analytical draft with next steps before adding it to your private library.

**Ask:**

```text
Prepare a Q2 2025 sales report with total revenue, monthly revenue, top 5 products and recommended actions for Q3 2025. Do not save it yet.
```

**Follow-up 1:**

```text
Save it as "Q2 demo review".
```

**Follow-up 2:**

```text
List my saved reports.
```

**What to look for:** The first turn must not save anything. Suggested actions are proposals, not proven causes or invented numeric targets. After the second turn, the report should appear in your own library.

Example report titles exist only after you save them. Tests use isolated storage; they do not populate your personal report library. Restarting the CLI clears active context, while explicitly saved reports remain available.

## Verification

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest --cov=retail_agent --cov-report=term-missing
```

Offline tests exercise the actual pattern filter, including provider-boundary rejection, title persistence, benign IDs/dates/amounts and known detection gaps. Network sockets are disabled (Unix sockets remain available for asyncio), credentials are synthetic, and tests do not read `.env`. Live tests are excluded by default and require explicit marker selection AND networking:

```sh
uv run --locked pytest -m live --force-enable-socket -s tests/test_live.py
```

The basic live smoke test runs four questions and may incur charges up to four configured question budgets. It uses temporary report storage and does not modify a user's existing report library. The public dataset changes, so exact numbers and timing may differ.

## Troubleshooting

| Symptom | Action |
|---|---|
| Python credentials unavailable | Run `gcloud auth application-default login`; verify the ADC account can create query jobs in your configured project. |
| Project/API access denied | Check project ID, BigQuery API enablement, location US, job permissions and quota project. No application code should print tokens. |
| Gemini key rejected | Replace the key locally in `.env`, verify API access and restrictions; never paste it into logs/issues. |
| Gemini 429/503/504 or timeout | One bounded retry is attempted. Wait and retry a smaller question, or deliberately select another evaluated model. Local library commands continue to work. |
| Conversational wording could not be validated | The verified table remains available. Retry the explanation or inspect `/details`; no unsupported prose is published. |
| Scan/cost/call limit | Narrow period/dimensions; adjust an explicit limit only after reviewing expected spend. |
| Empty result | Check period, permitted brands and metric definition; do not infer zero for an undefined churn denominator. |
| Expired/stale confirmation | Request a new deletion preview. Never reuse a token or bypass ownership checks. |
| Local storage failure | Check disk/path permissions; do not assume a save/delete succeeded without its confirmation. |

The runtime uses native structured output for the optional ADK narrative. See the [current evaluation](docs/technical_reasoning.md#evaluation-and-limitations) for tested behavior and the [portable targeted suite](docs/technical_reasoning.md#reproduce-the-ten-targeted-cases) to reproduce the earlier targeted regression set. Provider timeouts and unavailable-service errors remain possible even when local checks pass.
