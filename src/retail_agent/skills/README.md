# Runtime skills

These files guide the running retail chatbot. Developer instructions for coding assistants remain in the separate repository `.agents/skills/` directory.

| Skill | Audience | Purpose |
| --- | --- | --- |
| [product-ranking-analysis](library/product-ranking-analysis/SKILL.md) | Analyst | Separate rankings, stable ties, selected populations and overlap |
| [revenue-driver-analysis](library/revenue-driver-analysis/SKILL.md) | Analyst | Prices, quantities, revenue per customer and supported explanations |
| [customer-retention](library/customer-retention/SKILL.md) | Analyst | Acquisition, repeat purchases, inactivity eligibility and denominators |
| [period-comparison](library/period-comparison/SKILL.md) | Analyst | Comparable periods, changes, zero bases and nonadditive counts |
| [business-report-writing](library/business-report-writing/SKILL.md) | Analyst | Proportionate synthesis, useful presentation and proposed actions |
| [analytical-review](library/analytical-review/SKILL.md) | Reviewer | Coverage, grounding, metrics, presentation and operation checks |

The analyst initially sees names, descriptions, versions and hashes. It chooses which instructions to read through `load_skill(name)`, and can read a listed Markdown reference through `load_skill_resource(name, path)`. A reference requires its parent skill to have been loaded in the current turn. These calls use the same budget, privacy screening and tracing as other tools. Loading guidance does not create a query result or authorize a new capability.

The application supplies `analytical-review` to every evaluator call, even when the analyst loads no skill. The reviewer remains tool-free. Its rubric is independent of the analyst's optional method choices.

## Add or edit a skill

Place a named directory directly under `library/` with a `SKILL.md` beginning with:

```yaml
---
name: your-skill-name
description: Explain the analytical situation where this method helps.
metadata:
  audience: analyst
  version: "1"
---
```

The name must match the directory. Use a focused description, guidance that permits different valid investigations, and concrete analytical pitfalls. Reference supporting files explicitly. Keep essential grounding and authorization requirements in the core instructions/application controls. Keep Golden examples and evaluation fixtures outside this library.

Supported resources are flat `references/*.md` files. This application's instruction-only skills do not contain scripts, tool grants, arbitrary file access or dynamic tool registration. The registry in `../tools/registry.py` is the explicit model tool surface; services implement its actual operations.

The catalog uses ADK's native `load_skill_from_dir` parser after validating the local text tree. Limits are 16 KB per SKILL.md, 8 KB per reference, eight references per skill, 32 skills and 120 KB for the whole library. Only audience/version metadata is accepted. Symbolic links and non-Markdown resources are rejected.

Skill text and references form an immutable snapshot when an `Analyst` instance starts. Restart the CLI to pick up edits. Bump the version for a changed method; hashes also identify exact content even if a version was not bumped. All files ship inside the Python wheel, so discovery is independent of the current working directory.

See the [runtime architecture](../../../docs/architecture.md#skills-and-golden-examples) for how skills fit into the agent loop and the [testing overview](../../../docs/architecture.md#testing) for validation. ADK documents the underlying [skills format and progressive disclosure](https://adk.dev/skills/).
