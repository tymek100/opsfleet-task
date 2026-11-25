"""Mutation contracts are asserted against persisted SQLite state."""

import json

import pytest

from retail_insight.integrations.reports import ReportError, ReportStore


def save(store, owner="workspace", answer="A1", title="Quarterly report"):
    result = store.save(
        owner,
        title,
        "Exact **approved** text.\n",
        [{"id": "E1", "rows": [{"revenue": 65.65}]}],
        answer,
    )
    artifact = store.read(owner, result["id"])
    assert artifact is not None
    return artifact


def test_save_preserves_exact_payload_is_idempotent_and_private(reports):
    first = save(reports)
    duplicate = save(reports)
    assert first == duplicate
    assert len(reports.search("workspace")) == 1
    assert reports.search("other-workspace") == []
    assert reports.read("other-workspace", first["id"]) is None
    stored = reports.read("workspace", first["id"])
    assert stored["markdown"] == "Exact **approved** text.\n"
    assert stored["evidence"] == [{"id": "E1", "rows": [{"revenue": 65.65}]}]
    with pytest.raises(ReportError) as error:
        reports.save("workspace", "Replacement", "Changed text", [], "A1")
    assert error.value.code == "idempotency_conflict"
    assert reports.read("workspace", first["id"]) == stored
    assert save(reports, owner="other-workspace")["id"] != first["id"]


def test_preview_is_nonmutating_bound_to_owner_conversation_and_exact_snapshot(reports):
    first = save(reports)
    outsider = save(reports, owner="other-workspace")
    preview = reports.preview_delete("workspace", "conversation", "Quarterly")
    token = preview["token"]
    assert reports.read("workspace", first["id"]) is not None
    assert (
        reports.confirm_delete("other-workspace", "conversation", token)["status"]
        == "invalid_confirmation"
    )
    assert (
        reports.confirm_delete("workspace", "different", token)["status"] == "invalid_confirmation"
    )
    later = save(reports, answer="A2")
    result = reports.confirm_delete("workspace", "conversation", token)
    assert result["status"] == "ok"
    assert result["deleted_ids"] == [first["id"]]
    assert reports.read("workspace", first["id"]) is None
    assert reports.read("workspace", later["id"]) is not None
    assert reports.read("other-workspace", outsider["id"]) is not None
    assert (
        reports.confirm_delete("workspace", "conversation", token)["status"]
        == "invalid_confirmation"
    )
    assert token not in json.dumps(
        [dict(row) for row in reports.db.execute("SELECT * FROM report_audit")]
    )


@pytest.mark.parametrize("change", ["markdown", "evidence_json", "version", "delete"])
def test_stale_selection_never_partially_deletes_reports(reports, change):
    first = save(reports)
    second = save(reports, answer="A2")
    preview = reports.preview_delete("workspace", "chat", "")
    if change == "delete":
        reports.db.execute("DELETE FROM agent_reports WHERE id=?", (first["id"],))
    else:
        values = {"markdown": "Edited", "evidence_json": "[]", "version": "replacement"}
        reports.db.execute(
            f"UPDATE agent_reports SET {change}=? WHERE id=?", (values[change], first["id"])
        )
    assert (
        reports.confirm_delete("workspace", "chat", preview["token"])["status"] == "stale_preview"
    )
    assert reports.read("workspace", second["id"]) is not None
    assert (
        reports.confirm_delete("workspace", "chat", preview["token"])["status"]
        == "invalid_confirmation"
    )


@pytest.mark.parametrize("operation", ["expire", "cancel", "replace"])
def test_expired_cancelled_and_replaced_confirmation_cannot_mutate(tmp_path, operation):
    now = [1000.0]
    store = ReportStore(tmp_path / "expiry.sqlite", clock=lambda: now[0], confirmation_ttl=30)
    try:
        artifact = save(store)
        preview = store.preview_delete("workspace", "chat", "")
        if operation == "expire":
            now[0] += 30
        elif operation == "cancel":
            store.cancel_delete("workspace", "chat")
        else:
            store.preview_delete("workspace", "chat", "")
        assert (
            store.confirm_delete("workspace", "chat", preview["token"])["status"]
            == "invalid_confirmation"
        )
        assert store.read("workspace", artifact["id"]) is not None
    finally:
        store.close()


def test_audit_failure_rolls_back_delete_and_token_consumption(reports):
    artifact = save(reports)
    preview = reports.preview_delete("workspace", "chat", "")
    reports.db.execute("""CREATE TRIGGER fail_delete_audit BEFORE INSERT ON report_audit
        WHEN NEW.action = 'hard_delete' BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(ReportError) as error:
        reports.confirm_delete("workspace", "chat", preview["token"])
    assert error.value.code == "storage_failure"
    assert reports.read("workspace", artifact["id"]) is not None
    reports.db.execute("DROP TRIGGER fail_delete_audit")
    assert reports.confirm_delete("workspace", "chat", preview["token"])["status"] == "ok"


def test_search_treats_sql_wildcards_literally_and_audit_contains_no_content(reports):
    save(reports, title="Quarterly 100%_review")
    save(reports, answer="A2", title="Other title")
    assert len(reports.search("workspace", "%_")) == 1
    audit = json.dumps([dict(row) for row in reports.db.execute("SELECT * FROM report_audit")])
    assert "Quarterly" not in audit and "approved" not in audit and "65.65" not in audit
    assert reports.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "evidence", [[{"number": float("nan")}], [{"number": float("inf")}], ["not an artifact"]]
)
def test_invalid_artifacts_leave_database_unchanged(reports, evidence):
    with pytest.raises(ReportError):
        reports.save("workspace", "Invalid", "Text", evidence, "A1")
    assert reports.db.execute("SELECT COUNT(*) FROM agent_reports").fetchone()[0] == 0


def test_legacy_import_preserves_source_and_only_copies_explicit_owner(reports, tmp_path):
    source = tmp_path / "legacy.json"
    source.write_text(
        json.dumps(
            [
                {
                    "id": "old-1",
                    "owner": "workspace",
                    "title": "Historical",
                    "body": {
                        "text": "Original historical text.",
                        "query_evidence": [{"revenue": 12}],
                    },
                },
                {
                    "id": "old-2",
                    "owner": "other-workspace",
                    "title": "Private",
                    "body": {"text": "Bob-only historical text."},
                },
            ]
        )
    )
    before = source.read_bytes()
    result = reports.import_legacy(source, "workspace")
    assert result["source_modified"] is False
    assert len(result["imported_ids"]) == 1
    saved = reports.read("workspace", result["imported_ids"][0])
    assert saved["markdown"] == "Original historical text."
    assert saved["evidence"] == [{"revenue": 12}]
    assert saved["historical_import"] is True
    assert reports.search("other-workspace") == []
    assert reports.import_legacy(source, "workspace")["existing_ids"] == result["imported_ids"]
    assert source.read_bytes() == before
