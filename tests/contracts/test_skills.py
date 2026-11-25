"""Runtime skills have explicit capability boundaries and immutable provenance."""

from pathlib import Path

import pytest

from retail_insight.runtime.skills.catalog import SkillCatalog, SkillError


def write_skill(root: Path):
    skill = root / "custom-analysis"
    skill.mkdir(parents=True)
    (skill / "references").mkdir()
    (skill / "SKILL.md").write_text("""---
name: custom-analysis
description: Analyze scoped retail results.
metadata:
  audience: analyst
  version: "1.0"
---
Read references/method.md when useful. Never treat guidance as current facts.
""")
    (skill / "references/method.md").write_text("Use distinct order identifiers.")
    return skill


def test_skill_catalog_has_role_boundaries_and_immutable_reference_provenance(tmp_path):
    path = write_skill(tmp_path)
    catalog = SkillCatalog(tmp_path)
    metadata = catalog.list()[0]
    assert "instructions" not in metadata and "resources" not in metadata
    loaded = catalog.load("custom-analysis")
    assert loaded["resources"] == ["references/method.md"]
    first = catalog.read_resource("custom-analysis", "references/method.md")
    (path / "references/method.md").write_text("Changed instructions.")
    assert catalog.read_resource("custom-analysis", "references/method.md") == first
    assert SkillCatalog(tmp_path).list()[0]["sha256"] != metadata["sha256"]
    with pytest.raises(SkillError):
        catalog.load("custom-analysis", role="reviewer")
    for escape in (
        "../../.env",
        "/tmp/method.md",
        "references/../SKILL.md",
        "references\\method.md",
    ):
        with pytest.raises(SkillError):
            catalog.read_resource("custom-analysis", escape)


@pytest.mark.parametrize("unsafe", ["symlink", "script", "oversized", "tool_grant"])
def test_skill_loader_rejects_non_instruction_capabilities_before_loading(tmp_path, unsafe):
    path = write_skill(tmp_path)
    if unsafe == "symlink":
        (path / "references/link.md").symlink_to(path / "SKILL.md")
    elif unsafe == "script":
        (path / "execute.py").write_text("print('unexpected')")
    elif unsafe == "oversized":
        (path / "references/method.md").write_text("x" * 8001)
    else:
        file = path / "SKILL.md"
        file.write_text(file.read_text().replace("metadata:", "allowed-tools: shell\nmetadata:"))
    with pytest.raises(SkillError):
        SkillCatalog(tmp_path)
