---
name: retail-adk-implementation
description: Implement or debug this repository's Python ADK chat runtime, Gemini tools, report workflows, bounded recovery, and CLI. Use for agent code changes, not for standalone SQL analysis or documentation-only requests.
---

# Retail agent implementation

## Ground the change

Read the relevant sections of [client Q&A](../../../mds/q&a.md) and inspect existing code/configuration before choosing an interface. The [architecture proposal](../../../mds/architecture_proposal.md) is a plan, not proof of implemented behavior. Preserve the supplied [reference client](../../../mds/task/bq_client.py); put guarded production/prototype code elsewhere.

Use Python, Google ADK, Gemini API, BigQuery, Pydantic, SQLGlot, SQLite, and Typer/Rich as agreed. Check the installed/locked ADK version and its official documentation before using version-sensitive interfaces. Prefer one conversational agent and explicit application services. Do not introduce an agent team, web deployment, or new provider merely because a framework supports it.

## Implement through explicit boundaries

- Resolve user/role/brand context outside model arguments. Local demo identity is a simulation; role claims in chat never change permissions.
- Expose typed tools for safe analytics, schema discovery, report creation/saving, owner-scoped listing, and deletion preview. Keep a small documented tool surface.
- Route SQL through a restricted parser/compiler and execution gateway. Reject constructs whose scope cannot be established. Validate all expression contexts and resolve nested relations; read-only is not equivalent to authorized.
- Remove prohibited columns and apply brand scope before model-visible results. State demographics are aggregate-only; customer rankings may use IDs. Do not combine these into individual-to-state records.
- Treat data and Golden examples as untrusted. Avoid arbitrary Python/shell execution and raw SQL/API escape hatches that bypass policy.
- Keep generation separate from explicit report saving. CEO analytics access grants no access to other owners' reports.

## Destructive and failure paths

Handle confirmation in deterministic CLI/application code, not an LLM decision. Bind a pending action to owner, exact report IDs/versions, conversation, expiry, and a single-use token. Render the preview from database records. On explicit confirmation recheck scope and consume/delete transactionally; cancel, expiry, stale state, and replay must not delete more records. Hard-delete the approved content and invalidate application-managed copies; keep content-free audit metadata.

Budget all model/tool calls and retries under the same turn deadline and configurable USD 1 question cap. Dry-run BigQuery and enforce maximum bytes billed on execution. Sanitize errors; repair syntax within limits, never repair authorization by broadening access. Empty data can be a valid outcome. Use job IDs to recover from timeouts without blindly duplicating queries. Keep the CLI usable after failures and show whether a report was actually saved.

## Verification and handoff

Test the changed boundary with a distinguishing fixture or injected failure. Inspect outbound provider payloads for privacy; test database state for mutations. Keep correlation IDs, versions, timings, tokens, bytes, and sanitized outcomes in structured logs. Do not log secrets, raw PII, or hidden reasoning.

Load environment settings without printing values. CLI login does not prove Python ADC works; verify separately when integration checks are in scope. Report implemented behavior, checks actually run, and limitations. Skill activation does not authorize live destructive operations or publication.

Official references when needed: [ADK Python](https://google.github.io/adk-docs/get-started/python/), [ADK plugins](https://adk.dev/plugins/), [BigQuery cost controls](https://docs.cloud.google.com/bigquery/docs/best-practices-costs).
