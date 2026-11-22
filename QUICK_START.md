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

`--golden-bootstrap` explicitly enables the synthetic, unapproved reference methods. The analyst selects examples from eligible summaries and may use none. Current numerical answers require fresh authorized queries. Without the flag, the supplied synthetic corpus is ineligible. Configure `GOLDEN_PATH` for a separately approved compatible corpus.

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

The model generates the complete answer, including optional tables, and the evaluator can request revisions. The progress indicator reports model, tool and review activity. Deadline exhaustion or reviewer unavailability returns an incomplete status; unreviewed answers are not published.

## Use synthetic data

This mode uses the real Gemini model with analytical queries against a frozen local fixture:

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

Type `/` in interactive chat to open the command menu. Typing filters commands
and highlights matching characters; **Up/Down** changes the selection.
**Enter** or **Tab** inserts the selected command. Add arguments, then press
**Enter** to execute. **Esc** dismisses the menu. Fully typed commands submit
directly. Completion covers command names; enter report IDs and confirmation
tokens explicitly. Piped input remains plain text.

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

Deletion confirmation is bound to the interactive chat that displayed the preview; one-shot commands cannot accept a later confirmation. Cancelled, expired, replayed or stale previews authorize no additional deletion. Successful deletion clears the current conversation's in-memory context; audit records contain no report text.

The report library uses `.retail-agent/reports-v2.sqlite3`. Earlier files are preserved. Explicit migration copies only the named owner's records:

```bash
uv run --locked retail-agent import-legacy .retail-agent/reports.db --user alice
```

Supply the actual existing legacy SQLite/JSON path; the filename above is an example. The source remains unchanged. Deleting an imported report deletes the new library's copy, not the separately retained legacy source.

## Tests and evaluation

Offline checks use isolated settings, temporary stores and scripted providers:

```bash
uv sync --locked --group evaluation
uv run --locked --group evaluation pytest
uv run --locked --group evaluation retail-eval validate
uv run --locked python scripts/validate_golden_bootstrap.py
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked --group evaluation pyright
```

For a real-model evaluation, set `GEMINI_API_KEY`, start Docker, and run:

```bash
uv run --locked --group evaluation retail-eval run \
  --suite smoke --repetitions 1 \
  --max-cost-usd 5 --deadline-seconds 900 --allow-unreviewed
```

This connects to or starts local Phoenix, prints experiment and trace links, executes the cases,
and publishes answer and trajectory evaluations as trials finish. Enable trace streaming for
completed spans; refresh the experiment view for new outputs and scores. One cost ceiling and deadline
cover the agent and judges. No separate grading or publishing command is needed.

For metrics, saved answers, advanced regrading, and comparisons, follow
[the testing and evaluation guide](docs/evaluation.md). Runtime Golden Knowledge and evaluation
references are separate. Regrading a saved run never executes the agent again.

## Configuration

`.env.example` lists provider, budget and storage settings. Analyst calls, evaluator calls and provider retries share one per-question budget and deadline. Counts and reserved costs are admission bounds, not invoiced charges. `MAX_MODEL_CALLS=12` allows retrieval and revisions; lower limits can leave complex requests incomplete. `TURN_TIMEOUT_SECONDS=120` includes a 30-second review reserve. The analyst defaults to low thinking; `REVIEW_THINKING_LEVEL=medium` configures the reviewer independently.

Input contact-pattern screening catches common pasted PII but is not comprehensive entity recognition. Warehouse privacy is enforced structurally before either model receives results. Production deployment still needs real authentication and controlled corpus publication.
