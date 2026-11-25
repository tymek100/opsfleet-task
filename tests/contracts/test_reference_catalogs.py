"""Runtime guidance has an explicit publication boundary and never becomes evidence."""

import json
from pathlib import Path

import pytest

from retail_insight.integrations.knowledge import GoldenStore, content_hash
from retail_insight.runtime.skills.catalog import SkillCatalog, SkillError


def published_record(name, brands, *, all_brands=False):
    record = {
        "id": name,
        "revision": 1,
        "scope": {"brands": brands, "all_brands": all_brands},
        "review_status": "approved",
        "visibility": "brand_scoped",
        "question": "How is average order value measured?",
        "tags": ["aov"],
        "method_notes": ["Use distinct scoped orders."],
        "analyst_report_markdown": "Historical illustrative AOV: 99.99.",
        "queries": [
            {"id": "q1", "sql": "SELECT 99.99 AS aov", "evidence": {"rows": [{"aov": 99.99}]}}
        ],
    }
    record["publication"] = {
        "editor_id": "editor",
        "reviewer_id": "reviewer",
        "approved_at": "2026-11-01T00:00:00Z",
        "content_sha256": content_hash(record),
    }
    return record


def corpus(tmp_path, records):
    path = tmp_path / "published.json"
    path.write_text(
        json.dumps(
            {
                "purpose": "retrieval_examples",
                "collection_id": "contract-methods",
                "revision": 1,
                "definitions": ["AOV divides scoped revenue by distinct orders."],
                "schema_version": "scoped-retail-v1",
                "metric_version": "retail-defaults-v1",
                "retrieval_policy": {"production_eligible": True},
                "examples": records,
            }
        )
    )
    return path


def test_catalog_filters_whole_source_scope_before_exposing_summaries(tmp_path):
    records = [
        published_record("own", ["Calvin Klein"]),
        published_record("other", ["Levi's"]),
        published_record("mixed", ["Calvin Klein", "Levi's"]),
        published_record("global", [], all_brands=True),
    ]
    path = corpus(tmp_path, records)
    manager = GoldenStore(path, ("Calvin Klein",))
    assert [item["id"] for item in manager.list_examples()["examples"]] == ["own"]
    for denied in ("other", "mixed", "global"):
        assert manager.read(denied)["status"] == "empty"
    assert len(GoldenStore(path, None).list_examples()["examples"]) == 4
    assert "not current analytical evidence" in manager.read("own")["warning"]


@pytest.mark.parametrize("mutation", ["content", "same_reviewer", "no_timezone", "draft"])
def test_unpublished_or_tampered_reference_is_not_visible(tmp_path, mutation):
    record = published_record("method", ["Calvin Klein"])
    if mutation == "content":
        record["analyst_report_markdown"] = "Tampered private text"
    elif mutation == "same_reviewer":
        record["publication"]["reviewer_id"] = "editor"
    elif mutation == "no_timezone":
        record["publication"]["approved_at"] = "2026-11-01"
    else:
        record["review_status"] = "draft"
    store = GoldenStore(corpus(tmp_path, [record]), ("Calvin Klein",))
    assert store.list_examples()["examples"] == []
    assert store.read("method")["status"] == "empty"


def test_catalog_is_snapshot_paged_and_return_values_are_defensive(tmp_path):
    records = [published_record(f"method_{index}", ["Calvin Klein"]) for index in range(23)]
    path = corpus(tmp_path, records)
    store = GoldenStore(path, ("Calvin Klein",))
    first = store.list_examples()
    second = store.list_examples(offset=first["next_offset"])
    assert len(first["examples"]) == 20 and len(second["examples"]) == 3
    assert len({r["id"] for r in first["examples"] + second["examples"]}) == 23
    assert "queries" not in first["examples"][0]
    first["examples"][0]["scope"]["brands"].append("Levi's")
    path.write_text("corrupted after load")
    assert store.read("method_0")["example"]["scope"]["brands"] == ["Calvin Klein"]
    assert GoldenStore(path, None).list_examples()["status"] == "unavailable"


def test_bootstrap_is_opt_in_and_fixture_integrity_is_checked(settings, tmp_path):
    assert GoldenStore(settings.golden_path, ("Calvin Klein",)).list_examples()["examples"] == []
    assert (
        GoldenStore(settings.golden_path, ("Calvin Klein",), bootstrap=True).list_examples()[
            "status"
        ]
        == "ok"
    )
    payload = json.loads(settings.golden_path.read_text())
    payload["fixture"]["path"] = "../../.env"
    path = tmp_path / "bad-bootstrap.json"
    path.write_text(json.dumps(payload))
    assert GoldenStore(path, None, bootstrap=True).list_examples()["status"] == "unavailable"


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
