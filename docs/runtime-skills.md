# Runtime skills and package organization

Updated: 20 November 2026. The implementation stays on Google ADK 2.12.0 and retains one analyst tool loop with a tool-free evaluator. The CLI commands and existing data/report formats remain unchanged.

## Package layout

```text
src/retail_agent/
├── cli.py                   # Terminal interface
├── runtime.py               # ADK assembly, conversation, bounded context
├── turn.py                  # Shared question state, budgets, artifacts, tracing
├── reviewer.py              # Isolated review and schema validation
├── tools/
│   ├── registry.py          # Explicit registration of 16 model-callable tools
│   ├── analytics.py         # Schema, queries, result reading/calculation
│   ├── knowledge.py         # Golden example search/read
│   ├── reports.py           # Prior answers, reports and staged operations
│   ├── completion.py        # Review submission and approved save commit
│   └── skills.py            # Instruction/reference loading
├── services/
│   ├── warehouse.py         # Scoped SQL, BigQuery, DuckDB, geography
│   ├── golden.py            # Eligible Golden corpus and FTS retrieval
│   └── reports.py           # Owner-private SQLite and deletion transactions
├── skills/
│   ├── catalog.py           # Validated ADK skill parsing and snapshots
│   ├── README.md            # Authoring and usage
│   └── library/<name>/
│       ├── SKILL.md
│       └── references/      # Optional Markdown reference files
├── prompts/                 # Small analyst/reviewer core instructions
└── config.py, contracts.py, budget.py, provider.py, privacy.py
```

Tools are small model-facing adapters with explicit signatures, bound to one shared `Turn`. Services own database and storage behavior. Skills contain analytical methods. The former inline `_Turn`/tool implementation was extracted from `runtime.py`; old `data.py`, `knowledge.py` and `reports.py` moved to the services package. Active imports and tests now use those locations. No compatibility shims or additional service abstraction layers were added.

## Research and implementation choice

ADK supports standard skill directories with name/description frontmatter, full instructions and optional resources, disclosed progressively. Its Python API includes `load_skill_from_dir` and `SkillToolset`. [ADK skills](https://adk.dev/skills/)

ADK derives function-tool schemas from signatures, type annotations and docstrings. Clear callable boundaries therefore serve both Python maintainers and the model. [ADK function tools](https://adk.dev/tools-custom/function-tools/)

The `tools/`, `services/` and `skills/` separation is this project's organization choice; ADK's [Python setup guide](https://adk.dev/get-started/python/) starts with a small agent package and does not require this particular layered layout.

The implementation reuses ADK's native skill parser and exposes two narrow function tools through the existing shared boundary. We did not directly register the broad `SkillToolset`: its own tool lifecycle would need additional adapters for our resource accounting, role checks and metadata-only trace. The packaged methods need only bounded Markdown reads. This preserves the current scope and does not enable script execution or arbitrary dynamic tools. The installed API was inspected alongside the online documentation; no dependency upgrade was required.

## How skills enter the loop

1. At startup, the application snapshots the six packaged skills. The analyst receives metadata for its five skills with the question context.
2. The model decides whether `load_skill(name)` is useful. Its full instructions enter the conversation as the tool observation. Nothing routes business questions through a fixed skill sequence.
3. `load_skill_resource(name, path)` can read a reference listed by an already loaded skill. The reference body was not present in the initial model context or the parent skill's tool response.
4. The analyst chooses SQL, other tools and the answer format as before. Skill guidance is not current business evidence and never receives an E-number.
5. `finish_answer` submits the candidate, evidence and loaded skill metadata. The application always adds the `analytical-review` instructions to the evaluator, which remains tool-free. Feedback returns to the same analyst loop.

The six methods and authoring instructions are listed in the [skill library README](../src/retail_agent/skills/README.md). Runtime skills are separate from `.agents/skills/`, which guide the coding assistant, and from `knowledge/golden/`, which supplies worked analytical examples. Evaluation labels and expected answers are never runtime skill content.

## Boundaries and maintenance

Skill reads count against the shared tool limit, deadline and model-context budget. Role filtering keeps the reviewer rubric out of the analyst's catalog. Load/resource events record names, versions and hashes without instruction bodies. The reviewer records its automatically supplied skill on each review. Unknown names, path traversal, unlisted references, oversized files, symlinks, tool-grant metadata and executable resources are rejected.

A skill cannot change application permissions, brand filters, report ownership or deletion confirmation. Those checks remain in code. Core instructions retain universal evidence and output requirements, while the detailed analytical guidance lives in skills. The evaluator's skill includes the specific requirement for actual unit-price/quantity evidence before accepting a price/volume explanation.

Restart the CLI to load edited skills into a new immutable catalog. Ordinary edits need no Python changes, but should increment the skill version and be checked against selected regressions. The library ships with the package; its source location does not depend on the working directory. Future externally managed skill publication would need its own provenance and update policy and is not implemented by this local directory.

See [test observations](runtime-skills-test-observations.md) for offline, packaging and real-model results. Loading the right instructions is observable; whether an LLM applies them correctly still requires independent assessment.
