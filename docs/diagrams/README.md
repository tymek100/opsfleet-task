# Diagram maintenance

Four diagrams accompany the submission:

| Diagram | Scope | Preview |
|---|---|---|
| Architecture | Proposed production deployment and service dependencies | [SVG](architecture.svg) |
| Prototype | Implemented local CLI, typed planning and direct execution | [SVG](prototype.svg) |
| Request flow | Proposed production request, validation and report draft | [SVG](request-flow.svg) |
| Deletion | Confirmation lifecycle; invalid attempts leave pending state intact | [SVG](deletion.svg) |

`architecture.json` is the canonical graph for production architecture. It generates `architecture.mmd` and the editable native [draw.io file](architecture.drawio). Edit labels, edges and draw.io coordinates in that JSON; manual changes to the generated draw.io file are overwritten on regeneration. The other three `.mmd` files are canonical sources. Generated Mermaid blocks are embedded in the HLD and technical design; SVGs are portable previews.

From the repository root:

```sh
uv run python scripts/diagrams.py
uv run python scripts/diagrams.py --check
uv run python scripts/diagrams.py --render
```

Rendering requires Node/npm and uses pinned Mermaid CLI 12.0.0. Puppeteer needs its matching browser installed; alternatively set `PUPPETEER_EXECUTABLE_PATH` to an installed Chrome executable. The command may download the CLI/browser dependencies. See [Mermaid CLI](https://github.com/mermaid-js/mermaid-cli).

`--check` verifies generated sources, draw.io and Markdown synchronization; it does not compare SVG pixels. After source changes, regenerate SVGs and visually review all affected diagrams. GitHub's Mermaid renderer may differ from the pinned local renderer. Colors distinguish external actors/services, application services, data stores and operational services; labels and arrows convey the actual responsibilities. The architecture diagram is a deployment overview, not a claim that the prototype deploys those services.
