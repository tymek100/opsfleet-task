import pytest

from retail_agent.models import Answer, AppError
from retail_agent.reports import ReportStore


def test_exact_set_new_matches_and_replay(store: ReportStore, answer: Answer) -> None:
    first = store.save("alice", "chat", "Calvin Klein Q1", answer)
    preview = store.preview("alice", "chat", "calvin klein", now=100)
    later = store.save("alice", "chat", "Calvin Klein Q2", answer)
    assert store.confirm("alice", "chat", preview.token, now=101) == 1
    assert [r.id for r in store.list("alice")] == [later]
    with pytest.raises(AppError):
        store.read("alice", first)
    with pytest.raises(AppError):
        store.confirm("alice", "chat", preview.token, now=102)


@pytest.mark.parametrize(
    "owner,conversation,now",
    [("bob", "chat", 101), ("ceo", "chat", 101), ("alice", "other", 101), ("alice", "chat", 401)],
)
def test_confirmation_owner_session_expiry(
    store: ReportStore, answer: Answer, owner: str, conversation: str, now: float
) -> None:
    rid = store.save("alice", "chat", "Q1", answer)
    preview = store.preview("alice", "chat", now=100)
    with pytest.raises(AppError):
        store.confirm(owner, conversation, preview.token, now=now)
    assert store.read("alice", rid) == answer


def test_cancel_and_stale_version(store: ReportStore, answer: Answer) -> None:
    rid = store.save("alice", "chat", "Q1", answer)
    preview = store.preview("alice", "chat", now=100)
    store.cancel("alice", "chat")
    with pytest.raises(AppError):
        store.confirm("alice", "chat", preview.token, now=101)
    preview = store.preview("alice", "chat", now=100)
    store.db.execute("UPDATE reports SET version=? WHERE id=?", ("changed", rid))
    with pytest.raises(AppError):
        store.confirm("alice", "chat", preview.token, now=101)
    assert len(store.list("alice")) == 1


def test_conversation_matching_and_private_reports(store: ReportStore, answer: Answer) -> None:
    own = store.save("alice", "one", "own", answer)
    store.save("alice", "two", "other", answer)
    store.save("bob", "one", "bobs", answer)
    assert store.list("ceo") == []
    with pytest.raises(AppError):
        store.read("ceo", own)
    preview = store.preview("alice", "one", conversation_only=True)
    assert [r.id for r in preview.reports] == [own]
    assert store.confirm("alice", "one", preview.token) == 1
    assert len(store.list("alice")) == 1 and len(store.list("bob")) == 1


def test_deletion_purges_managed_chat_copies_keeps_content_free_audit(
    store: ReportStore, answer: Answer
) -> None:
    store.save("alice", "chat", "private", answer)
    store.append_chat("alice", "chat", answer)
    preview = store.preview("alice", "chat")
    store.confirm("alice", "chat", preview.token)
    assert store.db.execute("SELECT COUNT(*) FROM chats").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM pending").fetchone()[0] == 0
    assert store.db.execute('SELECT count FROM audit WHERE action="hard_delete"').fetchone()[0] == 1
    columns = [r[1] for r in store.db.execute("PRAGMA table_info(audit)")]
    assert "body" not in columns and "title" not in columns


def test_transaction_rolls_back_entire_set_on_stale_report(
    store: ReportStore, answer: Answer
) -> None:
    first = store.save("alice", "chat", "one", answer)
    second = store.save("alice", "chat", "two", answer)
    preview = store.preview("alice", "chat")
    store.db.execute("UPDATE reports SET version=? WHERE id=?", ("changed", second))
    with pytest.raises(AppError):
        store.confirm("alice", "chat", preview.token)
    assert {r.id for r in store.list("alice")} == {first, second}


def test_save_audit_failure_rolls_back_and_retry_is_idempotent(
    store: ReportStore, answer: Answer
) -> None:
    import sqlite3

    store.db.execute("""
      CREATE TRIGGER fail_save BEFORE INSERT ON audit
      WHEN NEW.action = 'save' BEGIN SELECT RAISE(ABORT, 'injected'); END;
    """)
    with pytest.raises(sqlite3.IntegrityError):
        store.save("alice", "chat", "Q1", answer)
    assert store.list("alice") == []
    assert store.db.execute("SELECT COUNT(*) FROM save_keys").fetchone()[0] == 0
    store.db.execute("DROP TRIGGER fail_save")
    first = store.save("alice", "chat", "Q1", answer)
    assert store.save("alice", "chat", "Q1", answer) == first
    assert len(store.list("alice")) == 1
    assert store.db.execute("SELECT COUNT(*) FROM audit WHERE action='save'").fetchone()[0] == 1
