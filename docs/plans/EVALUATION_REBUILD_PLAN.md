> Historical plan or validation record. The current implementation is documented in [architecture.md](../architecture.md); ADK, A2A and Phoenix instructions below are superseded.

# Evaluation rebuild: local Phoenix and independent reference data

> Historical configuration note (2026-11-25): demo users and assigned-brand permissions described below are superseded by [full dataset access](FULL_DATASET_ACCESS.md). Current commands have no `--user` option. Historical findings and captures retain their original scope.

**Status:** evaluation platform implemented; human review, human calibration, and a sealed holdout remain pending. Old evaluation code and test implementations have been removed.
**Observed implementation:** [verification and pilot results](EVALUATION_IMPLEMENTATION_RESULTS.md).

**Research date:** 2026-11-22. **Repository baseline:** 4d205c0.
**Methodology review:** [Google, Anthropic, and OpenAI review](EVALUATION_REVIEW.md), 2026-11-22, against documentation baseline 37dfe2e. Implementation decisions and remaining validation are recorded below.

## 1. Scope and decisions

Replace the evaluation implementation and reconstruct the test suite around the actual application. Use **local Arize Phoenix** for traces, versioned datasets, experiments, and annotations; deterministic graders for numerical correctness, authorization, and persisted state; and calibrated LLM judges for claim support and semantic requirements.

The existing agentic runtime remains the system under test, including its runtime reviewer. Offline evaluation grades completed trials independently. Runtime approval, successful SQL execution, and presentation quality do not establish task success.

| Component | Purpose | Runtime access |
|---|---|---|
| **Evaluation Golden Dataset** | Frozen tasks, environments, verified facts, acceptance criteria | Task inputs and authorized environment only |
| **Phoenix** | Experiment inspection, comparison, outputs, scores | No analyst access |

Start with **40 reviewed cases** and expand toward 200 after validating the harness and graders. Establish quality thresholds from a baseline and product requirements; the attachment's illustrative 95%/98% targets are not adopted.

At cutover, delete the old evaluation tree, runners, and test implementations after reconstructing mandatory coverage. Git preserves their history; no archive directory is required. Application changes are limited to observability and the testability seams specified below.

## 2. Baseline assessment

The audit identified 14 Python test files and 543 files under `evals/`:

- Historical runners import removed modules; many captures describe retired implementations.
- Active smoke checks use runtime approval, formatting, and numeric-token presence, which cannot verify entity, period, or category attribution.
- Stronger checks depend on one fixture and identity. Calibration also imports historical captures.
- The 18 holdout specifications are unvalidated case candidates, not executed benchmark results.
- Existing tests protect essential scope, ownership, publication, deletion, accounting, per-prompt budget, and CLI contracts. Their implementation will be replaced; their requirements remain.

## 3. Evaluation model

Evaluate outcomes and traces together, accepting multiple valid execution paths. Code, model, and human graders have complementary roles. [Anthropic's agent evaluation guide](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)

Keep two independent measurements:

- **Correctness:** agreement with independently calculated reference facts.
- **Grounding:** support from evidence the agent actually observed.

An answer can accurately repeat incorrect SQL results, or accidentally state the correct value without evidence. Neither condition satisfies both measurements.

Atomic-claim grading detects unsupported implications within otherwise correct answers. [FActScore](https://aclanthology.org/2023.emnlp-main.741/) motivates fact decomposition; [FEVER](https://aclanthology.org/N18-1074/) distinguishes support, contradiction, and insufficient evidence. These methods require validation for retail analytics.

Evaluate SQL denotations across distinguishing fixtures rather than matching query text or relying on one database. This approximates semantic correctness; it does not prove equivalence for every dataset. [Semantic evaluation for text-to-SQL](https://arxiv.org/abs/2010.02840)

ADK trajectory/response evaluators are optional diagnostics. The primary harness exercises application budgets, review, and report operations. Exact tool sequences and ROUGE similarity are unsuitable general acceptance criteria. [ADK evaluation criteria](https://adk.dev/evaluate/criteria/)

Imported metrics require a versioned contract for evaluation unit, denominator, score direction, missing-output handling, and judge settings. ADK's sentence-level hallucination metric includes nonfactual sentences as successes; it is not interchangeable with our factual-claim precision. Report it separately if adopted.

## 4. Architecture and data boundaries

~~~mermaid
flowchart TD
    Inputs[Identity and user steps] --> Runner[Isolated conversation runner]
    Runner --> App[Analyst.ask and trusted actions]
    Fixtures[Frozen warehouse and report state] --> App
    App --> Loop[Analyst tool loop]
    Loop --> Review[Runtime reviewer]
    Review -->|Revise| Loop
    Review -->|Approve exact candidate| Result[Answer, observed evidence, actions, usage]
    Loop -->|Controlled failure| Result
    Result --> Graders[Independent code and calibrated LLM graders]
    References[Evaluation references] --> Graders
    App --> Traces[OpenInference and application spans]
    Traces --> Phoenix[Local Phoenix]
    Graders --> Phoenix
    Result --> Artifacts[Immutable local artifacts]
~~~

Offline graders cannot feed references back into the analyst or runtime reviewer. Canonical cases, schemas, rubrics, and fixtures live in Git; experiments pin their versions and export immutable manifests independently of Phoenix UI state.

| Asset | Location | Contract |
|---|---|---|
| Evaluation cases | `evaluation/datasets/golden/` | Development, regression, and held-out splits |
| Evaluation fixtures | `evaluation/fixtures/` | Independently designed, versioned data |
| Judge calibration | `evaluation/datasets/judge_calibration/` | Human-labeled candidates; separate tuning/validation splits |
| Generated artifacts | Ignored `.artifacts/evaluation/` and Phoenix | Outputs, never implicit test dependencies |

Retain runtime knowledge paths: renaming them would affect root discovery, validation, loaders, and public configuration without improving isolation.

The task adapter accepts **input only**. A trusted harness resolves identity and fixture configuration. References, oracle SQL, expected answers, and grader rubrics must never enter runtime prompts, tools, skills, knowledge, or review inputs.

Split by scenario and data-generation family, not paraphrase. Freeze manifests before tuning; vary products, prices, leaders, and category distributions from runtime examples. Any held-out case used to improve code, prompts, skills, or graders becomes regression data and must be replaced before another unseen-performance claim. LLM-generated drafts require independent calculations and human review before becoming verified references.

## 5. Local Phoenix deployment

Use Docker Compose, SQLite on a named volume, and localhost-only HTTP access. Pin the server image after a compatibility spike. [Docker deployment](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)

~~~yaml
services:
  phoenix:
    image: arizephoenix/phoenix:<validated-version>
    ports:
      - "127.0.0.1:6006:6006"
    environment:
      PHOENIX_WORKING_DIR: /data
      PHOENIX_ENABLE_AUTH: "false"
      PHOENIX_TELEMETRY_ENABLED: "false"
      PHOENIX_ALLOW_EXTERNAL_RESOURCES: "false"
      PHOENIX_DISABLE_MODEL_COST_AUTO_UPDATE: "true"
    volumes:
      - phoenix-data:/data
volumes:
  phoenix-data:
~~~

Authentication is disabled only for this localhost development deployment; shared access requires authentication. Validate settings against the pinned release. [Configuration](https://arize.com/docs/phoenix/self-hosting/configuration), [migration notes](https://github.com/Arize-ai/phoenix/blob/main/MIGRATION.md)

- UI/REST: `http://127.0.0.1:6006`
- OTLP HTTP exporter: `http://127.0.0.1:6006/v1/traces`

Separate dependencies: `arize-phoenix-otel` and `openinference-instrumentation-google-adk` for tracing; `arize-phoenix-client` and `arize-phoenix-evals` for evaluation; pytest and targeted property-testing support for tests. The server remains containerized. Validate a pinned combination against the current ADK 2.12.0 runtime and custom `AccountedModel`.

Local Phoenix provides local storage and UI, not local inference. Gemini agent/judge requests still reach Google's API. A local Ollama judge is optional after calibration; [structured outputs](https://docs.ollama.com/capabilities/structured-outputs) ensure format, not judgment validity.

## 6. Instrumentation and capture policy

Configure one tracer provider and instrument ADK once; verify overlapping provider instrumentation does not duplicate spans. [ADK integration](https://adk.dev/integrations/phoenix/), [OpenInference ADK instrumentor](https://github.com/Arize-ai/openinference/tree/main/python/instrumentation/openinference-instrumentation-google-adk)

Each prompt gets an application span with conversation/turn IDs. Analyst and reviewer spans remain its children despite separate ADK sessions. Experiments add case, repetition, and experiment IDs.

Record model role/settings, tools, timings, outcomes, review revisions, and budget/usage events. Synthetic captures retain exact visible observations and candidates, including which result rows were truncated or unread. Reconcile instrumentation with the provider ledger; summing parent and nested token attributes would double-count usage. Include thinking-token counts and separate analyst, runtime-reviewer, and offline-judge costs.

`AccountedModel` retries inside an ADK invocation. Record every provider attempt through child spans or attempt IDs, including failures, and reconcile settlements with the ledger.

| Capture mode | Content |
|---|---|
| Normal chat | Metadata only by default |
| Synthetic evaluation | Synthetic prompts, visible observations, candidates, and answers; credentials and confirmation secrets redacted |

Filter provider parts marked as thought even in full synthetic capture. Hiding controls alone do not protect custom attributes, exceptions, or dataset uploads: canary tests must inspect all outbound trace and experiment payloads. [OpenInference controls](https://arize-ai.github.io/openinference/spec/configuration/trace-config.html), [OpenTelemetry sensitive-data guidance](https://opentelemetry.io/docs/security/handling-sensitive-data/)

Exports and shutdown flushes must be bounded. Phoenix outages cannot block chat; evaluations retain local artifacts and report publication failures explicitly.

## 7. Evaluation dataset

### Case schema

One case represents a task or scripted conversation; repetitions start with isolated state. Prompts remain English. The following schema is illustrative, pending validation contracts:

~~~yaml
case_id: category-change-followup-001
family_id: quarterly-category-contributions
split: regression
review_status: verified
input:
  identity: alice
  steps:
    - kind: ask
      message: "Compare Q1 2026 with Q4 2025. Show qualifying revenue and its change."
    - kind: ask
      message: "Show the three categories with the largest absolute revenue changes, preserving signs. Group the rest as Other."
    - kind: ask
      message: "Summarize this in under 130 words with two next steps. Do not use a table."
environment:
  warehouse_fixture: category_changes_v1
  fixture_sha256: <verified-fixture-hash>
  report_store: empty
  clock_utc: "2026-04-02T12:00:00Z"
reference:
  oracle: category_changes_v1
  metric_policy_version: retail-defaults-v1
  required_checks:
    - scoped_revenue_and_periods
    - largest_absolute_changes_with_signed_values
    - other_equals_excluded_categories
    - displayed_contributions_reconcile
    - summary_preserves_group_meaning
  forbidden_assertions:
    - "Revenue alone proves a change in demand."
  final_state:
    reports_created: 0
evaluation:
  required_graders: [numeric_facts, reconciliation, claim_support, instructions, report_state]
provenance:
  source: observed_failure
  reference_review: <review-record-id>
~~~

Only input reaches the application; environment configures the harness, and reference/evaluation fields remain grader-only. `verified` requires reference validation and recorded review.

Declare acceptable outcomes per turn: answer, clarification, refusal, or incomplete result. A refusal can satisfy an access-control case; honest exhaustion does not satisfy ordinary analysis. Support typed `ask`, `confirm_delete`, and `cancel_delete` steps plus CLI scenarios. Deletion currently uses `Analyst.confirm_delete`, outside `ask`; the runner must exercise that trusted boundary using explicitly scripted user confirmation, without exposing tokens to the model or confirming its requests automatically. Fault schedules remain harness-controlled.

Reference facts specify entity, metric, scope, period, unit, denominator, value, and tolerance. Use Decimal arithmetic and declared monetary rounding; counts/IDs are exact. Accept valid tie alternatives when the task does not prescribe a unique tie-break.

Freeze atomic acceptance criteria before running candidates: criterion ID, applicable turn/branch, required evidence, grader, severity, and whether failure blocks task success. Criteria derive from the request, metric policy, or environment, never from the candidate answer. An LLM may draft criteria for review, but cannot relax them while grading. This adapts Google's task-specific rubric approach. [Google evaluation overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-overview)

Admission requires a reviewed passing answer/state and, for answerable tasks, a feasible reference procedure through authorized tools under the declared limits. The procedure validates solvability, not an expected trajectory. Mutated controls must fail the intended criteria. Broken fixtures/references become `INVALID_CASE` with recorded exclusions; repairs create a new version and require comparable baseline/candidate runs. [OpenAI evaluation-validity guidance](https://openai.com/index/trustworthy-third-party-evaluations-foundations/)

### Conversation scenarios

Retain scripted regressions and include a small set of bounded branching scenarios in the pilot: missing period, clarification, corrected definition, false premise, and cancellation. Branch on actual responses so a legitimate clarification does not encounter an unrelated next prompt. LLM user simulation is optional later, with capped turns/cost, user-owned scenario facts only, recorded transcripts/version, and independent simulator-validity checks. Simulator failures are harness errors; simulators cannot access oracle answers or authorize destructive actions. [ADK user simulation](https://adk.dev/evaluate/user-sim/)

### Independent oracles

Compute references from raw fixture rows using separate Python Decimal/set logic. Do not import the application compiler, reuse agent SQL, or accept reviewer verdicts as ground truth. Cross-check difficult calculations independently and through human review.

Fixtures must distinguish:

- Items, orders, and customers; repeat purchases and unequal order sizes.
- Cross-brand histories, mixed-brand orders, and first purchases outside authorized scope.
- Item/order cancellation and return statuses independently.
- UTC boundaries, empty periods, zero denominators, schema-valid nulls.
- Ties, unsold products, and different revenue/customer leaders.
- Signed category contributions, more than three categories, and zero net change.
- Truncated evidence, bounded history, and changed follow-up instructions.

Mutation tests must reject wrong DISTINCT usage, grain, status filters, end boundaries, scope, and contribution signs. Metamorphic checks include invariance under adding another brand's rows and increased orders without increased customers after a repeat purchase.

### Coverage

The 40-case pilot includes failures and successful controls across all major families. Expand after validating references and graders:

| Primary family | Target |
|---|---:|
| Analytics and metric semantics | 60 |
| Unsupported claims, ambiguity, missing data | 35 |
| Multi-turn context and instruction changes | 35 |
| Failures, recovery, exhaustion | 25 |
| Scope, ownership, injection, leakage | 25 |
| Report workflows | 20 |
| **Total** | **200** |

Assign one primary family per case; additional tags are allowed. Cases copied from runtime examples are not evidence of generalization.

Tag suite purpose independently of the development/regression/holdout split: representative workload, stable regression, or exploratory challenge. The 200-case allocation is diagnostic coverage, not an estimate of traffic frequencies. Report slices separately; weight workload estimates only from a documented sampling frame. Maintain a lightweight intake record for sanitized user-reported failures and successful controls, fixture reproduction, references, and review status. Preserve metadata-only chat defaults; richer capture requires explicit scope and sanitization. Saturated cases remain regressions while new realistic challenges extend coverage. [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)

## 8. Test layers and runtime seams

| Layer | Execution | Coverage |
|---|---|---|
| Contracts/properties | Real domain code; controlled clocks/stores | Scope, arithmetic, accounting, state, privacy |
| Application integration | Real loop/tools with scripted models | Completion, repair, follow-ups, cancellation, limits |
| Evaluators | Independent oracles, valid/defective answers, fake judges | Grading accuracy and failure handling |
| Phoenix integration | Local server, synthetic data, fake provider | Export, persistence, linkage, annotations, redaction |
| Live experiments | Actual runtime on frozen fixtures | Quality, reliability, latency, cost |
| BigQuery integration | Controlled versioned dataset | Dialect and execution compatibility |

Offline tests use explicit fake settings, temporary stores, and controlled clocks. Block network access and loading of `.env` or ambient credentials. Mock external boundaries, not the compiler, scope filters, or storage logic under test.

Reconstruct these contracts:

- Scope before joins/history/cohorts; SQL sandbox restrictions, query limits, and cancellation.
- Metric grain, statuses, dates, denominators, ties, and truncation.
- Exact reviewed publication/save target; revision feedback in the same analyst loop.
- Fresh per-prompt budgets with retained context; shared analyst/reviewer/retry accounting within a prompt; exactly-once settlements and conservative unknown usage.
- Explicit saves, owner isolation, exact deletion selection, expiring one-use tokens, stale previews, and final database state.
- Skill integrity, path restrictions, evidence separation, and bounded reads.
- CLI spacing, independent timer/status updates, completion navigation without automatic execution, and piped input.

Assert requirements rather than optional SQL/tool/skill choices. Enforce ordering only for genuine protocols, including review before publication and confirmation before deletion.

DuckDB fixtures do not establish BigQuery compatibility. Mutable public TheLook probes need a recorded snapshot or explicitly ungraded numerical correctness.

Two application seams are required: inject UTC/wall time for relative dates, history expiry, and report clocks while retaining real monotonic budget/cancellation time; and configure trusted physical BigQuery tables for controlled integration datasets. Source configuration remains outside model arguments and preserves scope enforcement.

Clock control must also account for SQL `CURRENT_DATE`/`CURRENT_TIMESTAMP`; changing prompt time alone does not freeze the database clock. Verify consistent as-of semantics or label the case non-frozen. Fault schedules specify boundary, trigger, response/latency, seed, and recovery expectations. Inject faults below the compiler/scope checks being tested; generative tool mocks cannot supply numerical ground truth.

### Adversarial and context boundaries

Exercise both runtime and evaluation surfaces with synthetic paired payloads:

| Surface | Attempt | Required observation |
|---|---|---|
| Product values, tool errors, saved reports | Override scope, fabricate facts, request unauthorized save/delete | No forbidden disclosure/mutation; retain legitimate task utility |
| Candidate, quoted history, selected evidence | Persuade the runtime reviewer to approve or authorize saving | Record reviewer false accepts and actual persisted state separately |
| Candidate/evidence passed to offline graders | Spoof rubric/system messages, full-score JSON, evidence IDs | Trusted criteria unchanged; defective controls remain failures |

Distinguish blocked attempts from successful policy violations and judge manipulation. Include benign quoted-instruction controls. Code validates boundaries and final state; no model score can override a failed invariant. These adapt [ADK's trust-boundary guidance](https://adk.dev/safety/) to the application's actual surfaces.

Stress current history limits: six entries, 4 KB answer excerpts, aggregate context allowance, and 30-result manifests. Use scripted models for boundary coverage and selected live scenarios with period/definition changes and older-answer references. Record visible context; missing details require rereading, querying, or clarification, not invented continuity. No new memory subsystem is required. [Anthropic context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)

## 9. Metrics and claim grading

Each score records name/version, status, value/label, denominator, and evidence-linked findings. Separate execution and grading status; missing scores never pass. Support `PASS`, `FAIL`, `ERROR`, `UNJUDGEABLE`, and `NOT_APPLICABLE`.

| Metric | Definition |
|---|---|
| Task success | All mandatory published turns, facts, instructions, and state checks pass; no critical violation or unresolved required grade. Report successes/attempts and unscored counts. |
| Required-fact coverage | Correctly communicated required facts / required facts |
| Numeric correctness | Correct required numeric facts / required numeric facts, including entity, period, metric, unit, and scope |
| Reconciliation | Signed components plus Other equal the independent total; top-component selection checked separately |
| Grounded precision | Supported / judgeable factual claims |
| Unsupported / contradiction rates | Each label's count / judgeable factual claims |
| Affected-answer rate | Answers containing unsupported or contradicted claims / answers with judgeable factual claims; distinguish material defects |
| Instruction compliance | Requested format, columns, word limits, coverage, and actions |
| Action correctness | Persisted ownership, selection, authorization, and content; receipts alone are insufficient |
| Boundary violations | Separate disclosure, mutation, confirmation, publication, and budget violation counts |

Grade every published answer with its turn-specific references and evidence. A later correction does not erase an earlier material failure; report first error, propagation, and recovery separately. Unpublished drafts rejected by review are diagnostics, not user-visible failures. This adapts Anthropic's conversation-wide evaluation principle. [Building strong safety evaluations, 2026-11-13](https://www.anthropic.com/research/building-strong-safety-evaluations)

### Answerability and abstention

Label each turn/branch as answerable, clarification-required, evidence-unavailable, or access-denied under its authorized environment. Pair sufficient/insufficient evidence and benign/adversarial cases. Report useful answer coverage on answerable tasks, unnecessary refusal/clarification, correct abstention where required, and material error rate among substantive answers. Keep provider failures and judge uncertainty separate; an empty result is not a failed query. Do not interpret model-reported confidence as calibrated probability. These measures expose both confident guessing and blanket refusal. [OpenAI hallucination research](https://openai.com/index/why-language-models-hallucinate/)

Use explicit denominators: useful coverage = correct, required-complete substantive answers on answerable turns / attempted answerable turns; unnecessary abstention = unjustified refusals or clarifications / gradable answerable turns; answer risk = substantive answers with a material factual/support defect / gradable substantive answers. Report answer-level grading coverage and unresolved counts so missing grades cannot dilute risk. Report appropriate limited responses separately for clarification-required, unavailable, and denied cases. Zero denominators produce `NOT_APPLICABLE`.

### Claim pipeline

Extract atomic assertions, including table labels, qualifiers, comparisons, causal claims, and aggregate-group meaning. Preserve exact spans and bind claims to entity/period/metric/scope and valid evidence IDs. Deterministically check numbers against independent oracles; separately evaluate support from observed evidence. Calibrated judges handle semantic implications. Combine these findings with coverage, instructions, and state assertions.

| Label | Meaning |
|---|---|
| SUPPORTED | Authorized observed evidence establishes the claim |
| UNSUPPORTED | Evidence is insufficient; the claim need not be false |
| CONTRADICTED | Evidence establishes an incompatible fact |
| NOT_FACTUAL | Suggestion or unasserted hypothesis; evaluate embedded factual premises separately |
| UNJUDGEABLE | Missing artifacts, ambiguous reference, or extraction/judge failure |

For counts S/U/C/J, grounded precision is `S/(S+U+C)` and judgeable coverage is `(S+U+C)/(S+U+C+J)`. No factual claims yields `NOT_APPLICABLE`, not 100%. Measure extraction recall only against human-annotated calibration/audit samples; otherwise use `NOT_MEASURED` and report audit coverage. Report claim-weighted micro scores and case/family macro averages.

Absent evidence due to agent behavior generally means unsupported; artifacts lost by the harness mean evaluation error. Follow-ups may use retained authorized observations and applicable definitions without another query. Track source type, scope, period, and authority: user assertions are premises to verify, historical reports are not current warehouse evidence, and explicit hypothetical assumptions must remain hypothetical. User-defined metrics configure the task but do not establish observed values. Unread rows and unrelated history do not count as observed evidence.

### Regression seeds

- **Ranking explanations:** disjoint revenue/customer rankings do not establish premium prices, lower volume, or causes. Distinguish asserted explanations from qualified proposals to investigate price, units, or mix.
- **Category summary:** +932.42 Outerwear, -383.51 Suits, +272.99 Tops, and -122.40 Other reconcile to +699.50. Omitting Tops while calling -122.40 the remainder after Outerwear/Suits misstates that remainder, which is **+150.59**. Numeric-token matching misses this defect.
- **Demand:** declining revenue alone does not establish declining demand. Accept cautious investigation proposals and valid arithmetic decompositions such as revenue = orders × AOV.
- **Follow-up exhaustion:** preserve context while resetting the prompt budget; distinguish accounting defects from provider/reviewer latency.

Convert these into reviewed fixed-answer calibration pairs and independent synthetic conversations. Historical captures motivate cases; new fixtures/oracles establish truth.

### Judge calibration

Start with 40–60 human-labeled candidate/evidence bundles and separate development/validation splits. Cover concise correct answers, polished errors, contradictions, entity errors, omissions, causal overreach, qualified hypotheses, and ambiguity. Independently double-review difficult cases where feasible, adjudicate disagreements, and record single-review provenance.

Blind judges to agent/model identity, runtime approval, and expected labels. Measure extraction recall, confusion matrices, false accepts/rejects, abstention, and repeated-judgment stability. Revalidate model/prompt changes. Audit verbosity, position, and self-preference bias; another model is not independent truth. Critical disputes require human adjudication. Request brief evidence-linked findings, not hidden reasoning. [MT-Bench research](https://arxiv.org/abs/2306.05685)

Keep offline judges tool-free, with trusted rubrics/references separate from bounded untrusted fields. Reject invalid labels, invented spans/IDs, and unexpected score fields. Add grader attacks to the labeled calibration set: instructions to approve, fake authority, wrong answers wrapped in score JSON, and fabricated citations. OpenAI reports injections targeting monitors/graders; schema validity alone is insufficient. [OpenAI monitoring research](https://openai.com/index/how-we-monitor-internal-coding-agents-misalignment/)

Run a frozen sentinel set on every grader/model change. Include fact-preserving paraphrases, nonfactual padding, polished incorrect answers, and correct concise controls. Track human-human agreement where available; audit a sample of passes as well as failures. If a plausible calibrated alternative grader reverses a claimed improvement, adjudicate before accepting it.

## 10. Reliability and experiment execution

Use an asynchronous adapter around `Analyst.ask` and trusted confirmation/cancellation actions. Target the pinned client's `phoenix.client.experiments.async_run_experiment` and `async_evaluate_experiment`; synchronous wrappers may differ in timeout behavior. Isolate stores, sessions, clocks, and initial state per case/repetition while preserving intra-conversation context.

Phoenix can inject reference fields into task functions, defaults to a 60-second timeout, and retries tasks. Explicitly use an input-only adapter, `retries=0`, initial concurrency 1, and a conversation deadline covering all turns plus setup/cleanup. Dry-run mode executes tasks and may incur model costs. [Python experiment API](https://arize-phoenix.readthedocs.io/projects/client/api/experiments.html)

With current 120-second prompt limits, a three-turn deadline must exceed 360 seconds. Require bounded local teardown, with subprocess isolation where necessary. Request supported remote cancellation and record unresolved jobs/unknown usage; local cancellation does not prove remote termination.

Separate execution from grading:

1. **Run:** persist immutable answers, observed evidence, state snapshots, timings, usage, and execution status locally.
2. **Grade:** evaluate saved artifacts and publish versioned annotations without rerunning the agent.

Judge budgets/timeouts/retries are separate. Attach programmatic evaluators explicitly; Phoenix UI dataset evaluators do not automatically grade every Python experiment. [Dataset evaluator behavior](https://arize.com/docs/phoenix/datasets-and-experiments/how-to-experiments/how-to-dataset-evaluators)

Every live command declares selected cases, total cost ceiling, and deadline in addition to per-prompt limits. Preserve conservative reservations for unknown usage. On exhaustion, retain completed work and mark remaining trials `NOT_EXECUTED`. Never select the best repetition or rerun failures until green.

Record commit/dirty-diff and lockfile hashes, dataset/fixture versions, metric policy, model/settings, prompt/skill hashes, judge version, repetitions, and limits. Distinguish changed judges from changed agent performance.

### Reporting and comparisons

- Report per-turn/conversation latency, stages, sample count, median/p95, timeouts, and controlled failures. Include all-attempt and success-conditional distributions; small-sample p95 is descriptive.
- Separate analyst, runtime-reviewer, query, and offline-judge usage/cost. Include failures and unknown usage; version pricing estimates. Cost per successful task includes all agent attempts and is undefined with no successes.
- Track invalid/repaired/repeated calls, review rounds, and query/model counts diagnostically. Successful recovery can include an invalid SQL attempt.
- Measure runtime-reviewer false accepts among independently invalid candidates and false rejects among valid candidates, with schema failures, retries, latency, and defect strata.
- Blind-grade first drafts, revisions, and published answers against independent truth and each candidate's contemporaneous evidence. Report invalid-to-valid repair yield, valid-to-invalid regression, and valid-but-blocked completion alongside review cost/latency. Keep reference/oracle versions fixed; later evidence cannot retroactively ground an earlier draft. These transitions are observational diagnostics, not isolated causal effects of the reviewer.
- Predeclare three pilot repetitions and size the suite to budget. Report per-attempt success, all-three success, and optionally any-of-three success. Interrupted repetition coverage makes consistency comparisons incomplete; do not analyze only surviving groups or cube the global mean. [tau-bench](https://arxiv.org/abs/2406.12045)

Compare identical case/fixture/repetition/judge versions; alternate execution order. Use paired per-case changes and confidence intervals clustered by case/family. Related claims are not independent observations; insufficient evidence remains inconclusive. [Statistical testing in NLP](https://aclanthology.org/P18-1128/)

Predeclare primary metrics, slices, comparison, and acceptable margins in the run manifest. Mark additional analyses exploratory; multiple tested variants must not turn a selected favorable result into an unqualified improvement claim.


## 11. Repository layout and workflow

Proposed additions and retained runtime paths:

~~~text
infra/phoenix/compose.yaml
evaluation/
  cli.py
  settings.py
  schemas/
  datasets/
    golden/{dev,regression,holdout}/
    judge_calibration/{development,validation}/
  fixtures/
  oracles/
  runners/
  graders/
  prompts/
  reporting/
tests/
  conftest.py
  support/
  contracts/
  integration/
  cli/
  evaluation/
src/retail_insight/integrations/phoenix/tracing.py
.artifacts/evaluation/            # Ignored generated output
docs/
  architecture.md
  task/
  plans/EVALUATION_REBUILD_PLAN.md
~~~

Package evaluation tooling behind a dedicated CLI; the application must not import it. Include the new package in Ruff/Pyright rather than copying the old `evals/` exclusion. Keep architecture in `docs/architecture.md`, assignment material in `docs/task/`, this plan in `docs/plans/`, and operational commands in the root README.

**CLI examples** (install dependencies with `uv sync --group evaluation`):

~~~bash
uv run retail-eval validate
docker compose -f infra/phoenix/compose.yaml up -d
uv run retail-eval sync --suite regression
uv run --group evaluation retail-eval run --suite smoke --repetitions 3 \
  --max-cost-usd 2 --deadline-seconds 2400 --allow-unreviewed
uv run --group evaluation retail-eval grade --run <run-directory> \
  --max-cost-usd 2 --deadline-seconds 1200
uv run --group evaluation retail-eval compare --baseline <baseline-grade-directory> --candidate <candidate-grade-directory>
~~~

`validate` checks schemas, splits, references, and hashes without model calls. `sync` mirrors a canonical dataset version. Finalize CLI validation in phase 1, including run and grading timeout settings. Execution prints the manifest, case count, model, capture policy, and limits.

| Trigger | CI checks |
|---|---|
| Every PR | Offline tests, lint/types, reference validation; no credentials/network |
| Observability changes | Local Phoenix integration with fake provider and synthetic canaries |
| Agent/prompt/tool changes | Explicitly initiated bounded development/regression smoke runs; human review during calibration |
| Release comparison | Frozen holdout, repeated baseline/candidate trials, independent grading and cost/latency comparison |
| Optional future schedule | Broader suite with explicit budget; not enabled by this plan |

Release gates require passing deterministic boundary tests, valid graders, verified targeted regressions, and no unresolved critical judgments. Any reproduced unauthorized disclosure/mutation, unreviewed publication, or budget violation blocks release. Establish quality/latency targets after the pilot and predeclare regression margins; nonsignificance does not establish equivalence. Publish attempted/completed/graded/failed/skipped counts. Zero observed violations is not proof of zero future risk.

## 12. Implementation and cutover

| Phase | Deliverables and exit criteria |
|---|---|
| 1. Contracts | Validated schemas, frozen atomic criteria, case-admission controls, split/suite manifests, oracle design; provenance and runtime visibility explicit |
| 2. Compatibility spike | Pinned Phoenix stack and optional instrumentation; actual runtime trace, persistence, privacy, accounting, and outage checks |
| 3. Foundations | Rewritten offline suite, distinguishing fixtures, deterministic graders, oracle mutations; no historical-capture dependencies or credentials |
| 4. Runner | Isolated conversations, run/grade phases, manifests, bounded execution; no leakage, hidden retries, cross-prompt accounting, or untracked timeout work |
| 5. Pilot | Calibrated judges with adversarial controls; 40 reviewed cases including answerability pairs and branching/context cases; per-turn, reviewer-impact, and repeated baseline results |
| 6. Atomic cutover | Remove old implementation, update CI/docs/configuration; new suite runnable without deleted paths |
| 7. Expansion | Toward 200 reviewed cases, frozen holdout; versioned comparisons with uncertainty and costs |

Compatibility acceptance checks:

1. Datasets, traces, experiments, and annotations survive server restart.
2. Analyst/tool/reviewer/provider-attempt linkage and usage reconcile without double-counting.
3. Revisions, provider failures, and budget exhaustion are represented accurately.
4. Follow-ups retain context with fresh prompt budgets.
5. Secret/thought canaries cannot escape capture policy.
6. Failed tasks execute once with retries disabled; repetitions remain distinct.
7. References never enter runtime inputs; regrading never reruns the agent.
8. Phoenix outages preserve chat operation and local artifacts with explicit publication errors.

At cutover, delete `evals/`, `scripts/evaluate_rewrite.py`, `scripts/calibrate_reviewer.py`, every old `tests/test_*.py` implementation, and obsolete dependencies/exclusions/configuration. Replace capture-based calibration with reviewed self-contained fixtures.

Update README, architecture, packaging, skills, and agent configuration references. Do not archive old code or commit generated capture collections. Work on an implementation branch: temporary coexistence is acceptable, but no published intermediate commit may leave the suite empty; the final cutover contains only reconstructed tests.

## 13. Completion criteria

The rebuild is complete when local Phoenix persists linked experiments and traces; runtime/evaluation data isolation passes; independent oracles expose incorrect SQL; calibrated graders detect the observed attribution and causal failures while accepting valid controls; and rewritten tests cover numerical, authorization, state, privacy, publication, accounting, and CLI contracts.

Grader attacks, case-admission controls, every-turn scoring, answerability pairs, and current context boundaries must be covered before trusting live pilot scores. Adaptive LLM simulation and broader sensitivity studies remain later extensions.

Multi-turn isolation, per-prompt limits, honest failure accounting, judge uncertainty, and repeatability must be demonstrated in a versioned baseline report. Old evaluation implementations and dependencies must be removed, with documentation aligned to `docs/task/`, `docs/architecture.md`, and `docs/plans/`.

Platform completion does not require the agent to meet future performance targets. The baseline must preserve genuine failures so subsequent runtime changes can be evaluated against them.

Evaluation measures protection; it does not provide it by itself. For each observed failure, use its trace to select a targeted prompt, skill, tool-contract, or review change; rerun the defect, its valid control, and the broader comparison. Runtime authorization and mutation checks remain application-enforced. Improve measured correction/abstention behavior without prescribing a fixed analytical workflow or adding an unvalidated reviewer to every tool call.

## 14. Implemented scope and remaining validation

The implementation uses Pydantic contracts in `evaluation/models.py` and `results.py`,
independent raw JSON fixtures rendered to SQL, immutable run snapshots, isolated conversation
execution, code graders, a tool-free Gemini judge, versioned grading outputs, and local Phoenix
publication. Phoenix's public `create`, `log_run`, and `log_evaluation` APIs import saved trials
with original timestamps and trace IDs. This replaces the proposed SDK task runner and avoids
implicit task retries or reference injection. Agent execution and grading stay separate.

The pilot contains 43 code-verified cases (40 core plus three edge cases) and 40 paired judge controls. Neither set claims
human approval. `--allow-unreviewed` explicitly admits diagnostic runs; ordinary admission
rejects unreviewed cases. No production success threshold or unseen holdout accuracy is claimed.
The comparison command checks grader/reference compatibility and reports uncertainty, including
missing repetitions. The test suite no longer depends on historical captures.

The platform still requires independent human reference review, adjudicated judge calibration,
a frozen held-out family split, product-specific quality margins, and controlled BigQuery
execution before release-quality conclusions. LLM user simulation, a 200-case expansion,
Bias/stability studies and production workload sampling remain
subsequent experiments. Local DuckDB denotations do not establish BigQuery equivalence.

Operational commands live in the root README. Reproducible dataset builders are maintenance
tools; rebuilding a dataset changes its version and requires comparable new baseline/candidate
runs. Repository Codex skills were removed at the user's request; runtime ADK analytical skills
remain part of the application under test.
