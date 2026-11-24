# Authored conversation scenarios

`manual_20.json` contains 20 English retail conversations, identified as `scenario-01` through
`scenario-20`, each with one initial prompt and one fixed follow-up. These are authored user-like
scenarios, not imported production
conversations or a representative traffic sample. They are intended for real-model execution,
inspection of every answer and observed tool result, and independently checked numerical facts.

Freeze this file before the baseline run. Keep initial prompts and follow-ups unchanged when
retesting runtime prompt or skill corrections; record every attempt rather than selecting only
successful answers. Checks describe acceptable behavior and remain outside the agent context.
They allow equivalent correct methods and explicitly supported limitations.

Nineteen conversations use Alice's Calvin Klein scope; one uses Bob's Levi's scope. Each starts
with isolated conversation and report state. Only `scenario-18` seeds reports, using two clearly
authored records to verify owner isolation and deletion cancellation. Those records must never
be added to an ordinary user's report library.

Topics cover ranking and overlap, period comparison, category reconciliation, metric grain,
repeat-order and acquisition cohorts, distinct-count unions, status overrides, catalog products
without qualifying sales, revenue concentration, unavailable profitability data, empty periods,
clarification, hypothetical currency conversion, authorization, report persistence, deletion,
and geographic aggregates. `oracle_topics` are audit labels, not routing instructions for the
agent or a required tool sequence.

Use the configured warehouse for live analytical execution and retain a separately collected
reference snapshot where possible. The default public TheLook source is example retail data;
running real queries against it must not be described as testing actual company production
traffic. Record query dates and any source-change limitations. Ordinary local fixture execution
cannot exercise the live geographic aggregate capability equivalently.

## Phoenix publication

`retail-eval run-conversations --max-cost-usd 10 --deadline-seconds 3600` executes this set
against BigQuery. It reuses the **Retail agent — 20 conversations** dataset and
`retail-conversations-20` trace project. Each dataset row contains both questions; each experiment
output contains both answers, automatic grades, and trace links. Dataset Output contains
independent facts and acceptance criteria for both turns, with source timestamps and hashes.
All source tables are pinned to the same timestamp for reference capture and agent queries.
Code compares extracted numerical claims with these references; independent LLM judgments assess
grounding, completeness, and trajectory. References never enter analyst context.

`manual_history.json` indexes archived captures and assistant reviews under `.artifacts/manual/`.
Their Phoenix experiments and traces were removed on 2026-11-23. Frozen artifacts retain their
original `manual-NN` identifiers; new runs use `scenario-NN`. Do not republish the archived manifest
into the reset workspace.

Keep complete runs and targeted retests separate. Runtime approval is not independent quality
approval. Historical assistant reviews are neither human validation nor calibrated judge scores.
See [evaluation](../../docs/evaluation.md) for commands, artifact locations, and review semantics.
