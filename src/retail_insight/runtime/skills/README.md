# Runtime skills

This library contains runtime guidance for the retail analyst and reviewer.

| Skill | Audience | Purpose |
| --- | --- | --- |
| [product-ranking-analysis](library/product-ranking-analysis/SKILL.md) | Analyst | Separate rankings, stable ties, selected populations and overlap |
| [revenue-driver-analysis](library/revenue-driver-analysis/SKILL.md) | Analyst | Prices, quantities, revenue per customer and supported explanations |
| [customer-retention](library/customer-retention/SKILL.md) | Analyst | Acquisition, repeat purchases, inactivity eligibility and denominators |
| [period-comparison](library/period-comparison/SKILL.md) | Analyst | Comparable periods, changes, zero bases and nonadditive counts |
| [sales-status-analysis](library/sales-status-analysis/SKILL.md) | Analyst | Status-value shares, exclusions, and limits of refund/fulfillment interpretations |
| [business-report-writing](library/business-report-writing/SKILL.md) | Analyst | Proportionate synthesis, useful presentation and proposed actions |
| [analytical-review](library/analytical-review/SKILL.md) | Reviewer | Coverage, grounding, metrics, presentation and operation checks |

The analyst initially receives skill names, descriptions, versions and hashes. It selects instructions through `load_skill(name)` and listed Markdown references through `load_skill_resource(name, path)`. References require their parent skill to be loaded in the current turn. Both calls use the standard tool budget, privacy screening and tracing. Skill content is guidance, not query evidence or additional authorization.

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

The name must match the directory. Describe the skill's scope and analytical pitfalls without prescribing a fixed investigation. Reference supporting files explicitly. Essential grounding requirements belong in core instructions; authorization remains application-controlled. Evaluation fixtures belong outside this library.

Supported resources are flat `references/*.md` files. Skills contain instructions only: scripts, tool grants, arbitrary file access and dynamic tool registration are unsupported. `../tools/registry.py` defines the model-facing tool surface; services implement the operations.

The catalog uses ADK's native `load_skill_from_dir` parser after validating the local text tree. Limits are 16 KB per SKILL.md, 8 KB per reference, eight references per skill, 32 skills and 120 KB for the whole library. Only audience/version metadata is accepted. Symbolic links and non-Markdown resources are rejected.

An `Analyst` instance loads an immutable snapshot of skill text and references. Restart the CLI after edits. Increment the version when changing a method; hashes identify exact content independently of version labels. The Python wheel includes all skill files, so discovery is independent of the working directory.

See the [runtime architecture](../../../../docs/architecture.md#skills-and-evaluation-assets) for how skills fit into the agent loop and the [testing overview](../../../../docs/architecture.md#independent-evaluation) for validation. ADK documents the underlying [skills format and progressive disclosure](https://adk.dev/skills/).


## Ownership

Agent-specific instructions live beside their implementation in
`agents/<role>/skills/`. Shared report-writing guidance lives in
`runtime/skills/library/`; the mandatory reviewer guidance lives in
`review/skills/`.

`SkillCatalog()` composes the shared library, retail analytical methods and
reviewer guidance. This preserves the original method catalog and content hashes.
`AgentSkills` adds the inventory, distribution or coordinator catalog to that
baseline and includes its domain guidance in reviewer input. Skills remain
read-only method references; they do not grant tools or data access.
