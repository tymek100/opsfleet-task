# Submission documents

- [Architecture / HLD](architecture.md): components, services, protocols, storage, trust boundaries and all production requirements.
- [Detailed technical explanation](technical-design.md): chosen stack, implementation, safety, workflows, errors, costs, extensions and limitations.
- [Requirement mapping](requirements.md): implemented versus design-only coverage.
- [Metric definitions](metrics.md): revenue, customers, periods, churn, privacy cohorts and overrides.
- [Setup and example run](setup.md): external credentials, commands and troubleshooting.
- [Evaluation report](evaluation.md): executed evidence, failures fixed, limits and release criteria.
- [Demo guide](demo.md): priority scenarios and interview explanation.
- [Golden trios](golden-trios.json) and [schema](golden-trio.schema.json): illustrative samples, not client-supplied knowledge.
- [Editable architecture](diagrams/architecture.drawio): open in diagrams.net. [SVG preview](diagrams/architecture.svg) and editable `.mmd` sources accompany the diagrams embedded in the HLD.

The root [README](../README.md) and [QUICKSTART](../QUICKSTART.md) are the entry points. `mds/` retains requirements conversations and planning history; these submission documents describe the delivered prototype and production proposal.

Latest review: [documentation audit](audits/submission-documentation-2026-10-25.md) and [completed corrections](audits/submission-documentation-remediation-2026-10-25.md).

For review, start with setup, then the implemented prototype in the technical design, the proposed production HLD, requirement mapping and current evaluation. The [portable ten-case evaluation](../evals/targeted-v4/README.md) runs offline against recorded evidence. See [diagram maintenance](diagrams/README.md) for canonical sources and regeneration.
