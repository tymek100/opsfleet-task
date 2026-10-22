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
/save Q1 review
/reports
/delete Q1
/cancel
/delete Q1
/confirm <paste the exact token shown in the preview>
/quit
```

Deletion is permanent. The preview shows the exact report IDs and titles; the token expires in five minutes. Nothing is saved until `/save` (or the explicit phrase “save this report”). `/help` lists all commands.

Demo identities: `alice` → Calvin Klein; `bob` → Levi's; `ceo` → all brands. Reports remain private to their creator. These identities simulate authentication for the assignment.

No credentials needed for checks:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest
```

See [README](README.md) for capabilities and limits, [setup](docs/setup.md) for troubleshooting, and [architecture](docs/architecture.md) for the production design.
