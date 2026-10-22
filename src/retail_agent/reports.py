"""Owner-scoped reports and exact, transactional, single-use hard deletion."""

import hashlib
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from retail_agent.models import Answer, AppError
from retail_agent.privacy import safe_text


@dataclass(frozen=True)
class Report:
    id: str
    title: str
    conversation: str
    created_at: float


@dataclass(frozen=True)
class Preview:
    token: str
    reports: list[Report]
    expires_at: float


class ReportStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, conversation TEXT NOT NULL,
            title TEXT NOT NULL, body TEXT NOT NULL, version TEXT NOT NULL, created REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS pending (
            token_hash TEXT PRIMARY KEY, owner TEXT NOT NULL, conversation TEXT NOT NULL,
            snapshot TEXT NOT NULL, expires REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY, owner TEXT NOT NULL, conversation TEXT NOT NULL,
            body TEXT NOT NULL, created REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY, owner TEXT NOT NULL, action TEXT NOT NULL,
            count INTEGER NOT NULL, created REAL NOT NULL
          );
        """)
        path.chmod(0o600)
        self.cleanup()

    def close(self) -> None:
        self.db.close()

    def cleanup(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.db.execute("DELETE FROM chats WHERE created < ?", (now - 90 * 86400,))
        self.db.execute("DELETE FROM audit WHERE created < ?", (now - 365 * 86400,))
        self.db.execute("DELETE FROM pending WHERE expires < ?", (now,))

    def save(self, owner: str, conversation: str, title: str, answer: Answer) -> str:
        if not answer.evidence:
            raise AppError("There is no successful analysis to save.")
        rid = uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO reports VALUES (?,?,?,?,?,?,?)",
            (
                rid,
                owner,
                conversation,
                safe_text(title, limit=120),
                answer.model_dump_json(),
                uuid4().hex,
                time.time(),
            ),
        )
        self.db.execute(
            "INSERT INTO audit(owner,action,count,created) VALUES (?,?,?,?)",
            (owner, "save", 1, time.time()),
        )
        return rid

    def list(self, owner: str) -> list[Report]:
        return [
            Report(str(r["id"]), str(r["title"]), str(r["conversation"]), float(r["created"]))
            for r in self.db.execute(
                "SELECT * FROM reports WHERE owner=? ORDER BY created,id", (owner,)
            )
        ]

    def read(self, owner: str, report_id: str) -> Answer:
        row = self.db.execute(
            "SELECT body FROM reports WHERE owner=? AND id=?", (owner, report_id)
        ).fetchone()
        if row is None:
            raise AppError("Report not found in your library.")
        return Answer.model_validate_json(row["body"])

    def preview(
        self,
        owner: str,
        conversation: str,
        match: str = "",
        *,
        conversation_only: bool = False,
        now: float | None = None,
    ) -> Preview:
        now = time.time() if now is None else now
        rows = self.db.execute(
            "SELECT * FROM reports WHERE owner=? ORDER BY created,id", (owner,)
        ).fetchall()
        selected = [
            r
            for r in rows
            if (not conversation_only or r["conversation"] == conversation)
            and (not match or match.casefold() in (r["title"] + " " + r["body"]).casefold())
        ]
        if len(selected) > 100:
            raise AppError("More than 100 reports match. Narrow the deletion request.")
        token = secrets.token_urlsafe(18)
        expiry = now + 300
        snapshot = json.dumps({r["id"]: r["version"] for r in selected})
        self.db.execute(
            "DELETE FROM pending WHERE owner=? AND conversation=?", (owner, conversation)
        )
        if selected:
            self.db.execute(
                "INSERT INTO pending VALUES (?,?,?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), owner, conversation, snapshot, expiry),
            )
        return Preview(
            token,
            [Report(r["id"], r["title"], r["conversation"], r["created"]) for r in selected],
            expiry,
        )

    def cancel(self, owner: str, conversation: str) -> None:
        self.db.execute(
            "DELETE FROM pending WHERE owner=? AND conversation=?", (owner, conversation)
        )

    def confirm(
        self, owner: str, conversation: str, token: str, *, now: float | None = None
    ) -> int:
        now = time.time() if now is None else now
        digest = hashlib.sha256(token.encode()).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM pending WHERE token_hash=? AND owner=? AND conversation=?",
                (digest, owner, conversation),
            ).fetchone()
            if row is None or row["expires"] < now:
                raise AppError(
                    "Confirmation is invalid, expired, or already used. Request a new preview."
                )
            snapshot: dict[str, str] = json.loads(row["snapshot"])
            conversations: set[str] = set()
            for rid, version in snapshot.items():
                report = self.db.execute(
                    "SELECT * FROM reports WHERE id=? AND owner=? AND version=?",
                    (rid, owner, version),
                ).fetchone()
                if report is None:
                    raise AppError("The report set changed. Request a new preview.")
                conversations.add(report["conversation"])
            for rid in snapshot:
                self.db.execute("DELETE FROM reports WHERE id=? AND owner=?", (rid, owner))
            # Conservative purge: all persisted chat copies from affected conversations.
            for session in conversations:
                self.db.execute(
                    "DELETE FROM chats WHERE owner=? AND conversation=?", (owner, session)
                )
            self.db.execute("DELETE FROM pending WHERE owner=?", (owner,))
            self.db.execute(
                "INSERT INTO audit(owner,action,count,created) VALUES (?,?,?,?)",
                (owner, "hard_delete", len(snapshot), now),
            )
            self.db.execute("COMMIT")
            return len(snapshot)
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def append_chat(self, owner: str, conversation: str, answer: Answer) -> None:
        self.db.execute(
            "INSERT INTO chats(owner,conversation,body,created) VALUES (?,?,?,?)",
            (owner, conversation, answer.model_dump_json(), time.time()),
        )
