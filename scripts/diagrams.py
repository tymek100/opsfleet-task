"""Generate shared diagram sources/embeds; optionally render with pinned Mermaid CLI."""

import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "docs/diagrams"
TARGETS = {
    "architecture": "architecture.md",
    "request-flow": "architecture.md",
    "deletion": "architecture.md",
    "prototype": "technical_reasoning.md",
}


def generated_architecture():
    graph = json.loads((DIR / "architecture.json").read_text())
    lines = ["flowchart TB"]
    for node in graph["nodes"]:
        label = node["label"].replace("\n", "<br/>")
        lines.append(f'  {node["id"]}["{label}"]:::{node["kind"]}')
    for edge in graph["edges"]:
        lines.append(f'  {edge["source"]} -->|"{edge["label"]}"| {edge["target"]}')
    colors = {"external": "#eef2ff", "app": "#e0f2fe", "data": "#ecfdf5", "ops": "#fff7ed"}
    for kind, color in colors.items():
        lines.append(f"  classDef {kind} fill:{color},stroke:#64748b,color:#0f172a")
    mx = ET.Element("mxfile", host="app.diagrams.net")
    diagram = ET.SubElement(mx, "diagram", name=graph["title"], id="production")
    model = ET.SubElement(
        diagram, "mxGraphModel", grid="1", page="1", pageWidth="1380", pageHeight="900"
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")
    for node in graph["nodes"]:
        cell = ET.SubElement(
            root,
            "mxCell",
            id=node["id"],
            value=node["label"],
            vertex="1",
            parent="1",
            style=f"rounded=1;whiteSpace=wrap;html=0;fillColor={colors[node['kind']]};fontSize=14;strokeColor=#64748b;",
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            x=str(node["x"]),
            y=str(node["y"]),
            width="250",
            height="85",
            attrib={"as": "geometry"},
        )
    for i, edge in enumerate(graph["edges"]):
        cell = ET.SubElement(
            root,
            "mxCell",
            id=f"edge{i}",
            value=edge["label"],
            edge="1",
            parent="1",
            source=edge["source"],
            target=edge["target"],
            style="edgeStyle=orthogonalEdgeStyle;rounded=0;endArrow=block;html=0;fontSize=11;labelBackgroundColor=#ffffff;",
        )
        ET.SubElement(cell, "mxGeometry", relative="1", attrib={"as": "geometry"})
    ET.indent(mx)
    return "\n".join(lines) + "\n", ET.tostring(mx, encoding="unicode") + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--render",
        action="store_true",
        help="Requires Node/npm; downloads pinned Mermaid CLI if absent",
    )
    args = parser.parse_args()
    mmd, drawio = generated_architecture()
    expected = {DIR / "architecture.mmd": mmd, DIR / "architecture.drawio": drawio}
    for name, doc in TARGETS.items():
        path = ROOT / "docs" / doc
        current = expected.get(path, path.read_text())
        source = mmd if name == "architecture" else (DIR / f"{name}.mmd").read_text()
        marker = f"<!-- diagram:{name}:start -->"
        block = f"{marker}\n```mermaid\n{source.rstrip()}\n```\n<!-- diagram:{name}:end -->"
        pattern = re.escape(marker) + r".*?" + re.escape(f"<!-- diagram:{name}:end -->")
        updated, count = re.subn(pattern, lambda _, block=block: block, current, flags=re.S)
        if count != 1:
            raise SystemExit(f"Missing/duplicate diagram marker: {path} {name}")
        expected[path] = updated
    stale = []
    for path, content in expected.items():
        if not path.exists() or path.read_text() != content:
            if args.check:
                stale.append(str(path.relative_to(ROOT)))
            else:
                path.write_text(content)
    if stale:
        raise SystemExit("Stale diagrams: " + ", ".join(stale))
    if args.render:
        for name in TARGETS:
            subprocess.run(
                [
                    "npx",
                    "--yes",
                    "--package",
                    "@mermaid-js/mermaid-cli@12.0.0",
                    "mmdc",
                    "-i",
                    str(DIR / f"{name}.mmd"),
                    "-o",
                    str(DIR / f"{name}.svg"),
                    "-c",
                    str(DIR / "mermaid-config.json"),
                    "-b",
                    "white",
                ],
                check=True,
                cwd=ROOT,
            )
    print("Diagram sources, draw.io and Markdown are synchronized.")


if __name__ == "__main__":
    main()
