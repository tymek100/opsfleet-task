"""The model can load a small, fixed set of local Markdown guides."""

from pathlib import Path

from retail_insight.core.tool import Tool, ToolArgs

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills"
SKILLS = {
    "sales-analysis": "Revenue, orders, customers and product rankings.",
    "period-comparison": "Comparable time periods and percentage changes.",
    "clear-writing": "Readable reports and short, grounded summaries.",
}


class SkillArgs(ToolArgs):
    name: str


async def read_skill(name: str) -> dict:
    if name not in SKILLS:
        return {"error": "Unknown skill", "available": list(SKILLS)}
    return {"name": name, "instructions": (SKILL_DIR / f"{name}.md").read_text()}


def skill_tool() -> Tool:
    return Tool(
        "read_skill",
        "Load a local guide: "
        + "; ".join(f"{name}: {description}" for name, description in SKILLS.items()),
        SkillArgs,
        read_skill,
    )
