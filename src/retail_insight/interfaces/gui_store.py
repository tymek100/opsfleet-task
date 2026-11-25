"""Browser-owned conversation presentation state, isolated by agent and data profile."""

import json
import sqlite3
import uuid
from pathlib import Path

from retail_insight.integrations.maps.privacy import contains_maps


class ConversationStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, role TEXT NOT NULL,
            profile TEXT NOT NULL, title TEXT NOT NULL, updated INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS messages (
            conversation TEXT NOT NULL, id TEXT NOT NULL, parent TEXT, value TEXT NOT NULL,
            PRIMARY KEY (conversation, id)
        );
        """)

    def create(self, owner: str, role: str, profile: str) -> dict:
        identifier = uuid.uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, 'New conversation', unixepoch())",
                (identifier, owner, role, profile),
            )
        return {"id": identifier, "role": role, "title": "New conversation"}

    def owned(self, identifier: str, owner: str, profile: str, role: str | None = None) -> bool:
        row = self.db.execute(
            "SELECT role FROM conversations WHERE id=? AND owner=? AND profile=?",
            (identifier, owner, profile),
        ).fetchone()
        return bool(row and (role is None or row[0] == role))

    def list(self, owner: str, profile: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT id,role,title FROM conversations WHERE owner=? AND profile=? ORDER BY updated DESC,rowid DESC",
            (owner, profile),
        ).fetchall()
        return [dict(zip(("id", "role", "title"), row, strict=True)) for row in rows]

    def load(self, identifier: str) -> dict:
        rows = self.db.execute(
            "SELECT parent,value FROM messages WHERE conversation=? ORDER BY rowid", (identifier,)
        ).fetchall()
        messages = [{"parentId": parent, "message": json.loads(value)} for parent, value in rows]
        parents = {entry["parentId"] for entry in messages}
        leaves = [entry for entry in messages if entry["message"]["id"] not in parents]
        return {"messages": messages, "headId": leaves[-1]["message"]["id"] if leaves else None}

    def append(self, identifier: str, entry: dict) -> None:
        message = entry["message"]
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
            raise ValueError("Invalid message")
        message_id = message.get("id")
        if not isinstance(message_id, str) or not 1 <= len(message_id) <= 128:
            raise ValueError("Invalid message ID")
        parent = entry.get("parentId")
        if parent is not None and (not isinstance(parent, str) or not 1 <= len(parent) <= 128):
            raise ValueError("Invalid parent message ID")
        if contains_maps(message):
            message = {
                **message,
                "content": [
                    {
                        "type": "text",
                        "text": "This answer used ephemeral Maps content and was not stored. Ask for a fresh lookup.",
                    }
                ],
                "metadata": {"custom": {}, "unstable_data": [], "unstable_annotations": []},
            }
        with self.db:
            self.db.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?) ON CONFLICT(conversation,id) DO UPDATE SET value=excluded.value",
                (identifier, message_id, entry.get("parentId"), json.dumps(message)),
            )
            if message["role"] == "user":
                title = " ".join(
                    part.get("text", "")
                    for part in message.get("content", [])
                    if isinstance(part, dict) and part.get("type") == "text"
                ).strip()[:90]
                self.db.execute(
                    "UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",
                    (title or "New conversation", identifier),
                )
            self.db.execute(
                "UPDATE conversations SET updated=unixepoch() WHERE id=?", (identifier,)
            )

    def delete(self, identifier: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM messages WHERE conversation=?", (identifier,))
            self.db.execute("DELETE FROM conversations WHERE id=?", (identifier,))
