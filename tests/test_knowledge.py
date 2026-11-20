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
    assert disabled.search("revenue")["matches"] == []
    assert disabled.read("average_scoped_order_value")["status"] == "empty"
    wrong_scope = GoldenStore(CORPUS, ("Levi's",), bootstrap=True)
    assert wrong_scope.search("revenue")["matches"] == []
    assert wrong_scope.read("average_scoped_order_value")["status"] == "empty"
    allowed = GoldenStore(CORPUS, ("Calvin Klein",), bootstrap=True)
    assert allowed.read("average_scoped_order_value")["status"] == "ok"
    assert allowed.read("average_scoped_order_value")["synthetic_demo_mode"] is True


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Average value per order", "average_scoped_order_value"),
        ("Products with zero sales in the catalog", "catalog_without_sales"),
        ("Compare customer cohorts and retention", "monthly_cohort_retention"),
        ("90-day inactivity spike", "inactivity_false_spike"),
        ("Revenue and distinct customer rankings", "separate_product_rankings"),
    ],
)
def test_lexical_paraphrases_retrieve_a_relevant_method(query: str, expected: str) -> None:
    store = GoldenStore(CORPUS, ("Calvin Klein",), bootstrap=True)
    result = store.search(query, limit=3)
    assert result["status"] == "ok"
    assert expected in [match["id"] for match in result["matches"]]
    # Search provides methods, not numerical example evidence.
    assert all(
        "queries" not in match and "analyst_report_markdown" not in match
        for match in result["matches"]
    )
    assert "not current analytical evidence" in result["warning"]
    assert len(result["corpus_sha256"]) == 64


def test_search_handles_no_match_and_fts_syntax_as_plain_text() -> None:
    store = GoldenStore(CORPUS, None, bootstrap=True)
    assert store.search("interplanetary aardvarks")["status"] == "empty"
    assert store.search('" OR * ) NEAR(')["status"] == "empty"
    assert store.search("the and our 2026")["status"] == "empty"
    assert store.search("revenue", limit="many")["status"] == "invalid_request"  # type: ignore[arg-type]
    assert store.search("x" * 2001)["status"] == "invalid_request"
    assert len(store.search("revenue", limit=999)["matches"]) <= 5


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
    match = store.search("average order value")["matches"][0]
    match["scope"]["brands"].append("Leaked brand")
    assert "Leaked brand" not in store.read(match["id"])["example"]["scope"]["brands"]


def test_corrupt_fixture_and_missing_corpus_fail_closed(tmp_path: Path) -> None:
    collection = source()
    collection["fixture"]["sha256"] = "0" * 64
    store = GoldenStore(write_corpus(tmp_path, collection), None, bootstrap=True)
    assert store.search("revenue")["status"] == "unavailable"
    assert store.read("average_scoped_order_value")["status"] == "unavailable"
    missing = GoldenStore(tmp_path / "absent.json", None)
    assert missing.search("revenue")["status"] == "unavailable"


def test_fixture_path_cannot_escape_and_invalid_collections_expose_nothing(tmp_path: Path) -> None:
    collection = source()
    collection["fixture"]["path"] = "../../.env"
    assert (
        GoldenStore(write_corpus(tmp_path, collection), None, bootstrap=True).search("revenue")[
            "status"
        ]
        == "unavailable"
    )
    collection = source()
    collection["examples"].append(copy.deepcopy(collection["examples"][0]))
    store = GoldenStore(write_corpus(tmp_path, collection), None, bootstrap=True)
    assert store.search("revenue")["status"] == "unavailable"
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
    assert store.search("TAMPERED PRIVATE BODY")["matches"] == []
    assert store.read(valid_id)["example"]["provenance"]["human_reviewed"] is True


def test_scope_filter_precedes_indexing_and_read_does_not_bypass_it(tmp_path: Path) -> None:
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
    assert manager.search("xenolith")["matches"] == []
    assert manager.read(private["id"])["status"] == "empty"
    assert manager.read(all_brands["id"])["status"] == "empty"
    ceo = GoldenStore(path, None)
    assert ceo.search("xenolith")["matches"][0]["id"] == private["id"]
    assert ceo.read(all_brands["id"])["status"] == "ok"


def test_version_compatibility_applies_at_collection_and_record_levels(tmp_path: Path) -> None:
    collection = published()
    collection["examples"][0]["schema_version"] = "outdated"
    approve(collection["examples"][0])
    store = GoldenStore(write_corpus(tmp_path, collection), None)
    assert store.read(collection["examples"][0]["id"])["status"] == "empty"
    assert store.read(collection["examples"][1]["id"])["status"] == "ok"
    collection["metric_version"] = "different-defaults"
    store = GoldenStore(write_corpus(tmp_path, collection), None)
    assert store.search("revenue")["matches"] == []


def test_unmarked_collection_never_becomes_eligible(tmp_path: Path) -> None:
    collection = published()
    del collection["retrieval_policy"]["production_eligible"]
    path = write_corpus(tmp_path, collection)
    assert GoldenStore(path, None, bootstrap=True).search("revenue")["matches"] == []
    collection["purpose"] = "holdout_evaluation"
    path = write_corpus(tmp_path, collection)
    assert GoldenStore(path, None).search("revenue")["status"] == "unavailable"
