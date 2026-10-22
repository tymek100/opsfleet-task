# Technical explanation of the prototype

The prototype is a local Python CLI. Gemini interprets questions and proposes typed analysis requests; a deterministic compiler constructs parameterized BigQuery SQL. A single ADK agent coordinates tools and follow-ups. SQLite stores private reports, sanitized analytical answers, confirmation snapshots and content-free audit records. No cloud deployment is required.

## Implementation map

| Module | Responsibility |
|---|---|
| `cli.py` | Local identity selection, chat loop, explicit save/read/preview/confirm commands, readable failures |
| `agent.py` | One ADK `LlmAgent`, structured final response, typed tools, follow-up context, explicit metric-override checks |
| `quality.py` | Evidence-bound facts, derived metrics, action-period validation, labelled hypotheses and deterministic report rendering |
| `metrics.py` | Deterministic churn direction and percentage-point comparisons, including undefined baselines |
| `models.py` | Immutable identity and analysis contracts; unknown fields rejected; dates/filter combinations validated |
| `queries.py` | Application-owned SQL compiler, brand scope, metrics, parameter binding and SQLGlot parse verification |
| `bigquery.py` | Lazy ADC client, dry run, byte cap, stable job recovery, bounded results and safe errors |
| `model.py`, `budget.py` | One transient model retry; shared cost/call/query/deadline budget |
| `reports.py` | Owner-scoped library, exact deletion snapshots, expiry, atomic recheck/delete/consume, retention cleanup |
| `privacy.py` | Text redaction and rejection of recognizable pasted contact data; structural source minimization is primary |
| `render.py` | Tables and effective definitions rendered from evidence independently of narrative |
| `observability.py` | Correlated JSON events excluding prompts, SQL parameters, result rows and provider exception messages |

The project uses `src/retail_agent`, strict Pyright, Ruff, uv, and one `pyproject.toml` for dependencies and tool settings. `uv.lock` pins the tested dependency graph. No broad type-checker exclusions are enabled. A narrow annotated exception covers an untyped BigQuery SDK property.

Google ADK was chosen for tool orchestration, callbacks, session handling and the Google SDK integration. The candidate confirmed this is their **first ADK project**. The implementation experience demonstrated here consists of integrating and testing these capabilities for this assignment; it does not imply previous production ADK experience. One agent and independently testable application services are sufficient; additional agent frameworks would add complexity without a concrete need.

The runtime uses `gemini-3.5-flash`, configurable through `GEMINI_MODEL`. On the development account, 3.8 Flash repeatedly returned 503 while 3.5 Flash successfully generated answers. This is an observed availability decision, not a general benchmark. Before changing models, rerun tool compatibility, numeric/intent and adversarial evaluations, and update conservative rate assumptions. The locked ADK version uses an experimental structured-response tool internally; offline and live tests exercise it. No code execution, browsing, email, or model-controlled report confirmation is enabled.

## Query contract and access

`run_analysis(spec_json)` accepts a validated JSON object. Example:

```json
{"kind":"sales","dimension":"product","start":"2026-01-01","end":"2026-04-01","rank_by":"revenue","limit":10}
```

Supported sales dimensions: total, product, brand, category, month, state, customer. Metrics: revenue, units, distinct customers, distinct orders. Optional filters: brand list, product IDs, internal customer ID; optional Complete-only definition. Churn supports total/brand cohorts and an explicit 7–365 day inactivity window (default 90).

SQL is generated dynamically from this contract. Arbitrary model-authored SQL is deliberately not executed. Enumerated dimensions and metrics select application-owned expressions; values use BigQuery parameters. Unknown JSON fields, raw SQL fields, role claims, unsupported combinations and out-of-scope brands fail before querying. SQLGlot checks generated query structure; it is not presented as a general-purpose SQL security validator. Extending the analytical language requires adding a compiler branch, result contract and boundary tests. This limits flexibility but makes the authorized surface reviewable within the assignment.

Every query scopes `products.brand` before customer histories or aggregations. Both item and order statuses are considered. Joins include order user consistency; item-grain sums avoid multiplying revenue. A mixed-brand order contributes only authorized items. CEO skips brand restriction but does not bypass privacy or report ownership. Demo identities are hardcoded trusted local configuration: Alice/Calvin Klein, Bob/Levi's, CEO/all brands. Users cannot change roles through chat. A person with local code/database access can bypass the demo; production authentication and IAM are design work, not simulated security claims.

The compiler never selects contact names, emails, street addresses, postal codes or coordinates. Customer analysis returns internal IDs only. The users table is joined only for state aggregation; state mode rejects customer and product-ID filters and suppresses cohorts below five distinct customers. No model-visible row combines a customer ID and state. Five is a documented conservative assumption, not a client-specified threshold, and is not differential privacy: sophisticated differencing across aggregates remains a production privacy review item.

The gateway checks exact expected output columns and scalar types, caps rows, and sanitizes catalog text. Prompt instructions add defense against indirect injection, while the tool contract and confirmation boundary contain its effects. Text patterns reject obvious pasted personal data and redact recognizable contact details in narrative/catalog strings. These patterns are not comprehensive name/entity detection; users should not paste personal information, and a production ingress DLP layer needs a measured language-specific policy. The stronger guarantee is that the transactional source's prohibited columns never reach the LLM or output.

## Metrics and evidence

See [metric definitions](metrics.md). Every successful analysis carries the effective request, authorized scope, definition text, rows, SQL hash, BigQuery job ID, query timestamp and latest purchase timestamp within the returned groups. That timestamp is not a promise about upstream ingestion freshness. Tables and analytical statements are rendered directly from evidence. The model selects metric references rather than composing unrestricted factual prose. This is a deliberately bounded report language; it does not claim to validate arbitrary natural-language entailment or prove that the selected facts fully answer every user intent.

The agent asks for missing material periods, handles follow-ups using the last four turns, and can perform several requests in a question. Current conversation context is in memory; sanitized answers are persisted for retention and debugging, but interactive sessions do not resume after process restart. No automatic saving: `/save TITLE` or “save this report” explicitly persists the latest successful analysis. Natural-language deletion invokes preview only; CLI commands remain available for deterministic operation and model outages.

## Report quality boundary

Every final answer with fresh evidence must supply a structured `Narrative`. `facts` contains exact metric IDs, not model-written values or explanations. `quality.py` builds the metric catalog from authorized query results and computes units/order, revenue/unit, revenue/order, churn percentage-point changes, and adjacent-period total changes in code. Cross-period totals require identical scope, filters and definitions; they are labelled as totals, not normalized daily rates. Zero denominators remain undefined. Profit margin is not an available metric and cannot be asserted through this contract.

The application renders factual sentences with their actual values, scope, periods and evidence citations. Nonempty free-form analytical messages and unknown metric references are rejected. Hypotheses use an explicit, limited vocabulary (seasonality, promotions, availability, product mix) and templates that always label them **unverified**, including what extra evidence is needed. Referencing a query does not turn a hypothesis into a demonstrated association or cause.

Actions select from four reviewed templates: cross-selling experiments, demand investigation, assortment review, or retention experiments. Each requires a compatible, defined baseline metric, a start/end date and an optional numeric proposed target. Units/order is required for cross-selling; customer/order counts cannot substitute for basket size. Inactivity-share targets use fractions from 0 to 1. Proposed owners and targets are visibly proposals, with no promise of feasibility or impact.

For the assignment's quarter-based report scenario, code resolves the requested action quarter from explicit Q1–Q4/year wording, or an explicit “next quarter” after a quarter-boundary analysis period. It rejects ambiguous or unsupported timing rather than accepting model-supplied dates. Q2 2026 actions must use `[2026-04-01, 2026-07-01)`; February cannot appear in the generated action templates. Arbitrary natural-language/monthly action scheduling is not implemented; the model is instructed to clarify timing before queries.

A rejected narrative gets **one tool-free correction attempt** using the same model, pacing, cost/call budget and remaining deadline. Only verified metric/context data and safe validation codes are supplied; failed prose is not retained in the saved answer or logs. The correction cannot run queries, save or delete reports. Provider-level transient retries still follow the shared retry policy. If correction fails, is unavailable, or cannot fit within limits, the answer explicitly states that narrative validation failed and shows verified figures; unsupported explanations/actions are withheld. `Answer.quality_status` distinguishes `validated`, `fallback`, and `not_applicable` (non-analytical replies).

This boundary trades expressive freedom for auditable output. It does not establish that a recommended intervention is wise, that a target is achievable, or that the model chose all relevant evidence. Broader analytical intent, usefulness, hypothesis relevance and UX still require independent evaluation. Extending the report vocabulary means adding typed metrics/action templates and regression cases rather than weakening the boundary with unrestricted prose.

## Confirmation and permanent deletion

`/delete TEXT` does a case-insensitive literal search over the owner's report title and stored answer/evidence; `/delete *` selects all; `/delete-conversation` restricts to this conversation. Natural language uses the same preview service. The preview displays exact IDs, titles and conversations, plus a random token. The token itself is withheld from the LLM. The database stores SHA-256(token), owner, conversation, report ID/version snapshot and five-minute expiry.

`/confirm TOKEN` is parsed by the CLI and never delegated to the model. `BEGIN IMMEDIATE` serializes confirmation; the service checks owner, session, expiry, all report versions, then deletes exactly the snapshot and consumes pending actions atomically. New matching reports are untouched. A stale set rolls back entirely. Wrong owner/session, expiry, cancellation and replay cannot delete content. CEO is simply another report owner.

SQLite uses `secure_delete=ON`, DELETE journaling and private file permissions. Deletion also removes persisted chat answers for affected conversations and clears active model context/last answer. No report content is written to audit events. Previously displayed terminal output, OS snapshots, and user-created exports cannot be recalled. Production backup/restore requirements are in the HLD. Existing independent reports remain independent objects even if their text resembles a deleted report.

## Failure handling and budgets

Default limits: $1 conservative model/query reservation per question, six model attempts, six analysis attempts/queries, 120 seconds, 4,096 output tokens, 100 MB maximum bytes billed per query, and at most 50 sales rows/100 churn rows. Configuration is external. Input UTF-8 payload bytes conservatively bound input tokens for admission, including bounded context; configured rates intentionally include headroom. Output thinking is disabled. Reservations are not refunded, so the displayed amount is a conservative allowance consumed, **not actual invoiced spend**. Fixed infrastructure cost is outside the question budget.

BigQuery dry run estimates work; the actual job also has `maximum_bytes_billed`. A stable random job ID supports status lookup after uncertain submission; no blind resubmission. Results have bounded waits; timeouts request cancellation. Server-side cancellation is best effort. Client retries that could duplicate jobs are disabled. Source query errors are replaced by safe categories; raw exceptions/SQL are not exposed to the model or user.

Malformed analysis JSON gets schema guidance and a bounded repair opportunity. Query syntax errors receive a safe error and can be retried through a corrected supported request; the agent cannot patch the compiler or run arbitrary SQL. Genuine empty periods remain empty; the prompt permits only one same-period diagnostic. Total sales over no rows has null revenue and zero counts, not fabricated revenue. All failures share the hard attempt limits. Model calls are spaced at least 13 seconds apart by default for free-tier quotas (configurable; set 0 only with suitable quota). A retry honors a provider RetryInfo delay up to the remaining deadline and a 60-second ceiling. Model 429/5xx failures retry once, with a new reservation, only before any partial response. Invalid analytical final JSON enters the bounded report-quality repair when evidence is available; unsuccessful repair returns verified figures. Other invalid responses and timeouts produce an actionable error while the CLI stays open. Library operations do not need a model call.

## Traceability

Each question gets a trace ID. Events record model version, user/conversation IDs, call sequence, usage tokens, retry status, job/hash/bytes, result row counts, evidence IDs and final outcome. Quality events include rejection codes, repair attempts, pass/fallback status and repair token usage, without rejected content. The saved answer ties its typed requests and evidence to that trace. Raw user prompts, tool payloads, secrets, provider exception bodies and hidden reasoning are not logged. Local diagnostic logs do not implement a production exporter or managed retention service; SQLite chat/audit retention cleanup runs on store startup. See the HLD for centralized monitoring, trace access, retention and incident response.

## Extension points and limits

Add a graph tool that takes validated evidence IDs rather than SQL; add email as an explicit authorized outbound action with recipient/content preview; add web trends as separately attributed untrusted context. Each capability needs its own permission, budget, trace and tests. Do not give the model a shell or generic network client.

Golden retrieval, persistent learned preferences, production SSO/IAM, nontechnical persona UI, automated promotion gates, distributed jobs/circuit breakers, managed observability, and cloud deployment are **design-only**. Illustrative Golden trios are supplied; there is no real client bucket. The optional retrieval demo was deferred to focus on mandatory prototype boundaries and evidence.

Sources checked during implementation: [ADK structured responses](https://adk.dev/agents/llm-agents/), [ADK callbacks](https://google.github.io/adk-docs/callbacks/), [ADK Python](https://github.com/google/adk-python), [Gemini model catalog](https://ai.google.dev/gemini-api/docs/models), [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [BigQuery cost controls](https://cloud.google.com/bigquery/docs/best-practices-costs), [Pyright configuration](https://github.com/microsoft/pyright/blob/main/docs/configuration.md).
