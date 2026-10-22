# Making this an exceptional interview submission

Research date: 21 October 2026. This is a proposed execution and review plan, not a claim about implemented features or measured results. “Top 1%” is an aspiration: we have no evidence about other candidates or the assessors' scoring distribution.

The strongest submission would make a reviewer confident that we understand both the business question and the consequences of letting an LLM operate software. Deliver a small working system with visible evidence of correctness, clear failure behavior, and a credible production design. The brief explicitly emphasizes system design, technical explanation, and an elegant prototype. Our priorities should follow that weighting.

Client decisions in [q&a.md](q&a.md) take precedence over recommendations here. The existing [architecture proposal](architecture_proposal.md) remains the baseline; this document identifies what to tighten and what evidence to produce.

## 1. What the research says, and how we apply it

These are primary sources. The application to this interview is our judgment, not a claim that the sources define OpsFleet's assessment criteria.

| Finding | Source | Application to our submission |
|---|---|---|
| Simple, composable workflows are a strong starting point; abstraction can obscure what an agent is doing. | [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | One ADK agent, a small tool surface, explicit limits, and readable policy code. Be able to explain every model/tool round trip. |
| Excessive permissions and autonomy create risks, including unconfirmed destructive actions. | [OWASP: Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) | Keep query access narrow and execute deletion through a deterministic confirmation handler. |
| Prompt injection can arrive through user input and retrieved content; filtering alone is insufficient. | [OWASP: Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html) | Treat Golden examples, product names, and tool results as untrusted data; authorization must survive malicious model output. |
| Authorized BigQuery views can expose subsets without granting access to source datasets. | [Google: Authorized views](https://docs.cloud.google.com/bigquery/docs/authorized-views) | Explain the production database boundary precisely and distinguish it from the public-data demo. |
| Dry runs and maximum bytes billed help control query costs; `LIMIT` is not a general scan-cost control. | [Google: Estimate and control costs](https://docs.cloud.google.com/bigquery/docs/best-practices-costs) | Show actual query admission controls and measured bytes, not just a sentence about cost awareness. |
| Agent evaluation should cover both tool behavior and final responses. | [Google ADK: Evaluation](https://adk.dev/evaluate/) | Evaluate required safety events and answer quality; allow multiple valid analytical paths. |
| A convincing transcript is different from a verified change in application state. | [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) | After “saved” or “deleted,” verify database state. Use deterministic grading for objective properties and human review for usefulness. |
| SQL equivalence is better assessed through behavior across distinguishing data cases than exact SQL text matching. | [Zhong et al.: Semantic Evaluation for Text-to-SQL with Distilled Test Suites](https://arxiv.org/abs/2010.02840) | Test result semantics on carefully chosen fixtures; one coincidentally correct answer is insufficient. |
| Sensitive prompt and response content should not be captured in telemetry by default. | [OpenTelemetry: GenAI span conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md) | Record versions, outcomes, IDs, costs, and sanitized diagnostic details without copying customer data into logs. |
| ADK plugins provide runner-wide lifecycle hooks for policy and monitoring. | [Google ADK: Plugins](https://adk.dev/plugins/) | Consider a shared policy/telemetry plugin, while keeping security checks in the tool services themselves. Pin a tested ADK version; verify its API before coding. |

## 2. Five things the reviewer should be able to verify

| Priority | Claim we want to earn | Concrete evidence |
|---|---|---|
| 1 | Access and privacy rules hold independently of model obedience. | Adversarial queries rejected; no prohibited values in captured model requests; cross-user report access denied. |
| 2 | The agent understands the business question. | Correct rankings, a precisely defined churn comparison, and a useful quarterly report with evidence. |
| 3 | Destructive actions and failures are controlled. | Exact deletion preview, replay/ownership tests, and a bounded recovery demonstration. |
| 4 | The design can be operated in production. | Specific service boundaries, identity flow, cost accounting, retention, and failure paths for the stated scale. |
| 5 | Someone else can review and run it easily. | Clean installation, external credentials, a short demo, requirement-to-evidence links, and honest limitations. |

The most valuable optional addition is a small retrieval demonstration showing a useful analytical method being reused. It comes after all mandatory behavior is verified. A new dashboard, agent team, or deployment does not compensate for a broken permission check.

## 3. Make the analytical semantics unusually clear

### Revenue and top sellers

Define the grain before writing SQL: one `order_items` row is a purchased item; a joined order is not an additional sale. Use actual item `sale_price`, not catalog `retail_price`, for revenue. Document exclusions for cancelled/returned items and orders and how conflicting statuses are handled. These are implementation defaults under the client's permission to choose definitions.

Produce two rankings for the first demo: top products by eligible revenue and top products by distinct eligible customers. Group by product ID, display its name, use deterministic tie-breaking, and specify the period. Multiple purchases by the same customer count once in that product's customer count. Apply brand scope before either calculation. Explain that customer counts across products are not additive.

### Churn: resolve the ambiguity before celebrating a result

“No purchase in 90 days” does not uniquely define a monthly churn rate. There is a difference between the share of customers currently inactive and the rate of customers becoming inactive during a month.

For an initial prototype, use a documented **90-day inactivity share at month end**: among customers with at least one eligible purchase before the boundary, count those with no eligible purchase in the preceding 90-day window. Use a half-open window `[boundary - 90 days, boundary)`, UTC, and authorized-brand purchases only. Include numerator and denominator. If the denominator is zero, the rate is undefined, not zero. Present this as our chosen interpretation and allow a different definition when requested.

For “spike last month,” compare the latest complete month with the preceding month, showing percentage-point change and base counts. Identify changes in the customer population as well as changes in inactivity. If useful, inspect a fixed cohort as a separate diagnostic so changing denominators do not masquerade as behavioral change. Verify the spike exists; an answer that politely rejects a false premise demonstrates judgment.

Historical calculations must ignore purchases after their as-of boundary. Current order statuses can still contain later returns or cancellations, so document whether historical results are restated using current eligibility or reconstructed from available event timestamps. Do not claim historically exact “what we knew then” reporting without sufficient event history.

### Quarterly reports

Clarify the year when “Q1” is ambiguous. Use calendar quarters in UTC and disclose incomplete periods or missing comparison history. Structure a useful executive report as: headline, key measures and comparison, supported findings, limitations, and actions. Tie each action to a finding and a proposed success measure. Present targets and owner roles as proposals, not established company commitments. Generating a report must not silently save it.

### Evidence carried through the workflow

Give each executed analysis a compact evidence record: effective brand scope, metric version/overrides, UTC boundaries, SQL hash, job ID, result schema, row count, approved result values, and data-as-of information. Save reports with enough sanitized evidence to remain understandable after the 90-day chat retention period.

Generate factual tables from validated results in code. Ask the model for interpretation and evidence references, then check numeric references. This reduces unsupported numbers; it does not prove the entire narrative correct. Avoid claiming that a second LLM “verifies everything.”

## 4. Build a security boundary we can explain under questioning

The framework cannot be the sole boundary. The application resolves identity, permissions, SQL admission, output contracts, and side effects. Tool parameters never select the acting user or grant a CEO role.

**Prefer a deliberately restricted dynamic SQL interface.** Let Gemini construct SQL over a documented set of safe logical relations. Resolve every base relation to a trusted, brand-scoped projection using a tested parser/compiler path. Reject unsupported constructs rather than trying to safely rewrite arbitrary BigQuery SQL within an interview time budget. Still support meaningful dynamic aggregation, filters, comparisons, and joins—three hardcoded answers would not meet the assignment.

Explicitly restrict direct dataset paths, wildcard tables, system metadata, scripts, writes, external access, remote functions, and unapproved functions. CTE names and aliases must not shadow trusted relations to escape scope. Read-only SQL alone does not make a query authorized. A forbidden column in `WHERE` can leak information even if it is absent from `SELECT`; inspect all expression contexts.

Keep customer-ranking data and geographic aggregates in separate approved interfaces. Do not expose row-level state alongside customer IDs to the model and hope the final answer aggregates it. A proposed minimum group size is an additional control, not a proof against re-identification or repeated-query inference; describe that residual risk.

Production should use private curated data and execution identities that cannot read raw PII. Explain exactly how a user's brand scope reaches the database/query gateway. A shared service account does not turn end-user identity into automatic row filtering. For the public-data prototype, acknowledge that users can independently query the public dataset: we demonstrate application authorization, not secrecy of the public source.

Use synthetic PII canaries in tests to inspect complete outbound model payloads, tool responses, saved content, and logs. Cover user-pasted sensitive data too. Column exclusion handles source-table PII; arbitrary personal information in free text requires an additional input policy, and regexes cannot guarantee detection of every name/address. State that limitation honestly.

## 5. Make deletion an excellent, small feature

Implement `request → exact preview → explicit confirmation → transactional hard delete`, with cancel, expiry, ownership recheck, and single-use action IDs. Render the preview from database records, not an LLM-written summary. The model can request a preview; it cannot manufacture a confirmation event.

The pending action binds the owner, conversation, report IDs and versions, expiry, and token. New matches added after preview must not be swept into the deletion. A different user, expired token, replay, or stale version must not delete anything. In one transaction, consume the action and remove the approved records. Report actual affected IDs/counts.

Delete application-managed report artifacts and invalidate linked caches/content copies; preserve only content-free audit events. Explain backup purge/restore handling in the HLD and distinguish immediate application deletion from physical backup expiration. The client has requested no recovery, so a soft-delete implementation would contradict the requirements.

## 6. Prove resilience with a tiny, meaningful evaluation suite

Create a fixed synthetic fixture with two brands, shared customers, a mixed-brand order, duplicate purchases, returns, tied rankings, zero-activity periods, and timestamps at month/churn boundaries. Do not use seed Golden examples as the only evaluation questions. Hold out paraphrases and different filters to test whether behavior generalizes.

| Evaluation | Required observable result |
|---|---|
| Revenue vs catalog price; duplicate purchases | Correct sale-price sum and distinct-customer count |
| Shared customer and mixed-brand order | Manager's metrics exclude all restricted-brand contributions |
| Customer ID with state; encoded forbidden column | Blocked before model-visible personal data is returned |
| Nested query, CTE shadowing, `UNION`, forbidden predicate | No escape from the permitted query surface |
| Prompt injection in a question or Golden example | No privilege escalation or unconfirmed mutation |
| “Delete everything” followed by cancel | No database change |
| Confirm as another user; replay; stale preview | No unauthorized or additional deletion |
| Valid confirmation | Exact approved records disappear; another owner's records remain |
| SQL syntax error | Limited repair attempt, successful answer or clear bounded failure |
| Genuine empty result | No invented data and no silent scope/time expansion |
| Simulated 429/timeout | Deadline/retry budget respected; CLI remains usable |
| Cost estimate exceeds budget | Query/model call not started; understandable explanation |
| Follow-up with a narrower period | Context retained while evidence and metrics are recomputed |
| False churn-spike premise | Correct comparison, transparent correction of the premise |

Tests should assert final database state and provider-boundary inputs, not just friendly text. Validate policy/compiler logic locally and use a small BigQuery integration set for dialect correctness. SQLite fixtures alone do not validate BigQuery SQL semantics.

Publish a compact evaluation report with case count, actual passes/failures, model/config versions, fixture date, and known gaps. Target zero failures on the finite security/confirmation suite, while acknowledging that passing a finite suite is not proof of universal safety. For live model behavior, report the small number of trials honestly; do not infer production p95 reliability from three demo calls. If budget permits, repeat the three priority scenarios a few times and report consistency.

## 7. Make costs and debugging tangible

Before execution, dry-run SQL and enforce `maximum_bytes_billed` on the real job. Bound output size, query count, model rounds, generated tokens, and total elapsed time. Share budgets across retries. Use a known BigQuery job ID to recover status after timeouts instead of blindly resubmitting. The USD 1 budget is configurable; maintain dated price assumptions and report estimate uncertainty.

An effective debug view shows a sanitized timeline: request accepted, definition selected, SQL admitted, job completed, results validated, answer produced. Include correlation IDs, policy version, model/prompt version, timings, bytes billed, token counts, retries, and outcome. Keep raw provider exceptions and personal data out of ordinary logs. Do not log hidden model reasoning.

Use JSON logs locally; describe their mapping to OpenTelemetry and Cloud Monitoring in production. Separate 90-day conversation/debug payloads from one-year content-free audit metadata. Track successful-task cost, not only average token cost: repeated failures can be inexpensive individually yet expensive overall.

## 8. Show production judgment at the actual requested scale

The confirmed scale is around 1,000 questions and 100 reports/day, a few concurrent users, and 1M new rows/day. A single application service plus managed storage and a worker for long jobs is a reasonable starting design. Explain scale limits and triggers for change; the assignment does not require Kubernetes or a microservice per tool.

The HLD should make these decisions reviewable:

- **Existing data:** Query existing BigQuery data on user demand and disclose available timestamps. Roi confirmed on 22 October 2026 that there is no cron-based analysis; remove the earlier proposed daily ingestion pipeline from application scope.
- **Serving:** OIDC → trusted user/brand context → scoped session → orchestration → constrained analytics gateway → safe results. Every cache key includes scope and definition versions to prevent cross-scope reuse. Access-revocation lifecycle handling is out of scope per Roi.
- **Jobs:** Long reports use bounded worker execution, idempotency, status/progress, and retry rules. Saving is a separate authorized action.
- **Knowledge:** Versioned sanitized trios, editor/reviewer workflow, permissions, semantic/text retrieval, schema compatibility, and retirement of stale examples. Never automatically promote a model answer because a user liked it.
- **Persona:** Non-technical form → automated quality gate → versioned publish or rejection → rollback. Security/numeric checks are mandatory and deterministic where possible. Persona publication has no manual approval; Golden Knowledge does.
- **Retention:** 90-day chats, reports until hard deletion, one-year audit events. Include derived content, indexes, caches, and backup restore behavior.
- **Failure:** For each dependency, document timeout, retryability, degraded behavior, and what the user sees. Missing retrieval must not silently substitute an invented business definition.

For cost planning, derive the ceiling clearly: 1,000 questions at a USD 1 cap permits up to USD 1,000/day in variable spend. That is arithmetic, not an estimate of actual spend or evidence of an approved total budget. Provide measured prototype costs and a separate hosting/storage estimate with dated pricing if completing the final production estimate.

## 9. Golden Knowledge: a small optional demonstration with a point

Seed three illustrative trios aligned to the demo: product ranking, churn diagnosis, and quarterly reporting. Include scope, metric definitions, SQL/schema version, limitations, review status, and provenance. Label any invented figures explicitly; preferably use results from a reproducible synthetic fixture.

If the mandatory work is complete, add lightweight local retrieval using tags/text relevance—no vector service required for three examples. Show which example was selected and how it changed the analysis, such as prompting a denominator check for churn. Current results must come from a new query. Include one paraphrased query absent from the seeds. Do not claim a retrieval quality improvement without a comparison.

## 10. The reviewer experience is part of the deliverable

Open the README with the problem, what works, and a short example. Provide a requirements table linking each requirement to implementation/tests or design-only sections. Keep one authoritative architecture document and link to it; remove stale or contradictory planning statements from the submission path.

Provide pinned dependencies or a lockfile, a credential-free `.env.example`, tested installation/authentication steps, and documented demo identities. Add a diagnostic command that distinguishes CLI login, application credentials, BigQuery job permissions, Gemini model/key access, and configuration errors without printing secrets. A schema read alone is not proof that query-job execution or Python ADC works.

Run a clean-environment check. Offer deterministic synthetic tests without credentials, plus explicitly labelled live checks requiring the reviewer's credentials. Recorded output is useful supporting evidence, not a substitute for live capability. Exclude local databases, logs, credentials, and generated personal artifacts from the public repository.

Use a 5–7 minute demo:

1. Start as a manager; show effective brand scope and run both top-10 rankings.
2. Ask a follow-up; demonstrate preserved context and a forbidden request being blocked.
3. Investigate churn, showing definitions, comparison counts, and limits of causal claims.
4. Generate a quarterly report; explicitly save it and show its ID.
5. Preview deletion, cancel once, then confirm. Show ownership and exact deletion outcome.
6. Show a clearly labelled injected failure and its bounded recovery, then the sanitized trace and test summary.

Prepare to explain the SQL, the permission boundary, one failed approach, and a tradeoff. Describe actual ADK experience honestly and disclose AI assistance if the interview rules require it. Understanding the code matters more than the length of the documentation.

## 11. A realistic 12-hour execution budget

The allocations below are proposed remaining implementation work. Count time already spent on research and requirements separately and report total effort honestly; this is not a claim that our total work will fit into twelve hours.

| Hours | Deliverable and exit condition |
|---|---|
| 0–1 | Freeze metric defaults, fixture cases, package/config structure, and dependency versions; verify Gemini and Python BigQuery access. |
| 1–3.5 | Build the restricted SQL gateway and privacy/scope contracts alongside adversarial tests. Authorized dynamic query works; escape cases fail closed. |
| 3.5–5.5 | Add ADK/CLI conversation and the three analytical flows. Answer evidence and definitions are visible. |
| 5.5–6.5 | Implement report storage and deterministic confirmation; verify ownership, cancellation, replay, and hard delete. |
| 6.5–8 | Complete bounded retries, shared budgets, structured events, and fault tests; preserve usable CLI state on failure. |
| 8–9.5 | Run the focused evaluation and fix failures; record actual outcomes and representative transcripts. |
| 9.5–11 | Finalize HLD, technical explanations, sample trios, requirement mapping, and setup; verify a clean environment. |
| 11–12 | Rehearse demo, reconcile documentation, and optionally add small retrieval if all mandatory checks pass. |

If time is tighter, reduce supported SQL constructs, evaluation breadth, and optional retrieval/UI features while documenting boundaries. Do not remove permission enforcement, privacy, confirmation, mandatory failure handling, or the required production explanation to make room for optional features. If the minimum is incomplete, report that rather than describing a partial solution as finished.

## 12. Final acceptance checklist

- [ ] All three priority scenarios work, with one meaningful follow-up each and documented definitions.
- [ ] Dynamic BigQuery SQL works within a clearly described supported subset.
- [ ] Managers are brand-scoped; CEO analytics and private-report access are correctly separated.
- [ ] Prohibited customer values never appear in the tested model requests, outputs, report content, or telemetry.
- [ ] Destructive actions require a genuine user confirmation of the exact target set.
- [ ] Faults and empty data produce bounded, understandable outcomes without fabricated findings.
- [ ] Actual evaluation results, costs, and timings are presented with their sample-size limitations.
- [ ] HLD covers all eight requirements, retention, deployment boundaries, and concrete production services.
- [ ] Trio format and illustrative seeds exist; optional retrieval status is explicit.
- [ ] A reviewer can run it with their own credentials and inspect tests without credentials.
- [ ] No secrets or generated private artifacts are committed; docs match implemented behavior.
- [ ] We can defend every major decision and state what we would improve with another week.

The central differentiator is evidence: a correct business answer, a blocked unauthorized action, an exact confirmed deletion, and a reproducible explanation of how each happened.
