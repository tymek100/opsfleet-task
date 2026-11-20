"""Skill disclosure preserves roles, content provenance and bounded read-only IO."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from retail_agent.skills import SkillCatalog, SkillError
from retail_agent.skills import catalog as catalog_module


def write_skill(
    root: Path,
    *,
    name: str = "example-analysis",
    audience: str = "analyst",
    body: str = "Use relevant evidence to answer the question.",
    metadata_extra: str = "",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Analyze an example.\nmetadata:\n"
        f'  audience: {audience}\n  version: "1"\n{metadata_extra}---\n\n{body}\n'
    )
    return directory


def test_bundled_catalog_discloses_metadata_before_instructions_and_resources() -> None:
    catalog = SkillCatalog()
    analyst = catalog.list()
    assert len(analyst) == 5
    assert all(set(item) == {"name", "description", "version", "sha256"} for item in analyst)
    assert {item["name"] for item in catalog.list(role="reviewer")} == {"analytical-review"}
    loaded = catalog.load("revenue-driver-analysis")
    assert loaded["instructions"]
    assert loaded["resources"] == ["references/measurement-guide.md"]
    reference = catalog.read_resource(loaded["name"], loaded["resources"][0])
    assert reference["content"] not in loaded["instructions"]
    assert reference["sha256"] == loaded["sha256"]
    assert reference["resource_sha256"] == hashlib.sha256(reference["content"].encode()).hexdigest()
    assert catalog.review_skill() == catalog.load("analytical-review", role="reviewer")


@pytest.mark.parametrize(
    ("name", "role"),
    [
        ("analytical-review", "analyst"),
        ("revenue-driver-analysis", "reviewer"),
        ("../../.env", "analyst"),
        ("missing-skill", "analyst"),
    ],
)
def test_skill_lookup_is_role_filtered_and_never_a_host_path(name: str, role: str) -> None:
    with pytest.raises(SkillError, match="No such skill"):
        SkillCatalog().load(name, role=role)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "path",
    ["../../.env", "/etc/passwd", "references/../SKILL.md", "references\\measurement-guide.md"],
)
def test_resources_are_exact_snapshot_keys_not_filesystem_paths(path: str) -> None:
    with pytest.raises(SkillError, match="No such reference"):
        SkillCatalog().read_resource("revenue-driver-analysis", path)


def test_catalog_is_a_snapshot_and_reference_changes_affect_provenance(tmp_path: Path) -> None:
    directory = write_skill(tmp_path)
    reference = directory / "references/measurement.md"
    reference.parent.mkdir()
    reference.write_text("Original guidance.\n")
    initial = SkillCatalog(tmp_path)
    before = initial.read_resource(directory.name, "references/measurement.md")
    reference.write_text("Revised guidance.\n")
    refreshed = SkillCatalog(tmp_path)
    after = refreshed.read_resource(directory.name, "references/measurement.md")
    assert initial.read_resource(directory.name, "references/measurement.md") == before
    assert before["sha256"] != after["sha256"]
    assert before["resource_sha256"] != after["resource_sha256"]
    assert after["content"] == "Revised guidance.\n"
    returned = initial.load(directory.name)
    returned["instructions"] = "Changed by caller."
    assert initial.load(directory.name)["instructions"] != returned["instructions"]


def test_symbolic_link_is_rejected_before_native_loader_can_read_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "library"
    directory = write_skill(library)
    outside = tmp_path / "outside.md"
    outside.write_text("Content outside the skill library.")
    references = directory / "references"
    references.mkdir()
    (references / "escape.md").symlink_to(outside)

    def unexpected_read(_directory: Path):
        pytest.fail("ADK must not read a skill containing a symbolic link")

    monkeypatch.setattr(catalog_module, "load_skill_from_dir", unexpected_read)
    with pytest.raises(SkillError, match="symbolic links"):
        SkillCatalog(library)


@pytest.mark.parametrize("target", ["SKILL.md", "references/large.md"])
def test_oversized_files_are_rejected_before_native_loading(tmp_path: Path, target: str) -> None:
    directory = write_skill(tmp_path)
    path = directory / target
    path.parent.mkdir(exist_ok=True)
    path.write_text("x" * 16_001)
    with pytest.raises(SkillError, match="byte limit"):
        SkillCatalog(tmp_path)


def test_scripts_and_state_or_tool_grants_cannot_enter_runtime_catalog(tmp_path: Path) -> None:
    directory = write_skill(tmp_path, metadata_extra="  adk_additional_tools: [shell]\n")
    with pytest.raises(SkillError, match="without tool grants"):
        SkillCatalog(tmp_path)
    (directory / "SKILL.md").write_text(
        (directory / "SKILL.md").read_text().replace("  adk_additional_tools: [shell]\n", "")
    )
    (directory / "scripts").mkdir()
    (directory / "scripts/run.py").write_text("raise RuntimeError('must not execute')\n")
    with pytest.raises(SkillError, match="references directory"):
        SkillCatalog(tmp_path)


def test_invalid_native_frontmatter_fails_closed(tmp_path: Path) -> None:
    directory = write_skill(tmp_path)
    path = directory / "SKILL.md"
    path.write_text(path.read_text().replace("name: example-analysis", "name: another-name"))
    with pytest.raises(SkillError, match="invalid ADK frontmatter"):
        SkillCatalog(tmp_path)


def test_entire_catalog_has_a_byte_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_skill(tmp_path)
    monkeypatch.setattr(catalog_module, "MAX_CATALOG_BYTES", 10)
    with pytest.raises(SkillError, match="library exceeds"):
        SkillCatalog(tmp_path)


@pytest.mark.parametrize("change_before_parse", [True, False])
def test_mid_load_edit_cannot_publish_a_mixed_skill_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change_before_parse: bool
) -> None:
    directory = write_skill(tmp_path)
    path = directory / "SKILL.md"
    original = path.read_text()
    native_load = catalog_module.load_skill_from_dir

    def edit_during_load(skill_directory: Path):
        if change_before_parse:
            path.write_text(original + "\nA newly edited instruction.\n")
        parsed = native_load(skill_directory)
        if not change_before_parse:
            path.write_text(original + "\nA newly edited instruction.\n")
        return parsed

    monkeypatch.setattr(catalog_module, "load_skill_from_dir", edit_during_load)
    with pytest.raises(SkillError, match="changed while loading"):
        SkillCatalog(tmp_path)
