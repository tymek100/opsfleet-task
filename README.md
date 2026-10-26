# Retail Analysis Assistant

A CLI for brand-scoped analysis of BigQuery's TheLook dataset, with Gemini planning and conversational answers, evidence-backed tables and reports, and explicit deletion confirmation.

The submission consists of two documents:

- [Architecture](docs/architecture.md): production HLD, diagrams, client constraints, services and data flows.
- [Technical reasoning](docs/technical_reasoning.md): implementation choices, requirement coverage, metrics and evaluation.

Start with the separate [Quick Start Guide](QUICK_START.md) for setup, configuration and runnable examples. Use your own Gemini and Google Cloud credentials. The production HLD is a proposal; the delivered prototype runs locally.

Try the [quick-start conversations](QUICK_START.md#example-conversations) for rankings, customer value, monthly trends and an explicit report save.

The model interprets questions and writes conversational replies; application code controls permissions, SQL, calculations and report mutations. Source details remain available through `/details`.
