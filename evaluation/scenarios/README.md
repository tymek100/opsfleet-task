# Authored conversation scenarios

`manual_20.json` contains 20 English retail conversations, each with one initial prompt and
one fixed follow-up. These are newly authored user-like scenarios, not imported production
conversations or a representative traffic sample. They are intended for real-model execution,
inspection of every answer and observed tool result, and independently checked numerical facts.

Freeze this file before the baseline run. Keep initial prompts and follow-ups unchanged when
retesting runtime prompt or skill corrections; record every attempt rather than selecting only
successful answers. Checks describe acceptable behavior and remain outside the agent context.
They allow equivalent correct methods and explicitly supported limitations.

Nineteen conversations use Alice's Calvin Klein scope; one uses Bob's Levi's scope. Each starts
with isolated conversation and report state. Only `manual-18` seeds reports, using two clearly
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
