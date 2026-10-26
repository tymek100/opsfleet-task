---
name: retail-agent-evaluation
description: Build or run focused correctness, privacy, authorization, deletion, resilience, and answer-quality evaluations for this retail agent. Use for testing and release-readiness evidence, not as a mandatory gate on every small edit.
---

# Evaluate observable agent behavior

Read the requirements relevant to the change in [client Q&A](../../../docs/architecture.md#confirmed-scope-and-client-decisions). Consult the evaluation cases in [the research plan](../../../docs/technical_reasoning.md#model-planning-workflow) when preparing broader submission checks. Inspect implemented interfaces first; do not describe planned controls as tested controls.

Use [the testing strategy](../../../docs/technical_reasoning.md#evaluation-and-limitations) for fixture design, test layers, property/stateful cases, and release gates. The adjacent [Python testing skill](../python-testing-patterns/SKILL.md) supplies pytest mechanics when needed; it does not replace domain-specific assertions. Offline tests must be isolated from real credentials and providers. Distinguish schema-valid output, correct calculations, and a useful business answer as separate properties.

## Choose the right oracle

- Deterministic checks: safe query admission, authorization, correct metric values, model-boundary data, mutation state, deadline and retry budgets.
- BigQuery integration checks: dialect validity, job handling, cost controls, and a few real dynamic analyses.
- Model/human rubric: relevance, evidence-backed interpretation, useful actions, appropriate caveats, and executive readability. LLM grading alone cannot establish security or numerical truth.

Build a small synthetic fixture with two brands, shared customers, a mixed-brand order, repeated purchases, a return, ranking ties, empty periods, and time-boundary cases. Keep evaluation queries distinct from seeded Golden examples. Use multiple distinguishing cases; one correct result on one dataset can be accidental.

## Verify critical behavior

1. Attack the allowed query surface with nested relations, aliases/CTE shadowing, unions, forbidden identifiers in filters and functions, direct source paths, and malformed SQL. Inspect what actually reaches the executor.
2. Capture every outbound model request and log sink using synthetic PII canaries. Check source results and user-pasted input paths. Do not send real PII to a provider to test privacy.
3. Test manager isolation, CEO analytics, owner-only report reads/deletes, and follow-up context. No chat instruction may change identity or scope.
4. Assert database state before/after deletion: cancel, wrong owner, token expiry/replay, stale preview, newly matching reports, and valid exact deletion. A success message is not proof of a mutation.
5. Inject bounded SQL errors, genuine empty results, 429s, timeouts, and report-store failures. Verify no retry explosion, no fabricated result, no permission relaxation, and a usable CLI afterward.
6. Verify numeric results for the demo rankings/churn/report. Check an incorrect churn-spike premise, undefined denominators, and period changes across follow-ups.

Choose cases proportional to the change. Once relevant tests pass, broaden only for a real unresolved concern. Keep fault injection clearly labelled; never disguise fixtures or recorded answers as a live model run.

## Publish evidence honestly

Report executed case counts, outcomes, fixture date, model/version/settings, observed timings/costs, and skipped checks with reasons. Separate offline deterministic tests from credential-dependent integration and model evaluation. Small samples do not establish production percentiles or perfect safety. Use required-event assertions where multiple valid tool paths exist; avoid brittle exact transcript matching.

For persona evaluation design, distinguish automatic quality-gated publication from human-reviewed Golden examples. Gate on factual/number preservation, privacy, required caveats, and style; preserve the published version when evaluation fails or is unavailable.

Sources: [ADK evaluation](https://adk.dev/evaluate/), [agent outcomes and graders](https://www.anthropic.com/research/demystifying-evals-for-ai-agents), [semantic SQL evaluation](https://arxiv.org/abs/2010.02840).
