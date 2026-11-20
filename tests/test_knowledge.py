"""Exercise the real local retrieval boundary, without model/network mocks."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from retail_agent.services.golden import GoldenStore, content_hash

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "knowledge/golden/bootstrap.json"


def source() -> dict:
    return json.loads(CORPUS.read_text())


def write_corpus(tmp_path: Path, collection: dict) -> Path:
    corpus = tmp_path / "knowledge/golden/examples.json"
    corpus.parent.mkdir(parents=True, exist_ok=True)
    fixture = tmp_path / "knowledge/fixtures/retail_seed_v1.sql"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_bytes((REPO / "knowledge/fixtures/retail_seed_v1.sql").read_bytes())
    corpus.write_text(json.dumps(collection))
    return corpus


def approve(record: dict) -> None:
    record.update(review_status="approved", visibility="brand_scoped")
    record["publication"] = {
        "editor_id": "editor-one",
        "reviewer_id": "reviewer-two",
        "approved_at": "2026-11-20T11:00:00Z",
        "content_sha256": content_hash(record),
    }


def published() -> dict:
    collection = source()
    collection["collection_id"] = "reviewed-methods-v1"
    collection["retrieval_policy"] = {"production_eligible": True}
    collection["provenance"] = {"author": "fixture editor", "human_reviewed": True}
    for record in collection["examples"]:
        approve(record)
    return collection


def test_bootstrap_requires_explicit_mode_and_scope() -> None:
    disabled = GoldenStore(CORPUS, ("Calvin Klein",))
    assert disabled.list_examples()["examples"] == []
    assert disabled.read("average_scoped_order_value")["status"] == "empty"
    wrong_scope = GoldenStore(CORPUS, ("Levi's",), bootstrap=True)
    assert wrong_scope.list_examples()["examples"] == []
    assert wrong_scope.read("average_scoped_order_value")["status"] == "empty"
    allowed = GoldenStore(CORPUS, ("Calvin Klein",), bootstrap=True)
    assert allowed.read("average_scoped_order_value")["status"] == "ok"
    assert allowed.read("average_scoped_order_value")["synthetic_demo_mode"] is True


def test_catalog_exposes_all_eligible_summaries_for_model_selection() -> None:
    store = GoldenStore(CORPUS, ("Calvin Klein",), bootstrap=True)
    result = store.list_examples()
    assert result["status"] == "ok"
    assert len(result["examples"]) == 11
    assert result["next_offset"] is None
    expected = source()["examples"]
    assert [item["id"] for item in result["examples"]] == [item["id"] for item in expected]
    assert [item["question"] for item in result["examples"]] == [
        item["question"] for item in expected
    ]
    # Listing lets the analyst choose methods; full examples require an explicit read.
    assert all(
        "queries" not in item and "analyst_report_markdown" not in item
        for item in result["examples"]
    )
    assert "not current analytical evidence" in result["warning"]
    assert len(result["corpus_sha256"]) == 64


def test_catalog_pagination_covers_all_examples_without_duplicates() -> None:
    store = GoldenStore(CORPUS, None, bootstrap=True)
    ids = []
    offset = 0
    while True:
        page = store.list_examples(offset=offset, limit=4)
        assert page["status"] == "ok"
        assert 1 <= len(page["examples"]) <= 4
        ids.extend(item["id"] for item in page["examples"])
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert ids == [item["id"] for item in source()["examples"]]
    assert len(set(ids)) == len(ids)
    empty = store.list_examples(offset=len(ids))
    assert empty["status"] == "empty"
    assert empty["examples"] == []
    assert empty["next_offset"] is None


def test_catalog_default_page_is_bounded_when_collection_grows(tmp_path: Path) -> None:
    collection = source()
    for index in range(12):
        extra = copy.deepcopy(collection["examples"][0])
        extra["id"] = f"additional_method_{index}"
        collection["examples"].append(extra)
    store = GoldenStore(write_corpus(tmp_path, collection), None, bootstrap=True)
    first = store.list_examples()
    assert len(first["examples"]) == 20
    assert first["next_offset"] == 20
    last = store.list_examples(offset=first["next_offset"])
    assert len(last["examples"]) == 3
    assert last["next_offset"] is None
    assert [item["id"] for item in first["examples"] + last["examples"]] == [
        item["id"] for item in collection["examples"]
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        {"offset": -1},
        {"offset": True},
        {"offset": "0"},
        {"offset": 1.5},
        {"limit": 0},
        {"limit": -1},
        {"limit": 21},
        {"limit": True},
        {"limit": "many"},
        {"limit": 1.5},
    ],
)
def test_catalog_rejects_invalid_pagination(arguments: dict) -> None:
    store = GoldenStore(CORPUS, None, bootstrap=True)
    assert store.list_examples(**arguments)["status"] == "invalid_request"


def test_full_trio_provenance_and_returned_objects_are_isolated() -> None:
    store = GoldenStore(CORPUS, ("Calvin Klein",), bootstrap=True)
    result = store.read("average_scoped_order_value")
    example = result["example"]
    assert example["queries"][0]["evidence"]["rows"][0]["average_order_value"] == 62.5
    assert "62.50" in example["analyst_report_markdown"]
    assert example["provenance"]["human_reviewed"] is False
    assert result["fixture_sha256"] == source()["fixture"]["sha256"]
    example["analyst_report_markdown"] = "Changed by caller"
    assert store.read(example["id"])["example"]["analyst_report_markdown"] != "Changed by caller"
    match = store.list_examples()["examples"][0]
    match["scope"]["brands"].append("Leaked brand")
    assert "Leaked brand" not in store.read(match["id"])["example"]["scope"]["brands"]
    assert "Leaked brand" not in json.dumps(store.list_examples())


def test_corrupt_fixture_and_missing_corpus_fail_closed(tmp_path: Path) -> None:
    collection = source()
    collection["fixture"]["sha256"] = "0" * 64
    store = GoldenStore(write_corpus(tmp_path, collection), None, bootstrap=True)
    assert store.list_examples()["status"] == "unavailable"
    assert store.read("average_scoped_order_value")["status"] == "unavailable"
    missing = GoldenStore(tmp_path / "absent.json", None)
    assert missing.list_examples()["status"] == "unavailable"


def test_fixture_path_cannot_escape_and_invalid_collections_expose_nothing(tmp_path: Path) -> None:
    collection = source()
    collection["fixture"]["path"] = "../../.env"
    assert (
        GoldenStore(write_corpus(tmp_path, collection), None, bootstrap=True).list_examples()[
            "status"
        ]
        == "unavailable"
    )
    collection = source()
    collection["examples"].append(copy.deepcopy(collection["examples"][0]))
    store = GoldenStore(write_corpus(tmp_path, collection), None, bootstrap=True)
    assert store.list_examples()["status"] == "unavailable"
    assert store.read("average_scoped_order_value")["status"] == "unavailable"


def test_production_approved_entries_require_attestation_and_integrity(tmp_path: Path) -> None:
    collection = published()
    valid_id = collection["examples"][0]["id"]
    collection["examples"][1]["publication"]["reviewer_id"] = "editor-one"
    collection["examples"][2]["analyst_report_markdown"] = "TAMPERED PRIVATE BODY"
    collection["examples"][3]["publication"]["approved_at"] = "yesterday"
    collection["examples"][4]["review_status"] = "draft"
    collection["examples"][5]["review_status"] = "retired"
    store = GoldenStore(write_corpus(tmp_path, collection), ("Calvin Klein",))
    assert store.read(valid_id)["status"] == "ok"
    for record in collection["examples"][1:6]:
        assert store.read(record["id"])["status"] == "empty"
    visible_ids = {item["id"] for item in store.list_examples()["examples"]}
    assert valid_id in visible_ids
    assert visible_ids.isdisjoint(record["id"] for record in collection["examples"][1:6])
    assert "TAMPERED PRIVATE BODY" not in json.dumps(store.list_examples())
    assert store.read(valid_id)["example"]["provenance"]["human_reviewed"] is True


def test_scope_filter_precedes_listing_and_read_does_not_bypass_it(tmp_path: Path) -> None:
    collection = published()
    private = collection["examples"][0]
    private["scope"]["brands"] = ["Calvin Klein", "Levi's"]
    private["question"] = "Private canary xenolith economics"
    approve(private)
    all_brands = collection["examples"][1]
    all_brands["scope"] = {"brands": [], "all_brands": True}
    approve(all_brands)
    path = write_corpus(tmp_path, collection)
    manager = GoldenStore(path, ("Calvin Klein",))
    visible_ids = {item["id"] for item in manager.list_examples()["examples"]}
    assert private["id"] not in visible_ids
    assert all_brands["id"] not in visible_ids
    assert "xenolith" not in json.dumps(manager.list_examples())
    assert manager.read(private["id"])["status"] == "empty"
    assert manager.read(all_brands["id"])["status"] == "empty"
    ceo = GoldenStore(path, None)
    visible_ids = {item["id"] for item in ceo.list_examples()["examples"]}
    assert private["id"] in visible_ids
    assert all_brands["id"] in visible_ids
    assert ceo.read(all_brands["id"])["status"] == "ok"


def test_version_compatibility_applies_at_collection_and_record_levels(tmp_path: Path) -> None:
    collection = published()
    collection["examples"][0]["schema_version"] = "outdated"
    approve(collection["examples"][0])
    store = GoldenStore(write_corpus(tmp_path, collection), None)
    assert store.read(collection["examples"][0]["id"])["status"] == "empty"
    assert store.read(collection["examples"][1]["id"])["status"] == "ok"
    assert collection["examples"][0]["id"] not in {
        item["id"] for item in store.list_examples()["examples"]
    }
    collection["metric_version"] = "different-defaults"
    store = GoldenStore(write_corpus(tmp_path, collection), None)
    assert store.list_examples()["examples"] == []


def test_unmarked_collection_never_becomes_eligible(tmp_path: Path) -> None:
    collection = published()
    del collection["retrieval_policy"]["production_eligible"]
    path = write_corpus(tmp_path, collection)
    assert GoldenStore(path, None, bootstrap=True).list_examples()["examples"] == []
    collection["purpose"] = "holdout_evaluation"
    path = write_corpus(tmp_path, collection)
    assert GoldenStore(path, None).list_examples()["status"] == "unavailable"
