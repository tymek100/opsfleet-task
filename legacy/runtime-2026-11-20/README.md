# Retail Analysis Assistant

**Next implementation: a from-scratch replacement.** Start with the [researched rewrite plan](docs/from-scratch-agent-plan.md): one autonomous analyst loop, evaluated completion, LLM-authored Markdown and optional tables, and working Golden retrieval. The plan and synthetic examples are prepared; the replacement runtime is not implemented yet. The description and commands below refer to the current prototype.

A CLI for brand-scoped analysis of BigQuery's TheLook dataset. One Gemini analyst chooses tools, observes results, and changes its investigation as needed. Every candidate answer passes through an evaluator; revision feedback returns to the same agent loop.

The design and implementation are documented in:

- [Architecture](docs/architecture.md): production HLD, diagrams, client constraints, services and data flows.
- [Technical reasoning](docs/technical_reasoning.md): implemented runtime, requirement coverage, metrics and evaluation.
- [Single-loop refactor](docs/autonomous-agent-refactor.md): the current prototype's earlier incremental design, superseded as a replacement plan.

Start with the separate [Quick Start Guide](QUICK_START.md) for setup, configuration and runnable examples. Use your own Gemini and Google Cloud credentials. The production HLD is a proposal; the delivered prototype runs locally.

**Golden Knowledge status: not connected to the current runtime; required in the rewrite.** The new [bootstrap corpus](knowledge/golden/README.md) contains 11 LLM-authored synthetic examples with fixture-checked SQL/results and varied answers. They are unapproved demonstration methods, separate from the older three illustrative trios and from the [proposed rewrite evaluations](evals/rewrite/README.md). The original [client Q&A](docs/task/q&a.md#6-golden-knowledge-prototype-scope) made runtime retrieval optional; the new rewrite request makes it required.

Try the [quick-start conversations](QUICK_START.md#example-conversations) for rankings, customer value, monthly trends and an explicit report save.

The model composes queries over a restricted virtual schema; application code enforces identity, brand scope, SQL admission, shared budgets and report mutations. Approved answers include evidence; interrupted investigations are labelled incomplete. `/details` shows query provenance. Slash commands remain deterministic, and only exact-token confirmation can delete reports.
