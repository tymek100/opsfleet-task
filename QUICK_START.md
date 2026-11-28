# Quick start

## 1. Install

Use Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## 2. Configure Google access

If `.env` already contains your Google key and project, keep it. Otherwise, copy
`.env.example` to `.env` and fill in:

```dotenv
GEMINI_API_KEY=your-google-api-key
GOOGLE_CLOUD_PROJECT=your-gcp-billing-project
GEMINI_MODEL=gemini-3.8-flash
```

Gemini uses your existing Google API key. BigQuery uses separate Application
Default Credentials:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_GCP_PROJECT_ID
```

Enable the BigQuery API and grant your identity permission to create query jobs
in that project (`roles/bigquery.jobUser`). The queried tables are public:
`bigquery-public-data.thelook_ecommerce`. Query processing is billed to your GCP
project; the Gemini API uses its own key's billing setup.

No Azure login, container or observability account is needed.

## 3. Chat

```bash
uv run retail-agent chat
```

First question:

```text
Show the top five product categories by qualifying revenue in Q1 2026. Use a compact table.
```

Follow-up:

```text
Summarize the main finding in two short sentences. Do not infer why customers bought these products.
```

## 4. Use the CLI

Type `/` to open the menu. Keep typing to filter; use arrows to choose and Enter
or Tab to insert a command. Press Enter again to execute the selected command.

| Command | Action |
|---|---|
| `/help` | Show commands. |
| `/new` | Clear conversation history. |
| `/details` | Inspect the last tool calls, SQL and returned data. |
| `/skills` | List the available Markdown guides. |
| `/save report.md` | Save the last answer without overwriting an existing file. |
| `/exit`, `/quit` | Exit. |

While waiting, the spinner shows elapsed seconds and `Thinking...`. Ctrl+C during
an answer cancels that turn; the next prompt remains available. BigQuery has its
own 30-second job/wait limit and attempts cancellation when that limit expires.
Conversation memory disappears when you exit; saved Markdown files remain.

## 5. Explore the code

Open `src/retail_insight/core/loop.py` to see both nodes and the conditional edge.
Then open `agent.py` to see how `RetailAgent` inherits the loop and registers tools.
Change `prompt.md` or a file in `skills/` and restart the CLI to try your changes.

If a query hits the byte limit, narrow its columns/period or adjust
`MAX_QUERY_BYTES` in `.env`. Avoid `SELECT *` when you only need an aggregate.
`MAX_MODEL_CALLS` and `TURN_TIMEOUT_SECONDS` apply independently to each question.
