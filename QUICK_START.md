# Quick Start

## Install

Use Python 3.12 and uv from the repository root:

```bash
uv sync --locked --python 3.12
cp .env.example .env
```

If `.env` already exists, keep it and update only the settings you need. Set `GEMINI_API_KEY` and `GOOGLE_CLOUD_PROJECT` using your own credentials. The example contains no working secrets.

For BigQuery, establish Python Application Default Credentials:

```bash
gcloud auth application-default login
```

CLI login alone does not establish Python ADC. The configured billing project must allow BigQuery query jobs and reading the public TheLook dataset. Gemini and BigQuery calls may incur charges; the default per-question admission budget is USD 1, using configurable conservative rates.

## Start a conversation

```bash
uv run --locked retail-agent chat --user alice --golden-bootstrap
```

Demo identities: `alice` can analyze Calvin Klein; `bob` can analyze Levi's; `ceo` can analyze all brands. These are local simulations, not production authentication. Report libraries remain owner-private.

`--golden-bootstrap` enables synthetic, unapproved demonstration methods explicitly. The model chooses when to retrieve one; it must query fresh authorized data for current numerical answers. Without that flag, the supplied synthetic corpus is ineligible. Configure `GOLDEN_PATH` for a separately approved compatible corpus.

Example conversations:

```text
Show our top five products by revenue and, separately, by distinct customers in Q1 2026.

Among those five revenue leaders, which reached the most distinct customers?

What was our average order value in Q1 2026? Answer in one short paragraph without a table.

Which category earned the most revenue per active selling day in Q1 2026?

Consult a relevant Golden example, then calculate our Q1 2026 repeat-customer share from current authorized data.

Write a short Q1 2026 report and suggest two measurable actions for Q2. Do not save it yet.
Save that exact report as Q1 2026 Review.
```

The model writes the complete answer, including optional tables. The evaluator can request corrections. A progress indicator reports model/tool/review activity. An exhausted deadline or unavailable reviewer produces a clear incomplete status instead of an unreviewed answer.

## Use synthetic data

This still calls the real Gemini model, but all analytical queries run against a frozen local fixture:

```bash
uv run --locked retail-agent chat --user alice --backend fixture --golden-bootstrap
```

The fixture has two sold Calvin Klein products, one unsold product and invented transactions. A request for five products should explain that fewer qualify. Its Q1 revenue is 375, across six orders and five customers. It contains no geography. These are demonstration figures, not live company results.

One-shot example:

```bash
uv run --locked retail-agent ask \
  "What was our average order value in Q1 2026? No table." \
  --user alice --backend fixture --golden-bootstrap
```

## Reports and evidence

In the interactive chat, type `/` to open the command menu. Keep typing to filter
commands and highlight matching letters, then use **Up/Down** to select a command.
**Enter** or **Tab** inserts the selected command; add any arguments and press
**Enter** to run it. **Esc** dismisses the menu. Fully typed commands can be
submitted directly. Suggestions cover command names; report IDs and confirmation
tokens are entered explicitly. Piped input remains plain text.

| Command | Behavior |
| --- | --- |
| `/details` | Inspect the latest turn's SQL and result evidence |
| `/reports` | List your saved reports |
| `/read ID` | Display an owned saved report |
| `/delete TEXT` | Preview reports matching literal text |
| `/confirm TOKEN` | Permanently delete exactly the previewed records |
| `/cancel` | Cancel the pending deletion |
| `/new` | Clear conversation context and cancel pending deletion |
| `/help`, `/exit` | Help or exit |

Deletion confirmation belongs to the same interactive chat that displayed the preview. A one-shot command cannot provide a later interactive confirmation. Cancelling, expiring, replaying or changing a preview does not authorize additional deletion. Successful deletion clears application conversation copies; audit records contain no report text.

The new library uses `.retail-agent/reports-v2.sqlite3`. Earlier files are not overwritten. Explicit migration copies only the named owner's records:

```bash
uv run --locked retail-agent import-legacy .retail-agent/reports.db --user alice
```

Supply the actual existing legacy SQLite/JSON path; the filename above is an example. The source remains unchanged. Deleting an imported report deletes the new library's copy, not the separately retained legacy source.

## Checks and observed prompts

Offline checks do not require credentials:

```bash
uv run --locked pytest
uv run --locked python scripts/validate_golden_bootstrap.py
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
```

Explicit live smoke run, using a temporary report library:

```bash
uv run --locked python scripts/evaluate_rewrite.py --live --golden-bootstrap \
  --output evals/rewrite/runs/my-fixture-run
```

Use a new output directory each time. Add `--backend bigquery --case rankings` for the real warehouse ranking case. The runner writes JSON captures and Markdown observations. Its approval/number-presence checks do not establish semantic correctness; inspect the actual answers and evidence. See [how to inspect captured runs](evals/rewrite/runs/README.md#what-to-inspect).

## Configuration

`.env.example` lists provider, budget and storage settings. Analyst calls, evaluator calls and provider retries share the same question budget and deadline. Counts and reserved costs are admission bounds, not an invoice. `MAX_MODEL_CALLS=12` leaves room for retrieval and corrections; smaller values can cause complex requests to finish incomplete. `TURN_TIMEOUT_SECONDS=120` includes review, with a 30-second reserved completion allowance. The analyst uses low thinking by default; `REVIEW_THINKING_LEVEL=medium` gives the completion reviewer a separate setting.

Input contact-pattern screening catches common pasted PII but is not comprehensive entity recognition. Warehouse privacy is enforced structurally before either model receives results. Production deployment still needs real authentication and controlled corpus publication.
