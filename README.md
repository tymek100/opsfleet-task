# Retail Analysis Assistant

A local CLI for brand-scoped analysis of the public TheLook ecommerce dataset. Ask questions in natural language, discuss the results, generate reports with action items, and explicitly save or permanently delete your own reports.

**Start here:** [Quick start](QUICKSTART.md) · [Implemented prototype](docs/technical-design.md#implemented-prototype) · [Production HLD](docs/architecture.md) · [Current evaluation](docs/evaluation.md)

Gemini interprets the question into a structured plan. Python validates permissions and supported operations, executes the plan directly and checks evidence completeness; no regex-based natural-language parser is used. Reports use verified metric references, clearly labelled hypotheses, and dated action templates. One bounded repair is allowed; otherwise the assistant shows verified figures with a validation warning. See [report quality controls and limits](docs/technical-design.md#report-quality-boundary).

## What works

- Product rankings by revenue or distinct customers; product comparisons; monthly and total metrics; customer rankings by internal ID; aggregate state analysis.
- Multi-step questions and in-process follow-ups, including a documented churn proxy and quarterly reports with proposed actions.
- Trusted demo brand permissions applied before aggregation. Prohibited customer contact fields never enter the analytical result schema.
- Private saved reports. Natural-language deletion previews and deterministic, exact, expiring confirmation tokens for permanent deletion.
- Bounded model/query attempts, conservative cost reservations, BigQuery dry runs and byte caps, transient model retries, and correlated safe diagnostics.
- Offline behavioral tests, an opt-in live scenario suite, strict Pyright and Ruff, plus a credential-free CI workflow.

Gemini proposes a **typed analysis plan**; Python dynamically compiles it into parameterized BigQuery SQL. The agent does not execute arbitrary generated SQL or Python. This covers the demonstrated analytical surface and keeps authorization reviewable. Unsupported analyses require extending and testing the compiler, rather than bypassing it.

## Run locally

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), Google Cloud CLI, your own GCP project and Gemini API key.

```sh
uv sync --locked --python 3.12
cp .env.example .env
# Edit .env: GOOGLE_CLOUD_PROJECT and GEMINI_API_KEY.
gcloud auth application-default login
uv run --locked retail-agent doctor
uv run --locked retail-agent chat --user alice
```

If `.env` already exists, edit it instead of copying over it. `doctor` checks configuration presence, not provider connectivity. Python ADC is separate from `gcloud auth login`. BigQuery needs job-creation permission in your project and access to the public US dataset. Details and troubleshooting are in [setup](docs/setup.md).

The default is `gemini-3.8-flash` with `THINKING_LEVEL=medium`; model and limits are configurable. Verified tables remain application-rendered; explicitly requested model-written commentary passes a separate semantic review. Simple tables need only the planning model call. The local process calls Gemini and BigQuery over the internet. It stores reports/diagnostics under the ignored `.retail-agent/` directory. No application cloud deployment is required.

| Demo identity | Analytics scope | Report access |
|---|---|---|
| `alice` | Calvin Klein | Own reports only |
| `bob` | Levi's | Own reports only |
| `ceo` | All brands | Own reports only |

These identities simulate authentication. Local machine/code/database access is trusted; production SSO and IAM are covered in the HLD.

## Example interaction

```text
You> List the top 10 best sellers by revenue and by number of customers for Q1 2026.
      [Two fresh rankings, scope, definitions and evidence citations]
You> /details
      [Data tables and query diagnostics]
You> Show total revenue and monthly trends for the same quarter.
      [Fresh follow-up analysis preserving the period]
You> Create a Q1 2026 report with insights and action items for Q2.
      [Report draft; not yet saved]
You> /save Q1 review
      Saved report <id>.
You> /delete Q1
      [Exact IDs/titles and expiring confirmation token; nothing deleted]
You> /cancel
      Cancelled. Nothing deleted.
```

The bracketed lines describe output; they are not a fabricated transcript. See [demo guide](docs/demo.md) for the complete review flow. `/help` lists `/reports`, `/read ID`, `/delete-conversation`, `/confirm TOKEN`, `/new`, and `/quit`. Successful confirmation hard-deletes the exact previewed reports, purges managed chat copies and clears active context.

## Definitions and safety

Default revenue sums eligible item sale prices, excluding Cancelled/Returned orders **and** items. Customer counts are distinct IDs. UTC date ranges are start-inclusive/end-exclusive. The churn proxy is the share of seasoned customers with no authorized-brand purchase in the preceding 90 days; it is not monthly churn incidence. [Metric definitions](docs/metrics.md) explain the denominator, overrides and limitations.

Source customer names, emails, addresses, postal codes and coordinates are excluded structurally. State data is aggregate-only with at least five customers and no individual filters. Prompt instructions and text redaction are additional defenses; they do not turn free text into a formally safe channel. Evidence tables come directly from validated query results, while model prose still requires factual evaluation. Transaction patterns support hypotheses, not definitive causal claims.

## Development and checks

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest --cov=retail_agent --cov-report=term-missing
```

All tool settings and dependency declarations live in `pyproject.toml`; resolved versions live in `uv.lock`. `--locked` rejects stale dependency declarations instead of changing the lockfile. Use `uv add` to intentionally change dependencies.

Offline tests use synthetic fixtures and scripted model responses through the real planning/execution boundaries and optional ADK narrative runner. They block external sockets and do not load `.env` or ADC. Live testing is explicit and may incur charges:

```sh
uv run --locked pytest -m live --force-enable-socket -s tests/test_live.py
```

The current executed evidence and limitations are recorded in [evaluation](docs/evaluation.md). Passing a small suite does not establish production reliability or a guaranteed interview ranking.

## Repository layout

```text
src/retail_agent/       CLI, agent, compiler, cloud adapter, reports and controls
tests/                 Offline behavior/oracle tests and opt-in live scenarios
docs/                  Required submission documents, Golden examples and diagrams
mds/                   Client Q&A, original assignment and planning/research history
.agents/skills/        Development guidance, not runtime agent tools
```

The [technical explanation](docs/technical-design.md) gives module boundaries, chosen technologies, failure handling and extension points. The candidate's ADK experience is explicitly stated as a first project.

## Production proposal and limits

The HLD covers all eight assignment requirements, including reviewed Golden Knowledge retrieval, user/system learning, nontechnical persona publishing through an automated gate, SSO, cloud storage, retention, monitoring and evaluation. Those services are **design-only**. Golden trios are illustrative samples; there is no supplied client bucket or working retrieval demo.

Other limits: a bounded analytical language, simulated identities, no session resumption across restarts, no complete free-text PII detector or narrative fact verifier, no production distributed jobs/circuit breaker, and no instant recall of terminal output/user exports. The public dataset and provider quotas change. Default 13-second model-call spacing accommodates small free-tier quotas; configure it for your account. See [requirement mapping](docs/requirements.md) for exact coverage.

Latest verification: [targeted comparison, cancellation and messaging fixes](docs/audits/targeted-fixes-v4-2026-10-25.md): all 10 new targeted cases passed the final replay, with independent SQL/state checks and 167 offline tests. The preceding [20-case holdout](docs/audits/fresh-holdout-v3-2026-10-25.md) records the original failures.

The current interpretation architecture and research sources are documented in [model planning](docs/model-planning.md).
