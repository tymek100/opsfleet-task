"""Private report artifacts and user-confirmed, transactional hard deletion.

This service never interprets a request as authorization. Its caller decides
whether a save was explicitly requested; only trusted UI code calls confirmation.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from collections.abc import Callable, Generator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

MAX_ARTIFACT_BYTES = 2_000_000
MAX_IMPORT_BYTES = 32_000_000


class ReportError(ValueError):
    """A sanitized storage/validation error suitable for a tool response."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ReportError("invalid_request", f"A valid {label} is required.")
    if any(ord(char) < 32 for char in value):
        raise ReportError(
            "invalid_request", f"The {label} contains unsupported control characters."
        )


class ReportStore:
    """SQLite artifacts with owner isolation and content-free mutation audit.

    Use a new database for the replacement runtime. Legacy import reads its source
    without modifying it. The caller owns clearing any in-memory report copies
    identified by ``deleted_ids`` after successful confirmation.
    """

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = time.time,
        confirmation_ttl: float = 300,
    ) -> None:
        self.path = Path(path)
        self.clock = clock
        if not 0 < confirmation_ttl <= 3600:
            raise ReportError(
                "invalid_request", "Confirmation lifetime must be positive and bounded."
            )
        self.confirmation_ttl = confirmation_ttl
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA secure_delete=ON")
            self.db.execute("PRAGMA journal_mode=DELETE")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_reports (
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    title TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    answer_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    legacy_json TEXT,
                    UNIQUE(owner, answer_id)
                );
                CREATE INDEX IF NOT EXISTS agent_reports_owner ON agent_reports(owner, created_at);
                CREATE TABLE IF NOT EXISTS report_deletions (
                    token_hash TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    conversation TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    UNIQUE(owner, conversation)
                );
                CREATE TABLE IF NOT EXISTS report_audit (
                    id INTEGER PRIMARY KEY,
                    owner TEXT NOT NULL,
                    action TEXT NOT NULL,
                    record_count INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
            """)
            self.path.chmod(0o600)
            self.prune_audit()
        except (OSError, sqlite3.Error):
            raise ReportError(
                "storage_unavailable", "Could not open private report storage."
            ) from None

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def _transaction(self) -> Generator[None]:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.execute("COMMIT")
        except Exception as exc:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            if isinstance(exc, sqlite3.Error):
                raise ReportError(
                    "storage_failure", "Report storage could not complete the operation."
                ) from None
            raise

    def _audit(self, owner: str, action: str, count: int) -> None:
        self.db.execute(
            "INSERT INTO report_audit(owner,action,record_count,created_at) VALUES (?,?,?,?)",
            (owner, action, count, self.clock()),
        )

    @staticmethod
    def _metadata(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "answer_id": row["answer_id"],
            "version": row["version"],
            "created_at": row["created_at"],
            "historical_import": row["legacy_json"] is not None,
        }

    @classmethod
    def _artifact(cls, row: sqlite3.Row) -> dict[str, Any]:
        artifact = {
            **cls._metadata(row),
            "markdown": row["markdown"],
            "evidence": json.loads(row["evidence_json"]),
        }
        if row["legacy_json"] is not None:
            artifact["legacy_payload"] = json.loads(row["legacy_json"])
            artifact["import_note"] = (
                "Historical artifact imported without re-evaluation. Original structured evidence "
                "is preserved; its source database was not modified."
            )
        return artifact

    def _validate_artifact(
        self, owner: str, title: str, markdown: str, evidence: list[dict[str, Any]], answer_id: str
    ) -> str:
        _identifier(owner, "owner")
        _identifier(answer_id, "answer identifier")
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ReportError("invalid_request", "A report title of 1-200 characters is required.")
        if any(ord(char) < 32 for char in title):
            raise ReportError("invalid_request", "Report titles cannot contain control characters.")
        if not isinstance(markdown, str) or not markdown.strip():
            raise ReportError("invalid_request", "An approved answer is required before saving.")
        if not isinstance(evidence, list) or any(not isinstance(item, dict) for item in evidence):
            raise ReportError("invalid_request", "Evidence must be a list of result artifacts.")
        try:
            encoded = _json(evidence)
        except (TypeError, ValueError):
            raise ReportError(
                "invalid_request", "Evidence must contain finite JSON-compatible values."
            ) from None
        if len(markdown.encode()) + len(encoded.encode()) > MAX_ARTIFACT_BYTES:
            raise ReportError("artifact_too_large", "The report exceeds the bounded storage size.")
        return encoded

    def _insert(
        self,
        owner: str,
        title: str,
        markdown: str,
        evidence_json: str,
        answer_id: str,
        *,
        legacy_json: str | None = None,
        created_at: float | None = None,
    ) -> tuple[sqlite3.Row, bool]:
        previous = self.db.execute(
            "SELECT * FROM agent_reports WHERE owner=? AND answer_id=?", (owner, answer_id)
        ).fetchone()
        if previous is not None:
            if previous["markdown"] != markdown or previous["evidence_json"] != evidence_json:
                raise ReportError(
                    "idempotency_conflict",
                    "This answer identifier already names different saved content.",
                )
            return previous, False
        report_id = uuid4().hex[:16]
        self.db.execute(
            "INSERT INTO agent_reports VALUES (?,?,?,?,?,?,?,?,?)",
            (
                report_id,
                owner,
                title,
                markdown,
                evidence_json,
                answer_id,
                uuid4().hex,
                self.clock() if created_at is None else created_at,
                legacy_json,
            ),
        )
        row = self.db.execute("SELECT * FROM agent_reports WHERE id=?", (report_id,)).fetchone()
        assert row is not None
        return row, True

    def save(
        self, owner: str, title: str, markdown: str, evidence: list[dict[str, Any]], answer_id: str
    ) -> dict[str, Any]:
        """Save the exact approved Markdown, idempotently by owner and answer ID."""
        encoded = self._validate_artifact(owner, title, markdown, evidence, answer_id)
        with self._transaction():
            row, created = self._insert(owner, title, markdown, encoded, answer_id)
            if created:
                self._audit(owner, "save", 1)
            return {"status": "ok", "created": created, **self._artifact(row)}

    def search(self, owner: str, query: str = "") -> list[dict[str, Any]]:
        """Literal case-insensitive search across this owner's titles and Markdown."""
        _identifier(owner, "owner")
        if not isinstance(query, str) or len(query) > 1000:
            raise ReportError("invalid_request", "Search text must be at most 1,000 characters.")
        rows = self.db.execute(
            "SELECT * FROM agent_reports WHERE owner=? ORDER BY created_at DESC,id", (owner,)
        )
        needle = query.casefold()
        return [
            self._metadata(row)
            for row in rows
            if not needle or needle in f"{row['title']}\n{row['markdown']}".casefold()
        ]

    def read(self, owner: str, report_id: str) -> dict[str, Any] | None:
        _identifier(owner, "owner")
        row = self.db.execute(
            "SELECT * FROM agent_reports WHERE owner=? AND id=?", (owner, report_id)
        ).fetchone()
        return self._artifact(row) if row is not None else None

    @staticmethod
    def _record_signature(row: sqlite3.Row) -> str:
        # Also detect accidental out-of-band edits that failed to rotate version.
        return _digest(_json(dict(row)))

    def preview_delete(self, owner: str, conversation: str, query: str) -> dict[str, Any]:
        """Create an exact selection for trusted UI display; this does not delete."""
        _identifier(owner, "owner")
        _identifier(conversation, "conversation")
        if not isinstance(query, str) or len(query) > 1000:
            raise ReportError(
                "invalid_request", "Deletion search must be at most 1,000 characters."
            )
        needle = query.casefold()
        with self._transaction():
            selected = [
                row
                for row in self.db.execute(
                    "SELECT * FROM agent_reports WHERE owner=? ORDER BY created_at,id", (owner,)
                )
                if not needle or needle in f"{row['title']}\n{row['markdown']}".casefold()
            ]
            if len(selected) > 100:
                raise ReportError(
                    "too_many_matches", "More than 100 reports match; narrow the preview."
                )
            self.db.execute(
                "DELETE FROM report_deletions WHERE owner=? AND conversation=?",
                (owner, conversation),
            )
            expiry = self.clock() + self.confirmation_ttl
            token = secrets.token_urlsafe(24) if selected else ""
            if selected:
                snapshot = {
                    row["id"]: {"version": row["version"], "signature": self._record_signature(row)}
                    for row in selected
                }
                self.db.execute(
                    "INSERT INTO report_deletions VALUES (?,?,?,?,?)",
                    (_digest(token), owner, conversation, _json(snapshot), expiry),
                )
            return {
                "status": "confirmation_required" if selected else "empty",
                "token": token,
                "expires_at": expiry,
                "reports": [self._metadata(row) for row in selected],
                "message": "Nothing has been deleted. Confirm the exact displayed selection or cancel.",
            }

    def cancel_delete(self, owner: str, conversation: str) -> dict[str, Any]:
        _identifier(owner, "owner")
        _identifier(conversation, "conversation")
        with self._transaction():
            deleted = self.db.execute(
                "DELETE FROM report_deletions WHERE owner=? AND conversation=?",
                (owner, conversation),
            ).rowcount
        return {"status": "ok", "cancelled": bool(deleted), "deleted_ids": []}

    def confirm_delete(self, owner: str, conversation: str, token: str) -> dict[str, Any]:
        """Trusted UI entry point only. The LLM must never receive this as a tool."""
        _identifier(owner, "owner")
        _identifier(conversation, "conversation")
        if not isinstance(token, str) or len(token) > 256:
            return self._invalid_confirmation()
        with self._transaction():
            pending = self.db.execute(
                "SELECT * FROM report_deletions WHERE token_hash=? AND owner=? AND conversation=?",
                (_digest(token), owner, conversation),
            ).fetchone()
            if pending is None:
                return self._invalid_confirmation()
            if pending["expires_at"] <= self.clock():
                self.db.execute(
                    "DELETE FROM report_deletions WHERE token_hash=?", (_digest(token),)
                )
                return self._invalid_confirmation()
            snapshot = json.loads(pending["snapshot_json"])
            for report_id, expected in snapshot.items():
                row = self.db.execute(
                    "SELECT * FROM agent_reports WHERE owner=? AND id=?", (owner, report_id)
                ).fetchone()
                if (
                    row is None
                    or row["version"] != expected["version"]
                    or self._record_signature(row) != expected["signature"]
                ):
                    self.db.execute(
                        "DELETE FROM report_deletions WHERE token_hash=?", (_digest(token),)
                    )
                    return {
                        "status": "stale_preview",
                        "deleted_ids": [],
                        "message": "The report selection changed. Request a new preview.",
                    }
            self.db.executemany(
                "DELETE FROM agent_reports WHERE owner=? AND id=?",
                [(owner, report_id) for report_id in snapshot],
            )
            # Other previews may refer to the deleted reports; invalidate them too.
            self.db.execute("DELETE FROM report_deletions WHERE owner=?", (owner,))
            self._audit(owner, "hard_delete", len(snapshot))
            return {
                "status": "ok",
                "deleted_ids": list(snapshot),
                "count": len(snapshot),
                "message": "The confirmed reports were permanently deleted from this library.",
            }

    @staticmethod
    def _invalid_confirmation() -> dict[str, Any]:
        return {
            "status": "invalid_confirmation",
            "deleted_ids": [],
            "message": "Confirmation is invalid, expired or already used. Request a new preview.",
        }

    def prune_audit(self) -> None:
        """Expire content-free mutation audit after one year and stale previews."""
        now = self.clock()
        with self._transaction():
            self.db.execute("DELETE FROM report_audit WHERE created_at < ?", (now - 365 * 86400,))
            self.db.execute("DELETE FROM report_deletions WHERE expires_at <= ?", (now,))

    def import_legacy(self, path: Path, owner: str) -> dict[str, Any]:
        """Explicitly import owned historical records; never change the source.

        Reads the old SQLite ``reports.body`` JSON format, or a JSON export whose
        records explicitly identify their owners. The original Answer JSON stays
        attached for historical inspection; its text is not regenerated or marked
        approved by the new evaluator. No anonymous JSON is assigned an owner.
        """
        _identifier(owner, "owner")
        source = Path(path)
        if source.resolve() == self.path.resolve():
            raise ReportError("invalid_import", "Select a separate, read-only legacy source.")
        try:
            if source.stat().st_size > MAX_IMPORT_BYTES:
                raise ReportError(
                    "invalid_import", "The legacy source exceeds the bounded import size."
                )
            with source.open("rb") as handle:
                sqlite_source = handle.read(16) == b"SQLite format 3\x00"
            if sqlite_source:
                uri = source.resolve().as_uri() + "?mode=ro"
                with closing(sqlite3.connect(uri, uri=True)) as legacy_db:
                    legacy_db.execute("PRAGMA query_only=ON")
                    legacy_db.row_factory = sqlite3.Row
                    records = [
                        dict(row)
                        for row in legacy_db.execute(
                            "SELECT id,owner,title,body,version,created,conversation FROM reports WHERE owner=?",
                            (owner,),
                        )
                    ]
            else:
                payload = json.loads(source.read_text())
                records = (
                    payload.get("reports", [payload]) if isinstance(payload, dict) else payload
                )
                if not isinstance(records, list) or any(
                    not isinstance(row, dict) for row in records
                ):
                    raise ReportError(
                        "invalid_import", "Legacy JSON must contain owned report records."
                    )
                records = [row for row in records if row.get("owner") == owner]
            prepared = [self._prepare_legacy(row, owner) for row in records]
        except ReportError:
            raise
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            raise ReportError(
                "invalid_import", "The legacy source could not be read as owned reports."
            ) from None

        imported: list[str] = []
        existing: list[str] = []
        with self._transaction():
            for record in prepared:
                row, created = self._insert(owner, **record)
                (imported if created else existing).append(row["id"])
            if imported:
                self._audit(owner, "legacy_import", len(imported))
        return {
            "status": "ok",
            "imported_ids": imported,
            "existing_ids": existing,
            "source_modified": False,
            "message": "Historical reports imported without re-evaluation. The source remains unchanged.",
        }

    def _prepare_legacy(self, record: dict[str, Any], owner: str) -> dict[str, Any]:
        payload = record.get("body", record.get("answer"))
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            raise ReportError("invalid_import", "A legacy report does not contain an answer text.")
        original_id = str(record["id"])
        title = record["title"]
        markdown = payload["text"]
        evidence = payload.get("query_evidence") or payload.get("evidence") or []
        original = {
            "report_id": original_id,
            "version": record.get("version"),
            "conversation": record.get("conversation"),
            "answer": payload,
        }
        encoded_original = _json(original)
        if len(encoded_original.encode()) > MAX_ARTIFACT_BYTES:
            raise ReportError(
                "invalid_import", "A legacy report exceeds the bounded artifact size."
            )
        answer_id = "legacy:" + _digest(encoded_original)
        encoded_evidence = self._validate_artifact(owner, title, markdown, evidence, answer_id)
        return {
            "title": title,
            "markdown": markdown,
            "evidence_json": encoded_evidence,
            "answer_id": answer_id,
            "legacy_json": encoded_original,
            "created_at": float(record.get("created", self.clock())),
        }
