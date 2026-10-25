# Assignment coverage

The four mandatory prototype requirements have working code and behavioral tests. Other production requirements are explicitly designed rather than claimed as implemented. See [architecture](architecture.md), [technical explanation](technical-design.md) and [evaluation](evaluation.md).

| Requirement | Working prototype | Production design / remaining scope | Evidence |
|---|---|---|---|
| 1. Hybrid intelligence | Illustrative Question → SQL → Report trios and format; no runtime retrieval | Reviewed versioned bucket, permission/version-filtered hybrid retrieval, fresh query execution and stale-example retirement | `golden-trios.json`, `golden-trio.schema.json`, HLD knowledge lifecycle |
| 2. Safety, PII, product access | Trusted demo identities, brand-first compiled queries, prohibited source fields absent, aggregate-only state cohorts, bounded tools, obvious pasted PII checks | SSO, curated-view IAM, gateway execution identities, measured DLP and privacy review | `models.py`, `queries.py`, `bigquery.py`, `privacy.py`; query/gateway/ADK boundary tests |
| 3. High-stakes oversight | Exact owner-scoped preview; permanent hard delete only via token command; expiry, replay protection, version checks, transactional mutation and managed-copy purge | Web confirmation endpoint with CSRF protection, distributed invalidation, deletion ledger and backup policy | `reports.py`, `cli.py`; deletion state tests and structured-planner library tests |
| 4. Learning loop | In-process follow-ups and structured evidence persistence | User preference store, explicit/inferred preferences, reviewed feedback to trios/evals, gated releases | HLD learning section; no claim of autonomous learning |
| 5. Resilience | Bounded malformed-plan repair, safe empty results, one transient model retry, shared budgets, query dry run and byte cap, uncertain-job recovery, timeout cancellation, usable CLI | Circuit breakers, distributed job idempotency, durable job failure state, explicit redrive and fallback operations | `budget.py`, `model.py`, `bigquery.py`; budget, provider-fault and ADK recovery tests |
| 6. Quality assurance | Synthetic numeric oracles, policy/property tests, report state tests, planning/execution tests and the optional ADK narrative runner, opt-in live scenarios | Frozen holdouts, release canaries, human review, task-based executive UX studies | `tests/`, evaluation report and demo guide |
| 7. Observability | Correlated JSON events, model usage, job/hash/bytes, result/evidence IDs, retries/outcomes; content-free audit | OTel pipeline, restricted sanitized message correspondence, alerting, dashboards and retained debug traces | `observability.py`, planner/executor log assertions; HLD metrics |
| 8. Persona agility | Fixed versioned instructions in prototype | Nontechnical editor, automatic quality gate, atomic publish and rollback without deployment; no manual approval | HLD persona section |

Additional deliverables:

- CLI chat, follow-ups, analysis and reports/actions: `retail-agent chat`; supported analytical language documented in the technical explanation.
- BigQuery integration against all four specified tables: joins compile from typed requests; users is accessed only for state aggregates.
- Setup on another machine: root README/QUICKSTART, `.env.example`, `pyproject.toml`, `uv.lock`, external ADC and API key.
- Framework rationale and experience: technical explanation explicitly records the candidate's first ADK project.
- Architecture diagram: embedded Mermaid plus editable draw.io source under `docs/diagrams/`.
- Public GitHub submission: repository exists; this implementation has not been published unless separately committed/pushed.

Known tradeoff: this prototype does not execute arbitrary LLM-authored SQL. It dynamically compiles a bounded analysis language into SQL, covering the requested capabilities with explicit extension points. This is a conscious safety/design decision and should be explained in the interview.
