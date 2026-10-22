# Python development

This document records the implementation plan only. No tooling configuration, package scaffold, or development environment is installed in this repository. Use Python 3.12 or newer. `pyproject.toml` will be the single source for dependency declarations, packaging, Ruff, strict Pyright, pytest, and coverage settings. Commit `uv.lock` for reproducible dependency versions. Add runtime dependencies with `uv add` as their functionality is implemented.

Once the tooling is implemented, use:

```sh
uv sync --locked --python 3.12
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked pytest
```

Use `uv run ruff format .` to format code. Configure pytest to disable sockets and exclude live markers by default. Live runs should require both explicit marker selection and `--enable-socket`, plus the credential and budget setup described in the testing strategy. Socket blocking does not prevent subprocess networking: offline tests must also avoid real CLI/cloud subprocesses and credential loading.

`--locked` tells uv to use the lockfile without updating it and fail when dependency declarations require a lockfile update. Use `uv add` or `uv lock` when intentionally updating dependencies.

## Module boundaries

Keep application code in `src/retail_agent/` and tests in `tests/`. Introduce focused modules as implementation requires them:

- `cli.py`: input/output and wiring, with no SQL or authorization decisions.
- `agent.py`: ADK orchestration and typed tool adapters.
- `models.py`: domain records and validated boundary schemas.
- `policy.py`: trusted brand permissions and privacy decisions.
- `queries.py`: SQL validation, scope enforcement, and query budgets.
- `bigquery.py`: cloud adapter with explicit typed results.
- `reports.py`: ownership, saving, confirmation state, and transactional deletion.
- `config.py` and `observability.py`: explicit configuration loading and safe structured events.

These are planned responsibilities, not empty modules to generate in advance. Domain logic must not import CLI or ADK orchestration. Pass dependencies explicitly; use small protocols where a real service boundary needs a fake implementation. Avoid generic repository frameworks, circular imports, catch-all `utils.py`, and module-import side effects such as reading `.env` or opening cloud connections.

Annotate functions, including tests. Use dataclasses or validated Pydantic models instead of loosely typed dictionaries at important boundaries. Static types do not validate model output or external data: validate those at runtime. Avoid blanket missing-import exclusions, `Any`, and suppressions; isolate an untyped SDK inside its adapter and explain any narrow suppression.

## Skills and references

Potential skills to add later: `python-type-safety` for annotations and interfaces and `python-project-structure` for module organization, from wshobson/agents. Adapt them to strict Pyright. Existing `retail-adk-implementation` and evaluation/testing skills cover agent behavior and meaningful tests. Skills guide development; the planned tools enforce checks.

References: [uv dependency management](https://docs.astral.sh/uv/concepts/projects/dependencies/), [Pyright configuration](https://github.com/microsoft/pyright/blob/main/docs/configuration.md), [Ruff configuration](https://docs.astral.sh/ruff/configuration/).
