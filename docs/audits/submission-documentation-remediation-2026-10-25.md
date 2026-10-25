# Submission documentation remediation

Date: 2026-10-25. Follow-up to the [documentation audit](submission-documentation-2026-10-25.md). All nine findings are addressed in the submission documents. Application source is unchanged; no new live Gemini or BigQuery run was performed for this documentation work.

| Finding | Correction |
|---|---|
| D01 | Metric and technical definitions use explicit primary/baseline roles, allow disjoint periods and distinguish empty sales from unknown revenue and undefined percentage denominators. |
| D02 | Added an implemented-prototype diagram; README/setup/technical design describe typed planning, direct execution and optional ADK narration. |
| D03 | HLD specifies immutable publication, transactional outbox, authenticated task dispatch, durable job state, leases and explicit failed-job redrive. No native dead-letter queue is assumed. |
| D04 | Published exact ten prompts, sanitized captured responses, independent SQL/results, offline checker and opt-in isolated live runner in `evals/targeted-v4/`. |
| D05 | Distinguished minimized diagnostic context from content-free mutation audit, including filters, retention and access. |
| D06 | Specified embedding model, 768-dimensional configuration, task types, versioned publication and exact authorized-subset retrieval. ANN remains a measured future option. |
| D07 | Deletion state diagram and prose preserve pending state on invalid confirmation and distinguish cancellation, expiry and successful deletion. |
| D08 | Production graph uses deployed-service boundaries, one PostgreSQL store and explicit worker dependencies. Its source generates Mermaid and editable draw.io. |
| D09 | Current evaluation is concise; historical evidence is archived, the document index and demo excerpt are current, and diagram regeneration is documented. |

## Verification

- Offline suite: **167 passed, 17 live deselected**. Ruff lint/format and strict Pyright passed.
- Packaged recorded-evidence checker: **55/55 passed**, including comparison of all ten independent SQL evidence sets. This extends the original 50 assertions with four required-evidence checks and one combined SQL consistency check.
- Negative checker experiments rejected a missing case, missing oracle results and altered raw revenue.
- Live runner/oracle help commands work without credentials. Their live execution was not repeated; the portable harness adaptation and synthetic state-only seed are documented.
- All four Mermaid diagrams rendered with pinned Mermaid CLI 12.0.0 and installed Chrome; rendered previews were visually inspected. Generated sources, Markdown embeds and draw.io XML are synchronized. SVG and draw.io XML parse successfully. GitHub rendering and interactive draw.io layout were not independently exercised.
- Submission Markdown local file links resolve. Golden-trio examples still validate against their JSON schema.

The research corrections use official Cloud Tasks, BigQuery, ADK, pgvector, embedding and Mermaid documentation linked next to the relevant design claims. These sources inform a production proposal; they do not establish deployed behavior. Current runtime evidence and older failed attempts remain clearly distinguished.
