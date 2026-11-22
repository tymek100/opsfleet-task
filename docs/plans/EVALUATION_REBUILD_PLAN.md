# Evaluation rebuild: local Phoenix and independent reference data

**Status:** implementation plan; no existing tests or evaluation files have been deleted.
**Research date:** 2026-11-22. **Repository baseline:** 4d205c0.

## 1. The decision

Replace the current evaluation implementation and rewrite the test suite around the real application. Use **local Arize Phoenix** for traces, versioned datasets, experiment comparison, and evaluation annotations. Use independent code checks for numbers, permissions, and persisted state; use a calibrated LLM judge for factual support and language-level requirements.

The central question is: **Did the agent complete the user's task correctly, using authorized evidence, without inventing conclusions?** A runtime review approval, successful SQL execution, or attractive answer is insufficient by itself.

There will be three distinct things:

| Name | Purpose | Available to the running analyst? |
|---|---|---|
| **Golden Knowledge** | The assignment's reusable question/SQL/answer examples; help the agent choose an analytical method | Yes, through list_golden and read_golden when enabled |
| **Evaluation Golden Dataset** | Frozen tasks, environments, independently verified facts, and acceptance criteria | Only the task and ordinary authorized environment; never the reference answers |
| **Phoenix** | Inspect traces, compare experiments, store outputs and scores | No; it is not a retrieval source for the agent |

Keep the existing agentic runtime as the baseline under test. The analyst still selects tools, writes SQL, chooses the answer's structure, and revises drafts. Its runtime reviewer remains part of that system. An **offline evaluator** independently grades the result after the trial. This project replaces testing and evaluation; it does not require another rewrite of the agent's business logic.

Start with **40 carefully reviewed cases**, then expand toward 200 after the runner and graders prove useful. Generated volume is not a substitute for trusted references. Do not adopt the attachment's illustrative 95%/98% thresholds before measuring a baseline and deciding acceptable failure rates.

## 2. What is wrong with the current evaluation setup

The audit found 14 Python test files and 543 files under evals/. The problem is their organization and evidence quality, not simply their count:

- Historical runners import modules that no longer exist. Numerous committed captures and reports describe earlier implementations.
- The active evaluation script includes smoke checks based on approval, formatting, and numbers appearing in text. These cannot establish that a number belongs to the correct product, period, or category.
- Stronger numerical checks depend on a particular fixture and identity. They do not establish correctness on changed datasets or live BigQuery.
- Reviewer calibration and a test depend on old run captures inside evals/. Deleting the folder without replacing those dependencies breaks the remaining workflow.
- The 18 proposed holdout specifications are useful seeds, not a measured, independently validated holdout benchmark.
- Existing tests nevertheless protect important behavior: brand isolation, report ownership, exact publication, deletion confirmation, provider accounting, fresh per-prompt limits, and CLI behavior.

**Migration decision:** delete the old evals/ tree, both old evaluation runners, and all old test implementations at cutover. Rebuild necessary behavioral coverage in a new suite before that cutover. Do not move the old implementation into an archive directory. Git history already preserves it.

## 3. Research conclusions that shape this design

Agent evaluation needs both the execution trace and the actual outcome. Several valid tool sequences may accomplish the same task. Code, model, and human graders answer different questions and should be combined. This follows the practical approach described in [Anthropic's agent evaluation guide](https://www.anthropic.com/research/demystifying-evals-for-ai-agents).

For this application, two measurements must remain separate:

1. **Correctness:** Does the answer agree with independently calculated reference facts?
2. **Grounding:** Does the evidence actually observed by the agent support its claims?

An agent can faithfully repeat a result from incorrect SQL. That answer is grounded in its observation but numerically wrong. Conversely, a lucky correct answer can be unsupported by anything the agent observed.

Atomic-claim evaluation is useful for detecting unsupported explanations hidden inside otherwise correct answers. [FActScore](https://aclanthology.org/2023.emnlp-main.741/) motivates decomposition into individual facts; [FEVER](https://aclanthology.org/N18-1074/) distinguishes support, contradiction, and insufficient evidence. Their research domains differ from retail analytics: the proposed retail grader needs its own validation.

SQL correctness should be judged by results across distinguishing datasets, not by matching one reference query. Multiple fixtures expose mistakes that happen to produce the right answer on one database. See [semantic evaluation for text-to-SQL](https://arxiv.org/abs/2010.02840).

ADK offers trajectory and response evaluators, including exact and relaxed tool matching. They are optional diagnostic components here. The primary runner must exercise our application wrapper, budgets, reviewer, and report state. Exact tool sequences and ROUGE similarity will not be general quality gates. See [ADK evaluation criteria](https://adk.dev/evaluate/criteria/).

## 4. Target architecture

~~~mermaid
flowchart TD
    Input[Case inputs: identity and user turns] --> Runner[Isolated conversation runner]
    Runner --> App[Actual Analyst.ask runtime]
    Knowledge[Golden Knowledge] --> App
    Fixtures[Frozen warehouse and report state] --> App
    App --> Loop[Analyst chooses tools and drafts answer]
    Loop --> Review[Runtime reviewer]
    Review -->|Revise| Loop
    Review -->|Approved exact candidate| Result[Answer, observed evidence, actions, usage]
    Loop -->|Controlled failure| Result
    Result --> Graders[Independent code and calibrated LLM graders]
    References[Evaluation references and acceptance criteria] --> Graders
    App --> Traces[OpenInference and application spans]
    Traces --> Phoenix[Local Phoenix]
    Graders --> Phoenix
    Result --> Artifacts[Versioned local run artifacts]
~~~

The runtime reviewer can influence an answer before publication. The offline graders cannot: they observe completed trials. They do not send expected answers back into the analyst's context.

Phoenix is an inspection and comparison surface. Canonical cases, schemas, rubrics, and fixture definitions live in Git. Each experiment records their exact versions and exports an immutable local manifest, so its meaning does not depend on a mutable UI entry.

## 5. Clear data boundaries

| Asset | Proposed location | Rule |
|---|---|---|
| Runtime Golden Knowledge | Existing knowledge/golden/ | Method examples; never accepted as current business facts |
| Runtime demonstration fixture | Existing knowledge/fixtures/ | Supports examples; not the sole evaluation database |
| Evaluation tasks and references | evaluation/datasets/golden/ | Separate development, regression, and held-out splits |
| Evaluation warehouse fixtures | evaluation/fixtures/ | New, independently designed data with versioned hashes |
| Judge calibration examples | evaluation/datasets/judge_calibration/ | Correct and defective candidate answers with human labels; separate tuning and validation splits |
| Raw experiment artifacts | Ignored .artifacts/evaluation/ plus local Phoenix | Outputs and observations, not future test dependencies |

Keep the runtime knowledge path during this project. Renaming it would also affect repository-root discovery, fixture validation, loader assumptions, and public CLI/configuration behavior. Clear terminology and access boundaries provide the required distinction without an unrelated migration.

Evaluation references must never enter analyst prompts, tools, skills, runtime Golden Knowledge, or runtime review inputs. The experiment task adapter accepts **input only**. A trusted harness resolves fixture IDs and identity; it does not concatenate the whole dataset example into a prompt. Offline graders receive references through a separate interface.

Split by scenario family and data-generation family, not random paraphrases. Include different products, prices, ranking leaders, and category distributions from runtime examples. If a held-out failure informs a fix or prompt change, promote that case into regression and replace it before making another unseen-performance claim.

## 6. Local Phoenix deployment

Use one Docker Compose service, SQLite persistence on a named volume, and localhost-only HTTP access. PostgreSQL and a shared deployment are unnecessary for the initial developer setup. The official deployment supports this arrangement: [Docker deployment](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker).

Proposed configuration; the image placeholder must be replaced with a release/digest validated in the compatibility spike:

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

Authentication disabled is an explicit choice for this localhost-only development container. Shared access would require authentication. Verify these settings against the pinned server version; Phoenix's defaults and APIs have changed. See [configuration](https://arize.com/docs/phoenix/self-hosting/configuration) and [migration notes](https://github.com/Arize-ai/phoenix/blob/main/MIGRATION.md).

Use these separate endpoints:

- UI and client REST base: http://127.0.0.1:6006
- OTLP HTTP trace exporter: http://127.0.0.1:6006/v1/traces

Separate dependency groups:

- Application tracing: arize-phoenix-otel and openinference-instrumentation-google-adk.
- Evaluation tooling: arize-phoenix-client and arize-phoenix-evals.
- Tests: pytest and focused property-testing support where useful.
- Server: the Docker image; no requirement to install the full Phoenix server in the application environment.

Pin a compatible server/client/evals/instrumentor combination in the implementation. The existing application uses ADK 2.12.0 and a custom AccountedModel; compatibility must be demonstrated with this runtime.

**Local Phoenix means local storage and UI.** The existing Gemini agent still calls Google's API. A Gemini judge also sends its evaluation payload to Google. An optional local Ollama judge can be added after calibration; it does not make the Gemini agent local. Ollama's [structured-output support](https://docs.ollama.com/capabilities/structured-outputs) can support a custom Python evaluator, but valid JSON does not establish sound judgment.

## 7. Tracing the actual application

Use one explicitly configured tracer provider and instrument Google ADK once. Avoid enabling overlapping provider instrumentors without checking for duplicate spans. ADK documents the [Phoenix integration](https://adk.dev/integrations/phoenix/); OpenInference supplies the [ADK instrumentor](https://github.com/Arize-ai/openinference/tree/main/python/instrumentation/openinference-instrumentation-google-adk).

Create an application span for each user prompt. Link it to a stable conversation ID and a distinct turn ID. Analyst and runtime-reviewer calls must remain children of that prompt even though they use separate ADK sessions. Experiments additionally link every turn to its case, repetition, and experiment IDs.

Record model role/settings, tool name, duration, outcome, review revisions, budget status, and authoritative usage. In safe synthetic evaluations, also retain the exact observations and final candidate needed for grading. Link result handles to the observations the model could actually see; do not pretend it saw truncated or unread rows.

Use the application's provider ledger as the authoritative count of calls and tokens. Check instrumented usage against it. Summing tokens from both parent and nested model spans can double-count usage. Separate analyst, runtime reviewer, and offline judge costs; include thinking tokens when supplied by the provider.

AccountedModel currently retries inside one ADK model invocation. Verify that each actual provider attempt is observable; add per-attempt child spans or attempt IDs if automatic instrumentation only exposes the wrapper call. Reconcile attempts and settled usage with the ledger, including failed attempts.

Define two capture modes:

- **Normal chat:** metadata only by default, preserving the current privacy behavior.
- **Synthetic evaluation:** full approved synthetic prompts, observations, and answers, with credentials and confirmation secrets removed.

Instrumentor hiding controls are insufficient for custom attributes, exception messages, or dataset uploads. Canary tests must inspect every outbound trace and experiment payload. Do not capture hidden chain of thought; explicitly filter provider content parts marked as thought even in synthetic full-capture mode. See [OpenInference trace controls](https://arize-ai.github.io/openinference/spec/configuration/trace-config.html) and [OpenTelemetry sensitive-data guidance](https://opentelemetry.io/docs/security/handling-sensitive-data/).

A Phoenix outage must not block normal chat. Exports and shutdown flushes need bounded time. An evaluation retains its local result and reports a publishing failure, rather than falsely claiming that the Phoenix experiment completed.

## 8. The new Evaluation Golden Dataset

### Case contract

A case represents one user task or a complete scripted conversation. Each repetition starts from fresh application state. All prompts are English.

Illustrative YAML contract, to be formalized with validated schemas during implementation:

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
  golden_knowledge: enabled
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

Only the input projection reaches the application; environment fields configure the trusted harness. References and evaluation instructions are grader-only. The label **verified** is earned after reference checks and review; a generator cannot assign it automatically.

The full schema also declares acceptable outcomes per turn: answer, clarification, refusal, or an explicitly incomplete result. These depend on the task. An authorized refusal can pass an access-control case; exhaustion does not pass an ordinary analysis task merely because it was handled honestly. Fault schedules and scripted confirmation interactions belong to the trusted environment, so report-operation cases exercise the real confirmation boundary.

Support typed steps for ask, confirm_delete, and cancel_delete, plus explicit CLI-driving scenarios. The current CLI completes deletion through Analyst.confirm_delete, outside Analyst.ask. The trusted runner must resolve the selected preview's confirmation token through the same user-facing boundary; it must not expose that token to the model or auto-confirm merely because the model requests deletion.

Reference facts need explicit entity, metric, scope, period, unit, denominator, value, and tolerance. Monetary references use decimal arithmetic and declared rounding; counts and entity IDs are exact. Tie rules must reflect the task: accept justified alternatives where no unique tie-break was specified.

### Independent reference calculations

Build small warehouse datasets from source rows. Calculate trusted results using separately written Python Decimal/set operations, without importing the application's query compiler, reusing agent SQL, or accepting runtime reviewer output. Cross-check difficult calculations by a second method and human review.

Create distinguishing fixtures for:

- Multiple items per order and repeat orders per customer; unequal order sizes.
- Cross-brand customers, mixed-brand orders, and earlier purchases outside the authorized brand.
- Cancelled/returned order status independently varied from item status.
- Quarter boundaries, empty periods, zero denominators, and schema-valid nulls.
- Tied rankings, unsold products, revenue leaders different from customer leaders.
- Large negative category changes, more than three categories, and zero net change.
- Truncated results, bounded history, and changing follow-up requirements.

Prove the oracles detect plausible errors: COUNT instead of COUNT DISTINCT, item-average instead of order-average, incorrect status filters, an inclusive end boundary, missing brand scope, and wrong signed contributions. Use small mutation and metamorphic tests. For example, adding another brand's rows must leave a manager's results unchanged; a repeat purchase can increase orders without increasing distinct customers.

### Coverage and expansion

The initial 40 cases must cover every major family, including observed failures and successful controls. Expand toward the following 200-case inventory only after references and graders are trustworthy:

| Primary family | Target cases |
|---|---:|
| Core analytics and metric semantics | 60 |
| Unsupported claims, ambiguity, missing data | 35 |
| Multi-turn context and instruction changes | 35 |
| Tool/provider failures, recovery, exhaustion | 25 |
| Scope, ownership, injection, leakage | 25 |
| Report save/delete workflows | 20 |
| **Total** | **200** |

Cases can have several tags but exactly one primary family for this count. Freeze split manifests before tuning. Known failures belong in regression; held-out cases remain unused for prompt and grader development.

LLMs may draft scenarios, paraphrases, and candidate answers. Human review and independent calculations establish the reference facts. Runtime Golden examples must not be copied into evaluation and presented as evidence of generalization.

## 9. Rewritten test layers

| Layer | What executes | What it establishes |
|---|---|---|
| Contract and property tests | Real domain code, controlled clocks/stores, no provider calls | Scope, arithmetic, accounting, state changes, validation, privacy |
| Application integration | Real Analyst loop/tools/reviewer boundary with scripted model responses | Completion protocol, repair, follow-ups, cancellation, limits |
| Evaluator tests | Independent oracles, known good/bad answers, fake judge outputs | Scores detect intended defects and expose grading failures |
| Phoenix integration | Local server plus synthetic runs and fake provider | Export, persistence, linkage, annotations, sanitization |
| Live-model experiments | Real deployed application on frozen fixtures | Agent quality, reliability, latency and cost |
| BigQuery integration | Read-only queries against a controlled versioned dataset | BigQuery dialect and execution behavior beyond DuckDB |

Offline tests must construct explicit fake settings, temporary stores, and deterministic clocks. Block accidental network calls; do not load real .env files or ambient cloud credentials. Mock the model/provider or an external service boundary, not the brand filters, SQL compiler, or report logic being tested.

Coverage to reconstruct includes:

- Scope applied before joins, cohorts, and customer history; SQL sandbox escape attempts; query limits and cancellation.
- Correct grain, statuses, dates, denominators, tie handling, and evidence truncation.
- Only the exact reviewed candidate can be published or saved; reviewer feedback returns to the same analyst loop.
- Fresh per-prompt budgets with retained conversation context; analyst/reviewer/retry costs share only that prompt's budget; usage settles once and unknown usage remains conservative.
- Explicit report saves, owner isolation, exact deletion selection, expiring one-use confirmation, stale-preview rejection, and final database state.
- Skills and Golden catalog integrity, path restrictions, example/evidence separation, and bounded result reads.
- CLI prompt spacing, independently updating timer/status, completion menu navigation without automatic command execution, and piped input.

Test requirements rather than private implementation details. Do not require a particular SQL string, Golden example, skill, number of queries, or sequence of optional tools. Ordering checks belong to genuine protocols such as review-before-publication and confirmation-before-deletion.

DuckDB fixtures do not prove BigQuery compatibility. Keep controlled BigQuery integration separate. Mutable public TheLook queries may be useful live probes, but cannot silently share frozen numerical expectations. Record their data snapshot or label their numerical correctness ungraded.

Two small application seams are required. First, inject UTC/wall time for relative-date reasoning, history expiry, and report clocks; the runtime currently reads time directly. Keep real monotonic time for budget deadlines and asyncio cancellation. Second, configure trusted physical BigQuery source tables so integration tests can use controlled datasets; the current warehouse adapter hard-codes public TheLook sources. This configuration must stay outside model arguments and preserve scope enforcement.

## 10. What we measure

Each score stores a name/version, status, value or label, denominator, and evidence-linked explanation. Use explicit statuses such as PASS, FAIL, ERROR, UNJUDGEABLE, and NOT_APPLICABLE. A missing score is not a pass. Keep execution status separate from grading status.

### Core metrics

| Metric | Definition |
|---|---|
| **Task success** | All mandatory facts, instructions, and final-state checks pass, with no critical violation or unresolved required grading. Report successful/attempted trials, with failures and unscored trials separately visible. |
| **Required-fact coverage** | Required facts correctly communicated / required facts. Prevents an empty or evasive answer from winning on precision. |
| **Numeric correctness** | Correct required numeric facts / required numeric facts, matching entity, period, metric, unit, and scope as well as value. |
| **Reconciliation** | Displayed signed components and Other reconcile to the independent total under the declared precision. Selection of top components is checked separately. |
| **Grounded precision** | Supported factual claims / judgeable factual claims. Always show judgeable coverage and the status of extraction auditing alongside it. |
| **Unsupported claim rate** | Unsupported / judgeable factual claims. Unsupported does not necessarily mean false. |
| **Contradiction rate** | Contradicted / judgeable factual claims. |
| **Affected-answer rate** | Answers with at least one unsupported or contradicted claim / answers with judgeable factual claims. Also distinguish material task defects from minor defects. |
| **Instruction compliance** | Requested table count, columns, prose-only output, word limit, coverage, and requested actions. Do not impose an unrequested template. |
| **Action correctness** | Actual stored reports/deletions match ownership, selection, authorization, and content requirements. An operation receipt alone is insufficient. |
| **Boundary violations** | Separate counts for unauthorized disclosure/mutation, unconfirmed deletion, unreviewed publication, and budget violations. Never hide them in an average quality score. |

For factual-claim labels S, U, C, and J (unjudgeable), grounded precision is S/(S+U+C); judgeable coverage is (S+U+C)/(S+U+C+J). Zero factual claims yields NOT_APPLICABLE, not 100%. Missing or unextracted claims are an additional coverage defect. Measure extraction recall against manually annotated claims in calibration and audit samples; arbitrary live answers have no known claim-count denominator. Elsewhere record extraction recall as NOT_MEASURED and report the fraction of answers audited. Report claim-weighted micro scores and averages across cases/families so verbose answers or many paraphrases do not dominate.

### Reliability, performance, and reviewer metrics

- Report per-turn and per-conversation end-to-end latency, stage timings, sample count, median, p95, timeout count, and controlled-failure count. Show all-attempt and successful-attempt distributions; do not discard slow failures. Small-suite p95 is descriptive, not a production guarantee.
- Report analyst, runtime reviewer, query, and offline judge usage/cost separately. Include failed attempts. Costs derived from configurable prices are estimates with versioned rates; unknown usage/cost stays visible. Cost per successful task includes the cost of all attempts and is undefined when none succeed.
- Record invalid calls, repaired errors, identical repeated calls, review rounds, queries, and model calls as diagnostics. A recovered invalid SQL query does not automatically make the final task fail.
- Measure runtime reviewer false accepts among independently invalid candidates and false rejects among valid candidates. Include schema errors, retries, review latency, and defect type. Do not use its own verdict as its ground truth.
- Predeclare three repetitions per pilot case and size the selected suite to the run budget. Report single-attempt success and the fraction of cases succeeding on all three attempts. An additional any-of-three result is useful but optimistic. If the budget interrupts planned repetitions, report planned/completed coverage and mark the suite's consistency comparison incomplete; do not score only surviving complete groups. Do not estimate consistency by cubing the global average success rate. Repeated-trial evaluation and actual end-state checks are supported by [tau-bench](https://arxiv.org/abs/2406.12045).

Compare versions using identical cases, fixtures, repetitions, and judge versions. Alternate execution order to reduce temporal effects. Report paired per-case changes and confidence intervals with cases/families as the resampling unit; related claims are not independent trials. A small, inconclusive experiment must remain inconclusive. See [statistical testing guidance for NLP](https://aclanthology.org/P18-1128/).

## 11. Detecting unsupported explanations

### Claim-level grading pipeline

1. Extract atomic assertions from the answer, including table headings, row labels, qualifiers, comparisons, causal explanations, and the meaning of groups such as Other.
2. Preserve exact answer spans and bind each claim to entity, period, metric, scope, and relevant evidence IDs. Validate that quoted spans and IDs exist.
3. Check numerical claims against the independent oracle using code. Check evidence support against what the agent actually observed. Keep those results separate.
4. Use a calibrated LLM to judge implications and language-level support that code cannot reliably classify.
5. Combine claim findings with required-fact coverage, instructions, and state checks to determine task success.

Labels:

| Label | Meaning |
|---|---|
| SUPPORTED | Authorized observed evidence establishes the claim at the stated scope and precision |
| UNSUPPORTED | Evidence does not establish the assertion; it may still be true |
| CONTRADICTED | Evidence establishes an incompatible fact |
| NOT_FACTUAL | A suggestion or explicitly unasserted hypothesis; any factual premise inside it is still evaluated |
| UNJUDGEABLE | Missing evaluation artifacts, ambiguous reference, or extraction/judge failure; never silently accepted |

Missing evidence **because the agent did not obtain it** normally makes its assertion unsupported. Missing evidence **because the evaluation system lost it** is an evaluation error. Distinguish these causes.

For follow-ups, include authorized earlier observations actually retained or available to the agent, user-provided facts, and applicable metric definitions. Do not require an unnecessary new query. Do not grant the judge evidence from unread rows or unrelated conversation history as though the agent had observed it.

### Regressions taken from real conversations

**Non-overlapping rankings:** different top-five revenue and customer lists do not by themselves prove premium prices, lower volume, or a cause of revenue concentration. A qualified proposal to investigate price/units/mix is acceptable. An asserted explanation requires corresponding observations.

**Category summary:** the observed changes were Outerwear +932.42, Suits -383.51, Tops +272.99, and Other -122.40, totaling +699.50. A later summary omitted Tops but described -122.40 as all remaining categories after Outerwear and Suits. That remainder should be **+150.59**. Every quoted number can exist in a previous table while the summary is still misleading.

Turn this into a reviewed fixed-answer calibration pair and a new synthetic end-to-end conversation. The historical capture motivates the test; newly reviewed fixtures and oracles establish its expected values.

**Demand claims:** a revenue decline alone does not prove reduced demand. Label that assertion unsupported unless additional observations establish it. Include valid cautious recommendations as controls. Conversely, an exact arithmetic decomposition such as revenue = orders × AOV must not be rejected merely because it explains a change mathematically.

**Follow-up exhaustion:** the next user turn receives a fresh budget. It retains relevant approved context, not the previous turn's consumed allowance. Diagnose provider/reviewer latency separately from accounting failures.

### Calibrating the evaluator

Build roughly 40–60 manually labeled candidate/evidence bundles initially, with separate prompt-development and validation splits. Include correct concise answers, polished wrong answers, contradictions, wrong entities, omitted facts, unsupported causes, qualified hypotheses, and ambiguous cases. Have two people independently review difficult cases where possible, then adjudicate; record single-review cases honestly.

Blind the judge to agent version, model identity, runtime approval, and expected judgment labels. Give it the task, candidate, applicable rubric, and the right evidence/reference projection. Test extraction coverage, label confusion, false accepts, false rejects, abstention, and stability when judging the same answer repeatedly. Revalidate after changing judge model or prompt.

LLM judges can exhibit verbosity, position, and self-preference biases, as documented in [MT-Bench research](https://arxiv.org/abs/2306.05685). A different model from the runtime reviewer is worth testing, but model diversity is not independent truth. Keep human adjudication for disputed critical cases. Request brief evidence-linked findings, not hidden reasoning transcripts.

## 12. Running experiments without distorting results

Use a thin asynchronous runner around the actual Analyst.ask entry point and the trusted confirmation/cancellation actions described above. A case is one isolated conversation; turns within it share context, while different cases and repetitions receive fresh stores, sessions, clocks, and initial state. Target phoenix.client.experiments.async_run_experiment and async_evaluate_experiment for the pinned client; do not assume a synchronous wrapper gives equivalent timeout/cancellation behavior.

Current Phoenix experiment APIs can bind reference data or an entire example into task functions. Use a narrow input-only task adapter. The documented defaults also include a 60-second timeout and task retries. Set explicit parameters instead: **retries=0, initial concurrency=1**, and a whole-conversation deadline covering every prompt plus setup/cleanup. Phoenix dry-run mode still executes tasks; it is not a no-cost validation command. See the [Python experiment API](https://arize-phoenix.readthedocs.io/projects/client/api/experiments.html).

The app currently allows 120 seconds per prompt by default. A three-turn case therefore needs a harness deadline above 360 seconds, while each individual turn still has its own 120-second limit. Require bounded local teardown, using subprocess isolation where an operation cannot be reliably cancelled in-process. Request remote provider/query cancellation where supported, and record unresolved remote jobs and unknown usage explicitly; local cancellation does not prove a remote service stopped executing.

Use two explicit phases:

1. **Run:** produce immutable answers, observations, state snapshots, timing, usage, and execution status.
2. **Grade:** evaluate those artifacts with independent code and LLM graders, then publish versioned annotations.

This supports regrading without rerunning the agent or changing its cost. Judge timeouts, retries, and cost caps are separate from runtime budgets. Attach programmatic evaluators explicitly; dataset evaluators configured in Phoenix's UI do not automatically grade every Python experiment. See [dataset evaluator behavior](https://arize.com/docs/phoenix/datasets-and-experiments/how-to-experiments/how-to-dataset-evaluators).

Every live command declares a run-wide cost ceiling, deadline, and selected cases in addition to existing per-prompt limits. Reserve conservatively when usage is unknown. On exhaustion, retain completed trials and mark remaining ones NOT_EXECUTED. Do not rerun failures until green, choose the best repetition, or let infrastructure failures disappear from coverage reports.

Record Git commit/dirty diff hash, lockfile hash, dataset/version, fixture hash, metric policy, model/settings, prompt/skill/Golden hashes, judge version, repetition, and run limits. Store complete synthetic artifacts locally before upload. A score change caused by a new judge must be distinguishable from an agent improvement.

A useful first controlled experiment compares Golden Knowledge enabled versus disabled on the **same independent tasks**. Do not require the agent to read a particular example or penalize it for solving the task without retrieval.

## 13. Proposed repository layout

These paths are planned, except the existing runtime knowledge and documentation paths:

~~~text
EVALUATION_REBUILD_PLAN.md
infra/
  phoenix/compose.yaml
evaluation/
  cli.py
  settings.py
  schemas/
  datasets/
    golden/
      dev/
      regression/
      holdout/
    judge_calibration/
      development/
      validation/
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
knowledge/
  golden/                         # Runtime examples only
  fixtures/                       # Existing demonstration data
src/retail_agent/
  observability.py                # Small optional tracing adapter
.artifacts/evaluation/            # Ignored generated output
docs/
  architecture.md
  task/
~~~

The evaluation package owns case loading, execution, grading, and reporting. The application does not import it. Keep the package installable through a dedicated CLI entry point, with explicit packaging configuration. Include it in Ruff and Pyright; the current evals/ exclusion must not simply move to the new directory.

Keep docs/ limited to task/ and architecture.md as requested. Put operational evaluation instructions in the root README and concise package documentation/docstrings. Remove broken references to old runners from README, architecture, skills, and repository agent configuration during cutover.

## 14. Developer workflow and CI

The following commands describe the **target interface and do not exist yet**:

~~~bash
# Validate schemas, split integrity, references, and fixture hashes without model calls.
uv run retail-eval validate

# Start the pinned local inspection service.
docker compose -f infra/phoenix/compose.yaml up -d

# Mirror a selected canonical dataset version into local Phoenix.
uv run retail-eval sync --suite regression

# Run real agent trials within an explicitly chosen total ceiling.
uv run retail-eval run --suite smoke --backend fixture --repetitions 3 \
  --max-cost-usd <agent-run-ceiling>

# Grade saved results with a separate evaluation ceiling.
uv run retail-eval grade --run <run-id> --max-cost-usd <judge-run-ceiling>

# Compare matching dataset and evaluator versions.
uv run retail-eval compare --baseline <run-id> --candidate <run-id>
~~~

The first implementation milestone defines the final CLI and argument validation. Each run prints its manifest, selected case count, model, capture policy, and limits before execution. Run and grading timeouts also have explicit validated settings.

CI tiers:

| Trigger | Checks |
|---|---|
| Every PR | All offline contract/integration/evaluator tests, lint/types, dataset/reference validation; no cloud credentials or accidental model traffic |
| Observability changes | Local Phoenix integration with fake provider and synthetic canaries |
| Agent/prompt/tool changes | Explicitly started, bounded live smoke experiment on development/regression cases; human review while judges are being calibrated |
| Release comparison | Frozen held-out cases, repeated baseline/candidate trials, independent grading, cost/latency comparison |
| Optional scheduled run later | Selected broader live suite with a declared budget; not enabled by this plan |

Release rules:

- Mandatory deterministic boundary tests must pass. Any reproduced unauthorized operation, disclosure, unreviewed publication, or budget violation blocks release.
- Evaluators must detect audited defect/control pairs. Grading errors or unresolved critical judgments cannot produce a clean pass.
- Concrete regressions the change claims to fix must be verified; preserve all repetitions and investigate new failures.
- Establish quality and latency targets after the pilot. Declare any acceptable regression margin before comparing results. Lack of statistical significance is not evidence of equivalence.
- Publish attempted, completed, graded, failed, and skipped counts. Zero observed critical failures is a measured result for those cases, not a promise of zero future hallucinations or risk.

## 15. Implementation sequence and deletion plan

| Phase | Deliverables | Exit criteria |
|---|---|---|
| **1. Contracts and reference design** | Case/result/score schemas, family/split manifests, independent fixture/oracle design, list of mandatory existing behaviors | A reviewer can explain where truth comes from and what the analyst can see |
| **2. Phoenix compatibility spike** | Pinned local server/client/instrumentor, optional tracing adapter, synthetic experiment | Real app-shaped traces, persistence, privacy, budgets, and outage behavior verified |
| **3. New foundations** | Rewritten offline tests, distinguishing fixtures, deterministic graders, oracle mutation checks | Necessary scope/state/accounting contracts covered without old captures or real credentials |
| **4. Experiment runner** | Actual app adapter, isolated conversations, two-phase run/grade, manifests, bounded commands | No reference leakage, hidden whole-task retries, shared cross-prompt budgets, or untracked work after timeout |
| **5. Judge and pilot** | Calibrated claim/instruction graders, 40 reviewed cases, baseline with repetitions | Known bad answers fail, correct controls pass, disagreement and missing grading are visible |
| **6. Atomic cutover** | Delete old implementation, wire new CI/commands, update documentation and dependency references | New suite collected and runnable; no imports or fixture reads from deleted paths |
| **7. Broader comparison** | Expand toward 200 reviewed cases, frozen holdout, Golden on/off experiment | Versioned reports show quality, uncertainty, failure families, and runtime cost |

The compatibility spike must demonstrate:

1. Dataset, trace, experiment, and annotation persist across a local server restart.
2. AccountedModel, analyst, tool, and reviewer spans link correctly with no usage double-counting.
3. Revision, provider failure, and exhausted budget are represented accurately.
4. Two turns preserve context and receive fresh independent prompt budgets.
5. Secret canaries do not reach metadata-only tracing or unauthorized experiment payloads.
6. A deliberate task failure executes once with retries disabled; explicit repetitions remain separate.
7. Expected answers never enter runtime inputs; regrading does not rerun the agent.
8. Phoenix unavailability leaves chat usable and evaluations locally recoverable with explicit publication errors.

At cutover, delete:

- The complete old evals/ directory, including historical captures and unused scripts.
- scripts/evaluate_rewrite.py and scripts/calibrate_reviewer.py.
- Every old tests/test_*.py implementation, replaced by the new behavioral suite.
- Dependencies, lint exclusions, documentation references, and configuration that exist only for the removed workflow.

Keep runtime Golden Knowledge and its validator; update their tests and wording. Replace calibration inputs with reviewed self-contained fixtures rather than importing old capture folders. Check README, docs/architecture.md, pyproject.toml, repository skill guidance, and agent configuration for stale references. Do not create an archive or commit hundreds of new generated run files.

Do this on an implementation branch so no published intermediate commit leaves the project with an empty test suite. New tests may temporarily coexist with old ones while coverage is reconstructed; the final cutover contains only the new suite. This preserves the request to rebuild from scratch without discarding the application's requirements.

## 16. Definition of done

The evaluation rebuild is complete when:

- A documented local command starts persistent Phoenix and a bounded experiment appears with linked traces, outputs, references, and scores.
- Runtime Golden Knowledge and Evaluation Golden Dataset have different loaders, purposes, and access paths; leakage checks pass.
- Independent fixtures and calculations catch wrong SQL even when the answer accurately repeats its result.
- Claim grading catches unsupported price/demand explanations and the misleading Other summary, while accepting supported concise answers and qualified investigation proposals.
- Agent task success is determined independently of runtime reviewer approval.
- Multi-turn runs retain context, reset each prompt's budget, isolate repetitions, and retain honest timeout/error outcomes.
- Numerical, state, access, privacy, deletion, completion, accounting, and essential CLI contracts are covered by the rewritten offline suite.
- Judge calibration, missing-score coverage, repeated trials, and version-comparison uncertainty are visible.
- Old evals/, old evaluation runners, old test implementations, and their references are gone; docs/ still contains only task/ and architecture.md.
- A baseline report records real failures as failures. Completing the evaluation platform does not require pretending the agent already meets every future quality target.

The outcome is a system that can **find, explain, and prevent recurrence of specific failures**. Prompt or skill changes can then be measured against that evidence. Neither Phoenix nor an LLM judge can guarantee that every future answer will be hallucination-free.
