"""Per-service durable ownership, A2A task and conversation state."""

import json
import sqlite3
from pathlib import Path

from a2a.server.tasks import TaskStore
from a2a.types import ListTasksRequest, ListTasksResponse, Task
from a2a.utils.errors import InvalidParamsError
from google.protobuf.json_format import MessageToDict, Parse

from retail_insight.integrations.maps.privacy import contains_maps, persistent_result


class Store(TaskStore):
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS contexts (id TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, owner TEXT NOT NULL, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, owner TEXT NOT NULL, digest TEXT NOT NULL, result TEXT, budget TEXT);
        """)

    def context(self, context_id: str, owner: str) -> dict:
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO contexts VALUES (?, ?, '{}')", (context_id, owner)
            )
            stored = self.db.execute(
                "SELECT owner,state FROM contexts WHERE id=?", (context_id,)
            ).fetchone()
        if stored[0] != owner:
            raise PermissionError("Conversation belongs to another identity")
        return json.loads(stored[1])

    def save_context(self, context_id: str, owner: str, state: dict) -> None:
        with self.db:
            self.db.execute(
                "UPDATE contexts SET state=? WHERE id=? AND owner=?",
                (json.dumps(state, default=str), context_id, owner),
            )

    def claim(self, request_id: str, owner: str, digest: str) -> dict | None:
        with self.db:
            row = self.db.execute(
                "SELECT owner,digest,result FROM requests WHERE id=?", (request_id,)
            ).fetchone()
            if row:
                if row[0] != owner or row[1] != digest:
                    raise PermissionError("Request ID conflicts with an existing request")
                if row[2] is None:
                    raise RuntimeError(
                        "Request is running or was interrupted; automatic replay is disabled"
                    )
                return json.loads(row[2])
            self.db.execute(
                "INSERT INTO requests VALUES (?, ?, ?, NULL, '{}')", (request_id, owner, digest)
            )
        return None

    def budget(self, request_id: str, snapshot: dict):
        with self.db:
            self.db.execute(
                "UPDATE requests SET budget=? WHERE id=?", (json.dumps(snapshot), request_id)
            )

    def finish(self, request_id: str, result: dict):
        with self.db:
            self.db.execute(
                "UPDATE requests SET result=? WHERE id=?",
                (json.dumps(result, default=str), request_id),
            )

    async def save(self, task: Task, context=None) -> None:
        owner = (
            context.state["principal"].identity
            if context
            else self.db.execute(
                "SELECT owner FROM contexts WHERE id=?", (task.context_id,)
            ).fetchone()[0]
        )
        self.context(task.context_id, owner)
        serialized = MessageToDict(task)
        if contains_maps(serialized):
            redacted = {"text": "Ephemeral Maps-derived answer; request a fresh lookup."}
            status_message = serialized.get("status", {}).get("message")
            if status_message:
                status_message["parts"] = [redacted]
            for message in serialized.get("history", []):
                if message.get("role") == "ROLE_AGENT":
                    message["parts"] = [redacted]
            for artifact in serialized.get("artifacts", []):
                for part in artifact.get("parts", []):
                    if "data" in part:
                        part["data"] = persistent_result(part["data"])
                    if "text" in part:
                        part["text"] = "Ephemeral Maps-derived answer; request a fresh lookup."
        with self.db:
            self.db.execute(
                "INSERT INTO tasks VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                (task.id, owner, json.dumps(serialized)),
            )

    async def get(self, task_id: str, context=None) -> Task | None:
        row = self.db.execute("SELECT owner,value FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        if context and row[0] != context.state["principal"].identity:
            return None
        return self.decode_task(row[1])

    @staticmethod
    def decode_task(value: str) -> Task:
        """Read old rows without rewriting or deleting the original persisted data."""
        if json.loads(value).get("kind") == "task":
            from a2a.compat.v0_3.conversions import to_core_task
            from a2a.compat.v0_3.types import Task as LegacyTask

            return to_core_task(LegacyTask.model_validate_json(value))
        return Parse(value, Task())

    async def list(self, params: ListTasksRequest, context) -> ListTasksResponse:
        owner = context.state["principal"].identity
        try:
            offset = int(params.page_token or "0")
            if offset < 0:
                raise ValueError
        except ValueError as exc:
            raise InvalidParamsError(message="Invalid page token") from exc
        size = min(params.page_size or 50, 100)
        if size < 1:
            raise InvalidParamsError(message="Invalid page size")
        rows = self.db.execute(
            "SELECT value FROM tasks WHERE owner=? ORDER BY rowid DESC", (owner,)
        ).fetchall()
        tasks = []
        for (value,) in rows:
            task = self.decode_task(value)
            if params.context_id and task.context_id != params.context_id:
                continue
            if params.status and task.status.state != params.status:
                continue
            if params.HasField("status_timestamp_after") and (
                not task.status.HasField("timestamp")
                or task.status.timestamp.ToNanoseconds()
                <= params.status_timestamp_after.ToNanoseconds()
            ):
                continue
            tasks.append(task)
        page = tasks[offset : offset + size]
        for task in page:
            if not params.include_artifacts:
                task.ClearField("artifacts")
            if params.history_length:
                del task.history[: -params.history_length]
            else:
                task.ClearField("history")
        return ListTasksResponse(
            tasks=page,
            page_size=size,
            total_size=len(tasks),
            next_page_token=str(offset + size) if offset + size < len(tasks) else "",
        )

    async def delete(self, task_id: str, context=None) -> None:
        if await self.get(task_id, context):
            with self.db:
                self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
