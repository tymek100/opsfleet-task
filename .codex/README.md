# Repository skills

Skills for building and presenting this retail-agent interview assignment live in `../.agents/skills`. This directory stores their inventory and provenance. They guide the coding assistant; they are not runtime ADK tools, Python dependencies, or a guarantee of submission quality.

Codex discovers repository skills in `.agents/skills`; `.codex` does not need a duplicate skill tree or an invented configuration setting. See [official skill documentation](https://learn.chatgpt.com/docs/build-skills). They should be available on the next turn; if the client does not refresh discovery, restart it. No model, approval, sandbox, MCP, or global configuration settings were changed.

## Installed workflows

| Skill | Origin | Use |
|---|---|---|
| [retail-adk-implementation](../.agents/skills/retail-adk-implementation/SKILL.md) | Created for this repository | ADK/CLI implementation, typed tools, privacy boundaries, report confirmation, bounded recovery |
| [retail-analytics](../.agents/skills/retail-analytics/SKILL.md) | Created for this repository | Revenue and churn semantics, scoped BigQuery SQL, analytical evidence, Golden trios |
| [retail-agent-evaluation](../.agents/skills/retail-agent-evaluation/SKILL.md) | Created for this repository | Correctness, adversarial cases, mutation outcomes, fault injection, honest evaluation results |
| [python-testing-patterns](../.agents/skills/python-testing-patterns/SKILL.md) | Community skill from wshobson/agents, locally adapted | pytest fixtures, mocks, async testing, property-based cases, and CI mechanics |
| [interview-delivery](../.agents/skills/interview-delivery/SKILL.md) | Created for this repository | HLD, requirement mapping, reproducible setup, executive demo, interview explanation |
| [security-best-practices](../.agents/skills/security-best-practices/SKILL.md) | OpenAI curated | Explicit security reviews and secure-by-default coding guidance; load only relevant language/framework references |
| [security-threat-model](../.agents/skills/security-threat-model/SKILL.md) | OpenAI curated | Explicit repository-grounded threat modeling; distinguish actual controls from proposed production controls |

Examples of explicit invocation:

- `Use $retail-adk-implementation to build the first chat workflow.`
- `Use $retail-analytics to review our churn calculation.`
- `Use $retail-agent-evaluation to verify brand isolation and report deletion.`
- `Use $interview-delivery to review the submission from the interviewer's perspective.`
- `Use $security-threat-model to assess the implemented query and report boundaries.`

Use only the workflow relevant to the request. Installing skills does not authorize deployments, messages, public publication, or live destructive operations. The curated security workflows retain their upstream scope; installation alone does not request a security report or a threat-model session.

## Requirements and provenance

The local skills point to [client Q&A](../docs/architecture.md#confirmed-scope-and-client-decisions), [the original assignment](../docs/technical_reasoning.md#assignment-coverage), [architecture](../docs/architecture.md), and [the research plan](../docs/technical_reasoning.md#model-planning-workflow). Confirmed client answers take precedence over proposed defaults. Update the confirmed client decisions as new answers arrive instead of duplicating the full specification into each skill.

The two curated skills were installed using the bundled skill installer from [openai/skills at revision 49f948faa9258a0c61caceaf225e179651397431](https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.curated). Their licenses and references are retained unmodified. The generic `cli-creator` was inspected but excluded because its automation-tool scope and raw escape hatch are not a good fit for this app.

[skills-manifest.json](skills-manifest.json) records the installed revision, local skill names, and SHA-256 file hashes. It is a provenance record, not a Codex runtime configuration file. Regenerate affected hashes after intentional skill updates; do not overwrite local edits during an upstream refresh.

The community Python testing skill was reviewed and installed from [wshobson/agents at revision 0874a27b17a22e2b7c2e2bcd725768e0803cad06](https://github.com/wshobson/agents/tree/0874a27b17a22e2b7c2e2bcd725768e0803cad06/plugins/python-development/skills/python-testing-patterns). A local adaptation section adds offline credential isolation, current-version checks, and scope guidance; its MIT license is retained. Generic upstream examples include older CI versions and are teaching examples, not executable project configuration. The repo-specific [testing strategy](../docs/technical_reasoning.md#evaluation-and-limitations) supplies the required domain behavior.

Validation at setup: all six skills passed the bundled `quick_validate.py` checks. Local Markdown references were checked. Descriptions were reviewed for narrow activation, and workflows were reviewed against the agreed brand, privacy, hard-delete, and persona requirements. This is structural and instruction review, not a measured behavioral evaluation of the coding assistant or the retail app.
