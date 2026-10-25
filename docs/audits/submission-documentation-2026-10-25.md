# Submission documentation and diagram audit

Date: 2026-10-25. Runtime inspected: `6105cd2920f1c9fc`.

Status: findings addressed in the [remediation record](submission-documentation-remediation-2026-10-25.md). The findings below preserve the original audit.

## Assessment

The design is defensible for the agreed scale and the assignment is broadly covered. Keep the small Python/ADK application, guarded BigQuery execution, private transactional report store, and explicit distinction between prototype and production. The main submission risk is inconsistent explanation: some prominent documents describe behavior that recent implementation changes deliberately removed. The production event and retrieval paths also need more concrete implementation detail.

This is a documentation review, not a new penetration test, deployment validation or live model evaluation. Findings below are not claims that proposed cloud components are deployed. P1 means correct before submission; P2 means a material clarification; P3 means editorial cleanup. These priorities describe submission readiness, not production incident severity.

## Checks performed

| Check | Result |
|---|---|
| Assignment and client clarifications | Reviewed against the four mandatory prototype requirements and all eight design requirements |
| Reviewer path | README, QUICKSTART, docs index, HLD, technical explanation, requirements, metrics, setup, demo, evaluation and latest audit evidence inspected |
| Mermaid consistency | All three blocks in `architecture.md` exactly match their corresponding `.mmd` sources after whitespace trimming |
| SVG inspection | All three SVG files parsed and were rendered locally with macOS Quick Look; architecture, request flow and deletion previews visually inspected |
| Editable diagram | draw.io XML parses; node/edge labels inspected; it is a coarser production view, not a pixel-identical Mermaid export |
| Local Markdown links | 101 local file targets checked across README, QUICKSTART and `docs/`; no missing targets found; anchor correctness and external link availability were not exhaustively checked |
| Golden examples | All three entries validate against the supplied JSON Schema and are explicitly illustrative, not approved client knowledge |
| Online research | Official Google, ADK, GitHub, C4 and upstream pgvector documentation consulted; sources linked beside the relevant findings |

Rendered previews are local audit artifacts under `.retail-agent/documentation-audit/`. GitHub's live Mermaid renderer and the draw.io editor were not exercised. The previously recorded 167 offline passes and live results were reviewed, not rerun for this documentation-only task. No cloud resources or paid model calls were created by this audit.

## Findings

### D01 — P1: Metric documentation contradicts current calculations

Locations: [metric definitions](../metrics.md#comparing-calendar-periods), line 29; [technical explanation](../technical-design.md#report-quality-boundary), lines 66, 84 and 100.

The documents still say comparisons require adjacent periods, calculate later minus earlier, use the earlier period as denominator, and leave empty revenue undefined. Current code instead respects the explicit primary/baseline roles, permits gaps, and derives zero revenue when zero units/orders/customers prove an empty sales population. Raw SQL evidence still contains NULL; missing revenue on nonempty sales remains unknown. See [metric catalog](../../src/retail_agent/quality.py) and [completeness validation](../../src/retail_agent/intent.py).

Impact: a reviewer can read a mathematically different definition from the one demonstrated by the CLI. This directly concerns the recently fixed reverse-comparison and year-over-year bugs.

Correction: define the baseline once; use `(primary - baseline) / baseline`, explain zero versus unknown, and link other documents to this definition. Remove both adjacent-period references from the technical explanation. Retain historical failure descriptions only in clearly dated audit records.

### D02 — P1: The delivered runtime has no accurate diagram of its own

Locations: [HLD request flow](../architecture.md#request-flow), [README testing description](../../README.md#development-and-checks), [setup warning](../setup.md#troubleshooting), [requirements evidence](../requirements.md).

The production diagram is correctly labelled as a proposal, so showing Vertex AI and Golden retrieval is not itself an error. However, it is the only end-to-end visual. It sends every analytical result back to the model and omits the explicit contract/completeness gate, while the implemented path constructs simple answers directly and invokes ADK narration only when requested. README still describes offline execution through the real ADK tool loop; setup still warns about the old structured-response tool. Those descriptions are stale after direct plan execution and native structured output.

Correction: add a compact **implemented prototype** diagram: CLI → typed planner → deterministic contract/auth validation → application executor → BigQuery → evidence/completeness → deterministic rendering, with optional tool-free narration and its bounded repair/fallback. Show SQLite and separate library/confirmation controls. Describe the actual use of ADK honestly: model integration and optional narrative runner/callbacks, not a model-driven query tool loop. Keep the production diagram separately labelled. Add the current bounded library sequence, cancel and nonmutating help routes to the technical explanation.

For the production sequence, represent multiple required queries and an optional narrative branch, then show validation before publication. An error returned by dry run must not appear to proceed unconditionally to execution.

### D03 — P1: Golden publication and terminal task failures lack a concrete mechanism

Locations: [component diagram](../architecture.md#components-and-trust-boundaries), line 19; [Golden lifecycle](../architecture.md#golden-knowledge-and-learning), line 85; [requirements resilience row](../requirements.md).

The diagram connects Cloud Storage directly to Cloud Tasks using an “approved publication event.” It does not identify the process that calls the task API, nor how a committed approved revision survives failure between storage publication and enqueueing. The text promises a failure queue/DLQ without specifying its implementation.

Cloud Storage event delivery can use Eventarc/Pub/Sub; creating a Cloud Task is a separate API action. Cloud Tasks can deliver duplicates, and exhausted tasks are deleted rather than providing the durable failed-job record implied by the current wording. See [Storage events](https://docs.cloud.google.com/run/docs/triggering/storage-triggers), [task creation](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks), [duplicate execution](https://docs.cloud.google.com/tasks/docs/common-pitfalls) and [retry exhaustion](https://docs.cloud.google.com/tasks/docs/configuring-queues).

Recommended design: the existing publication service records approved revision plus an outbox entry, and an authenticated dispatcher enqueues an idempotent indexing task. Keep immutable object generation and Trio revision in the task. Persist job state/attempts/failure reason in PostgreSQL and provide an explicit redrive action. If choosing storage-triggered publication instead, draw the Eventarc receiver and its approval check. Neither choice requires cron-based retail analysis.

Specify what constitutes successful acknowledgement, how duplicates are detected, and where a user sees a failed report job. Keep an async result as a draft unless saving was explicitly authorized. HTTP task handlers have a maximum 30-minute deadline; the requested 1–2 minute reports fit that envelope, but nested retries must not reset application budgets. [HTTP target limits](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks)

### D04 — P2: The strongest evaluation evidence is not portable with the repository

Locations: [latest evaluation](../evaluation.md), [targeted audit](targeted-fixes-v4-2026-10-25.md), `.gitignore`.

The latest audit provides exact prompts and outcomes, but its runnable harness, independent SQL oracle, acceptance checks and raw outputs live under ignored `.retail-agent/` directories. A fresh clone cannot reproduce the headline ten-case run using a documented command. The committed live suite covers other scenarios; it is not the same evaluation.

Correction: retain the ignored databases and private diagnostics, but move the secret-free case manifest, harness, numerical checker and a sanitized result summary into versioned evaluation assets. Document one opt-in command, identity/session dependencies, model settings and expected variable spend. Include a compact real transcript for the current runtime. Preserve failures and distinguish replay success from first-attempt holdout performance. Do not publish full runtime databases or credentials to make the evidence portable.

### D05 — P2: Diagnostic logs are described too broadly as content-free

Locations: [HLD observability](../architecture.md#observability-and-quality), line 129; [technical implementation map](../technical-design.md#implementation-map), line 21; [traceability](../technical-design.md#traceability).

The mutation audit is content-free, but diagnostic events include serialized accepted/proposed intents, with dates, brands, product/customer filters, and now sanitized validation reasons. `agent.py` emits `plan_accepted` with the complete typed intent; `planning.py` emits `plan_proposed`. This is minimized structured context, not only IDs/counters and not “no parameter values.” No raw-contact-data leak was established by this audit.

Correction: distinguish mutation audit, diagnostic context and persisted analytical answers. List allowed diagnostic fields and access/retention rules. Either remove unnecessary filter values or document their intentional presence. Retain the prohibition on raw prompts, provider exception bodies and hidden reasoning. The technical traceability section already partly reflects the new behavior; align the HLD and module table with it.

### D06 — P2: Retrieval has a good policy but an incomplete execution design

Location: [Golden Knowledge](../architecture.md#golden-knowledge-and-learning), especially line 87.

Using PostgreSQL with text search and pgvector is reasonable at this scale; Google explicitly supports pgvector in Cloud SQL. [Cloud SQL extensions](https://docs.cloud.google.com/sql/docs/postgres/extensions)

However, the HLD does not identify the embedding generation path/model-version contract, vector dimensions, or how filtered retrieval is implemented. “Filter BEFORE retrieving” is a correct disclosure rule, but should not promise a physical execution order for approximate vector indexes: upstream pgvector documents filtering after approximate index scans, which can underfill results. [pgvector filtering](https://github.com/pgvector/pgvector#iterative-index-scans)

Correction: start with exact similarity over the approved, authorized SQL subset for the small Golden corpus; return only authorized content. Describe embedding provider/version/dimensions, reindexing and hybrid ranking. If ANN becomes necessary, evaluate recall under filters and use appropriate partitions/indexing/iterative scans. Never retrieve globally and leave authorization to the model. Avoid adding a second vector database without measured need.

### D07 — P2: The deletion diagram mixes rejected attempts with persisted state

Location: [deletion state diagram](../architecture.md#reports-and-deletion) and [store confirmation](../../src/retail_agent/reports.py), lines 170–210.

The diagram moves a preview into `Rejected` for a wrong owner/session/token. In the implementation, an invalid confirmation rolls back and does not consume another valid pending preview. A wrong token therefore describes an attempt outcome, not necessarily a terminal change in the preview's state. A successful confirmation also invalidates pending confirmations for that owner, which is not visible in the diagram.

Correction: either label this explicitly as an attempted-operation flow, or make it a faithful persisted-state diagram: invalid confirmation returns an error while the valid preview remains pending; cancellation/expiry/success terminate it. Keep exact-set recheck and replay protection prominent. If production intentionally differs, document that choice instead of presenting the diagram as current behavior.

### D08 — P2: The production visual mixes process, component and storage boundaries

Locations: all three diagram formats in [diagrams](../diagrams/architecture.mmd).

The images render and their text is legible when enlarged. At a normal README width, the architecture is dense and labels become small. ADK is an in-process library alongside deployed services; the two PostgreSQL boxes can look like two databases despite the prose choosing one. The worker only connects to the knowledge index even though it also supposedly runs reports. It lacks the model/query-gateway/state paths needed for that responsibility. The separate gateway identity described in prose has no visible deployment/trust boundary.

Correction: group internal API/planner/renderer components, group PostgreSQL schemas within one Cloud SQL boundary, and separate the online request path from publishing/indexing. Add worker dependencies and trusted identity propagation. Give every inter-service edge a meaningful protocol/action label and include a legend for proposed components. Shorten labels and link to the accompanying responsibility table. This follows the separation of architectural levels and relationship clarity recommended by the [C4 container guidance](https://c4model.com/diagrams/container) and [review checklist](https://c4model.com/diagrams/checklist).

Keep the server-owned mapping to restricted BigQuery execution identities: it is a strong part of the proposal. Make the relationship to **authorized views** explicit and state that source and view datasets share the required location. A shared service account does not automatically inherit the chat user's permissions. [Authorized views](https://docs.cloud.google.com/bigquery/docs/authorized-views), [ADK tool identity](https://adk.dev/safety/)

### D09 — P3: The reviewer path is longer and more historical than necessary

Locations: [docs index](../README.md), [evaluation](../evaluation.md), [technical explanation](../technical-design.md).

The index's latest-review link points to an older audit. Evaluation is approximately 3,467 words and includes several generations of results, an old section titled “Latest verification,” and obsolete experimental warnings. Technical explanation has another 3,241 words, repeats several boundaries and contains “Example of one resulting request: Example:”. Historical failures are valuable evidence, but the reader should not have to reconstruct the current architecture from the chronology.

Correction: make the first page a current status summary with one source version, supported scope, test evidence, limitations and commands. Move detailed evolution to dated audits and link it. Keep a short reviewer path: quick start → prototype/HLD → requirement mapping → current evaluation → demo. Explain the current ADK role once. Use one canonical Mermaid source per diagram with an export/synchronization command; the present three copies are consistent, but there is no checked-in regeneration procedure. GitHub supports fenced Mermaid directly, so a new diagram platform is unnecessary. [GitHub diagrams](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams)

## What should stay

- Explicit prototype-versus-production labels and honest first-project ADK experience.
- Server-owned identity, brand-first analytics, source-field minimization, and owner-only report access even for the CEO.
- Deterministic confirmation with exact report set, expiry, transaction and replay tests.
- Precise inactivity-proxy definition, population counts, hypothesis caveats and evidence-backed numerical rendering.
- No runtime Golden retrieval claim; three clearly illustrative examples and a reviewed publication proposal.
- Automated persona publication gate distinct from human approval of Golden examples.
- Configurable per-question variable budget separated from actual invoices and fixed hosting cost.
- The small deployment choice: no Kubernetes, extra agent team or separate vector service is justified by this workload.

## Recommended correction order

1. Align metric/runtime/logging descriptions with current code (D01, D02, D05).
2. Add the implemented-prototype visual and make the production publication/worker paths executable on paper (D02, D03, D08).
3. Clarify retrieval and deletion-state semantics (D06, D07).
4. Package portable evaluation evidence and shorten the reviewer path (D04, D09).
5. Recheck Markdown/source/export consistency and inspect GitHub rendering before submission. Cloud deployment or another paid 20-question run is not required to correct these documentation findings.

No runtime source or existing submission document was rewritten in this audit. This report records the concrete corrections to make, rather than silently changing architectural decisions during review.
