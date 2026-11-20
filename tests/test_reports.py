from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from retail_agent.reports import ReportError, ReportStore


@pytest.fixture
def clock() -> list[float]:
    return [1_000.0]


@pytest.fixture
def store(tmp_path: Path, clock: list[float]):
    reports = ReportStore(tmp_path / "reports.sqlite3", clock=lambda: clock[0])
    yield reports
    reports.close()


def save(store: ReportStore, answer_id: str = "answer-1", owner: str = "alice", title: str = "Q1"):
    return store.save(
        owner,
        title,
        "**Exact approved Markdown**\n\nRevenue: 375.00.",
        [{"id": "result-1", "rows": [{"revenue": 375.0}]}],
        answer_id,
    )


def test_save_preserves_exact_markdown_and_is_idempotent_by_owner_answer(store: ReportStore):
    first = save(store)
    repeated = save(store, title="A renamed retry must not mutate the saved report")
    assert first["created"] is True
    assert repeated["created"] is False
    assert first["id"] == repeated["id"]
    assert repeated["title"] == "Q1"
    stored = store.read("alice", first["id"])
    assert stored is not None
    assert stored["markdown"] == "**Exact approved Markdown**\n\nRevenue: 375.00."
    assert stored["evidence"] == [{"id": "result-1", "rows": [{"revenue": 375.0}]}]
    assert len(store.search("alice")) == 1
    assert store.db.execute("SELECT COUNT(*) FROM report_audit").fetchone()[0] == 1


def test_idempotent_key_cannot_overwrite_different_content(store: ReportStore):
    original = save(store)
    with pytest.raises(ReportError, match="different saved content"):
        store.save("alice", "Q1", "Changed answer", [], "answer-1")
    stored = store.read("alice", original["id"])
    assert stored is not None and stored["markdown"].startswith("**Exact")


def test_owner_isolation_including_ceo_and_literal_search(store: ReportStore):
    alice = save(store, title="Denim revenue 10%")
    bob = save(store, owner="bob", title="Bob's denim")
    assert store.read("ceo", alice["id"]) is None
    assert store.read("bob", alice["id"]) is None
    assert store.search("ceo", "denim") == []
    assert [report["id"] for report in store.search("alice", "DENIM")] == [alice["id"]]
    assert [report["id"] for report in store.search("alice", "%")] == [alice["id"]]
    assert store.search("alice", "_") == []
    assert "markdown" not in store.search("alice")[0]
    assert store.read("bob", bob["id"]) is not None


def test_preview_then_confirm_deletes_exact_snapshot_and_consumes_token(store: ReportStore):
    first = save(store, title="Denim Q1")
    preview = store.preview_delete("alice", "chat", "denim")
    second = save(store, "answer-2", title="Denim Q2")
    other = save(store, owner="bob", title="Denim for Bob")
    assert preview["status"] == "confirmation_required"
    assert [r["id"] for r in preview["reports"]] == [first["id"]]
    assert store.read("alice", first["id"]) is not None
    result = store.confirm_delete("alice", "chat", preview["token"])
    assert result["deleted_ids"] == [first["id"]]
    assert result["count"] == 1
    assert store.read("alice", first["id"]) is None
    assert store.read("alice", second["id"]) is not None
    assert store.read("bob", other["id"]) is not None
    assert (
        store.confirm_delete("alice", "chat", preview["token"])["status"] == "invalid_confirmation"
    )


@pytest.mark.parametrize(
    "owner,conversation", [("bob", "chat"), ("ceo", "chat"), ("alice", "other")]
)
def test_confirmation_binds_owner_and_conversation_without_consuming_valid_token(
    store: ReportStore, owner: str, conversation: str
):
    first = save(store)
    preview = store.preview_delete("alice", "chat", "")
    denied = store.confirm_delete(owner, conversation, preview["token"])
    assert denied["deleted_ids"] == []
    assert store.read("alice", first["id"]) is not None
    assert store.confirm_delete("alice", "chat", preview["token"])["count"] == 1


def test_confirmation_expires_at_exact_boundary(store: ReportStore, clock: list[float]):
    first = save(store)
    preview = store.preview_delete("alice", "chat", "")
    clock[0] = preview["expires_at"]
    assert (
        store.confirm_delete("alice", "chat", preview["token"])["status"] == "invalid_confirmation"
    )
    assert store.read("alice", first["id"]) is not None
    assert store.db.execute("SELECT COUNT(*) FROM report_deletions").fetchone()[0] == 0


def test_cancel_and_replaced_preview_cannot_be_replayed(store: ReportStore):
    first = save(store)
    previous = store.preview_delete("alice", "chat", "")
    current = store.preview_delete("alice", "chat", "")
    assert (
        store.confirm_delete("alice", "chat", previous["token"])["status"] == "invalid_confirmation"
    )
    assert store.cancel_delete("alice", "chat")["cancelled"] is True
    assert store.cancel_delete("alice", "chat")["cancelled"] is False
    assert (
        store.confirm_delete("alice", "chat", current["token"])["status"] == "invalid_confirmation"
    )
    assert store.read("alice", first["id"]) is not None


@pytest.mark.parametrize("column,value", [("version", "changed"), ("markdown", "Mutated content")])
def test_stale_preview_detects_version_and_content_change_atomically(
    store: ReportStore, column: str, value: str
):
    first = save(store)
    second = save(store, "answer-2")
    preview = store.preview_delete("alice", "chat", "")
    assert column in {"version", "markdown"}
    store.db.execute(f"UPDATE agent_reports SET {column}=? WHERE id=?", (value, second["id"]))
    result = store.confirm_delete("alice", "chat", preview["token"])
    assert result["status"] == "stale_preview"
    assert {report["id"] for report in store.search("alice")} == {first["id"], second["id"]}
    assert (
        store.confirm_delete("alice", "chat", preview["token"])["status"] == "invalid_confirmation"
    )


def test_missing_report_invalidates_entire_preview(store: ReportStore):
    first = save(store)
    second = save(store, "answer-2")
    preview = store.preview_delete("alice", "chat", "")
    store.db.execute("DELETE FROM agent_reports WHERE id=?", (second["id"],))
    assert store.confirm_delete("alice", "chat", preview["token"])["status"] == "stale_preview"
    assert store.read("alice", first["id"]) is not None


def test_empty_preview_removes_prior_confirmation(store: ReportStore):
    save(store)
    previous = store.preview_delete("alice", "chat", "")
    empty = store.preview_delete("alice", "chat", "no match")
    assert empty["status"] == "empty" and empty["token"] == "" and empty["reports"] == []
    assert (
        store.confirm_delete("alice", "chat", previous["token"])["status"] == "invalid_confirmation"
    )


def test_save_and_delete_rollback_when_audit_fails(store: ReportStore):
    store.db.execute("""
        CREATE TRIGGER fail_audit BEFORE INSERT ON report_audit
        BEGIN SELECT RAISE(ABORT, 'injected'); END;
    """)
    with pytest.raises(ReportError, match="could not complete"):
        save(store)
    assert store.search("alice") == []
    store.db.execute("DROP TRIGGER fail_audit")
    first = save(store)
    preview = store.preview_delete("alice", "chat", "")
    store.db.execute("""
        CREATE TRIGGER fail_delete_audit BEFORE INSERT ON report_audit
        WHEN NEW.action='hard_delete' BEGIN SELECT RAISE(ABORT, 'injected'); END;
    """)
    with pytest.raises(ReportError, match="could not complete"):
        store.confirm_delete("alice", "chat", preview["token"])
    assert store.read("alice", first["id"]) is not None
    store.db.execute("DROP TRIGGER fail_delete_audit")
    assert store.confirm_delete("alice", "chat", preview["token"])["count"] == 1


def test_hard_delete_removes_all_store_content_and_keeps_content_free_audit(store: ReportStore):
    secret = "SYNTHETIC_REPORT_CANARY_8a465c7a"
    stored = store.save("alice", secret, secret, [{"canary": secret}], "answer-canary")
    preview = store.preview_delete("alice", "chat", "")
    result = store.confirm_delete("alice", "chat", preview["token"])
    assert result["deleted_ids"] == [stored["id"]]
    assert store.db.execute("SELECT COUNT(*) FROM agent_reports").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM report_deletions").fetchone()[0] == 0
    columns = {row[1] for row in store.db.execute("PRAGMA table_info(report_audit)")}
    assert columns == {"id", "owner", "action", "record_count", "created_at"}
    assert secret.encode() not in store.path.read_bytes()


def test_audit_retention_does_not_expire_reports(store: ReportStore, clock: list[float]):
    original = save(store)
    clock[0] += 366 * 86400
    store.prune_audit()
    assert store.read("alice", original["id"]) is not None
    assert store.db.execute("SELECT COUNT(*) FROM report_audit").fetchone()[0] == 0


def legacy_answer() -> dict:
    return {
        "artifact_version": 2,
        "evaluation_status": "approved",
        "text": "Legacy exact narrative [E1].",
        "query_evidence": [{"id": "E1", "rows": [{"revenue": 350.0}], "sql": "SELECT 350"}],
        "evidence": [],
        "trace_id": "legacy-run",
        "warnings": ["historical"],
    }


def test_import_actual_legacy_sqlite_format_owned_only_and_source_unchanged(
    store: ReportStore, tmp_path: Path
):
    source = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(source) as database:
        database.execute("""
            CREATE TABLE reports (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, conversation TEXT NOT NULL,
                title TEXT NOT NULL, body TEXT NOT NULL, version TEXT NOT NULL, created REAL NOT NULL
            )
        """)
        for owner in ("alice", "bob"):
            database.execute(
                "INSERT INTO reports VALUES (?,?,?,?,?,?,?)",
                (
                    owner + "-old",
                    owner,
                    "old-chat",
                    owner + " historical",
                    json.dumps(legacy_answer()),
                    "v1",
                    100,
                ),
            )
    before = source.read_bytes()
    imported = store.import_legacy(source, "alice")
    assert imported["source_modified"] is False and len(imported["imported_ids"]) == 1
    artifact = store.read("alice", imported["imported_ids"][0])
    assert artifact is not None
    assert artifact["markdown"] == legacy_answer()["text"]
    assert artifact["legacy_payload"]["answer"] == legacy_answer()
    assert artifact["historical_import"] is True
    assert artifact["created_at"] == 100
    assert store.search("bob") == []
    again = store.import_legacy(source, "alice")
    assert again["imported_ids"] == [] and again["existing_ids"] == imported["imported_ids"]
    assert source.read_bytes() == before
    preview = store.preview_delete("alice", "chat", "")
    assert store.confirm_delete("alice", "chat", preview["token"])["count"] == 1
    assert source.read_bytes() == before
    assert b"Legacy exact narrative" not in store.path.read_bytes()


def test_json_import_requires_explicit_owner_and_is_atomic_on_malformed_owned_record(
    store: ReportStore, tmp_path: Path
):
    path = tmp_path / "export.json"
    records = [
        {"id": "a", "owner": "alice", "title": "Mine", "body": legacy_answer()},
        {"id": "b", "owner": "bob", "title": "Private", "body": legacy_answer()},
        {"id": "c", "title": "Unattributed", "body": legacy_answer()},
    ]
    path.write_text(json.dumps({"reports": records}))
    assert len(store.import_legacy(path, "alice")["imported_ids"]) == 1
    assert len(store.search("alice")) == 1
    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "id": "new",
                        "owner": "alice",
                        "title": "Would be new",
                        "body": {"text": "New"},
                    },
                    {
                        "id": "broken",
                        "owner": "alice",
                        "title": "Broken",
                        "body": {"not_text": "bad"},
                    },
                ]
            }
        )
    )
    with pytest.raises(ReportError, match="answer text"):
        store.import_legacy(invalid, "alice")
    assert len(store.search("alice")) == 1


def test_import_cannot_target_current_store(store: ReportStore):
    with pytest.raises(ReportError, match="separate"):
        store.import_legacy(store.path, "alice")


@pytest.mark.parametrize(
    "title,markdown,evidence",
    [
        ("", "Answer", []),
        ("Bad\x1bTitle", "Answer", []),
        ("Title", "", []),
        ("Title", "Answer", [{"value": float("nan")}]),
    ],
)
def test_rejects_invalid_artifacts_without_persistence(
    store: ReportStore, title, markdown, evidence
):
    with pytest.raises(ReportError):
        store.save("alice", title, markdown, evidence, "id")
    assert store.search("alice") == []
