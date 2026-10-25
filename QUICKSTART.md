# Quick start

Run locally with Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install). Gemini and BigQuery run remotely. Use your own credentials.

```sh
uv sync --locked --python 3.12
cp .env.example .env
```

Edit `.env`: set `GEMINI_API_KEY` from Google AI Studio and `GOOGLE_CLOUD_PROJECT` to your project ID. Keep the default model unless your account requires another supported model.

```sh
gcloud auth application-default login
uv run --locked retail-agent doctor
uv run --locked retail-agent chat --user alice
```

`doctor` checks configuration presence only. CLI login (`gcloud auth login`) alone does not configure Python Application Default Credentials. Your project needs BigQuery job creation permission and access to the public dataset; enable the BigQuery API if needed. No dataset download is necessary.

Try:

```text
List the top 10 best sellers by revenue and by number of customers for Q1 2026.
Show total revenue and a monthly breakdown for that same quarter.
Create a report for Q1 2026 with insights and action items for Q2.
/details
/save Q1 review
/reports
/delete Q1
/cancel
/delete Q1
/confirm <paste the exact token shown in the preview>
/quit
```

The default view shows findings and definitions. Use `/details` for tables and query diagnostics, or `/details REPORT_ID` for a saved report.

Deletion is permanent. The preview shows the exact report IDs and titles; the token expires in five minutes. Nothing is saved until `/save` (or the explicit natural-language request “save this report”). `/help` lists all commands.

Demo identities: `alice` → Calvin Klein; `bob` → Levi's; `ceo` → all brands. Reports remain private to their creator. These identities simulate authentication for the assignment.

No credentials needed for checks:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest
```

See [README](README.md) for capabilities and limits, [setup](docs/setup.md) for troubleshooting, and [architecture](docs/architecture.md) for the production design.

Use `/clear` to clear the terminal screen while keeping the current conversation and reports. Use `/new` to start a new conversation. Plain `clear` is not a command.

Rankings and monthly trends appear as tables. Dates in sales summaries show the inclusive last calendar day; `/details` retains exact exclusive query boundaries. Amounts have no currency symbol unless a currency is explicitly established.

The default model is `gemini-3.8-flash` with `THINKING_LEVEL=medium`. Exact numbers
and tables are rendered by the application. An optional **AI commentary** section
adds model-written interpretation after a separate model review. If that step fails,
the verified findings remain available. Set `COMMENTARY_ENABLED=false` in `.env`
to omit these extra calls. High reasoning and review can noticeably increase latency.
`/details` shows the conservative budget reservation, not your Google invoice;
content-free `provider_usage` events include thinking tokens for cost estimation.
