# Runtime instructions and skills

Core instructions are loaded on every turn. Detailed analytical methods remain optional skills; the agent chooses when to read them.

| Layer | Responsibility |
| --- | --- |
| [Trust policy](../trust_policy.md) | Instruction/data boundaries and operation authority |
| [Runtime prompt](../prompt.md) | Evidence use, context, completion and report operations |
| [Shared answer style](../answer_style.md) | Concise writing and three fictional examples; always supplied to analysts and reviewers |
| Agent `prompt.md` | Role, capabilities and essential domain constraints |
| Agent `skills/` | Analytical methods and edge cases, loaded on demand |
| [Review prompt](../../review/prompt.md) and [rubric](../../review/skills/analytical-review/SKILL.md) | Mandatory completion checks; service reviewers also receive their domain skill |

The retail CLI and service agents share the same runtime and writing guidance. A summary is assessed against the current follow-up: select the main findings and preserve material limitations without reproducing every source metric. Examples teach presentation, not business facts or a fixed answer template. Independent offline evaluation prompts and references remain separate.

## Catalog

| Skill | Location |
| --- | --- |
| Product ranking, revenue drivers, customer retention, period comparison, sales status | [Retail skills](../../agents/retail/skills/) |
| Inventory analysis | [Inventory skills](../../agents/inventory/skills/) |
| Distribution analysis | [Distribution skills](../../agents/distribution/skills/) |
| Cross-domain analysis | [Coordinator skills](../../agents/coordinator/skills/) |
| Business report writing | [Shared library](library/business-report-writing/SKILL.md) |
| Analytical review | [Reviewer skill](../../review/skills/analytical-review/SKILL.md) |

`SkillCatalog()` combines retail methods, shared writing and reviewer guidance. `AgentSkills` adds the service role's methods and supplies those methods to its reviewer. Analyst context initially contains names, descriptions, versions and hashes; `load_skill(name)` reads a method, and `load_skill_resource(name, path)` reads a listed reference after its parent skill. Both use normal tool budgets, privacy screening and tracing. Skills grant no tools, access or permissions.

## Editing

Keep common rules in their shared source; do not repeat the writing policy inside each role or method. Keep essential domain constraints in the role prompt and detailed measurement guidance in skills. Increment a changed skill's version; exact content hashes provide provenance.

Each skill directory contains a `SKILL.md` with YAML frontmatter:

```yaml
---
name: your-skill-name
description: State when this analytical method helps.
metadata:
  audience: analyst
  version: "1"
---
```

The name matches the directory; audience is `analyst` or `reviewer`. Resources are flat `references/*.md` files. Scripts, tool grants, symbolic links and arbitrary file access are rejected. Limits: 16 KB per skill, 8 KB per reference, eight references per skill, 32 skills and 120 KB per catalog.

Catalogs use a validated YAML parser and take immutable snapshots. Restart a CLI or agent service after edits; rebuild its image when running Docker. Prompt assembly records shared files and hashes for Foundry attribution. The wheel includes Markdown instructions and skills.

See [architecture](../../../../docs/architecture.md#skills-and-evaluation-assets).
