"""Per-question state and shared boundaries for every analyst tool."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from retail_agent.budget import Budget, LimitReached
from retail_agent.contracts import Answer
from retail_agent.privacy import screen

if TYPE_CHECKING:
    from retail_agent.runtime import Analyst


class Turn:
    def __init__(self, app: Analyst, question: str):
        self.app, self.question = app, question
        self.budget = Budget(app.settings)
        self.trace: list[dict] = []
        self.answer: Answer | None = None
        self.new_results: list[str] = []
        self.retrieved: list[dict] = []
        self.loaded_skills: dict[str, dict] = {}
        self.pending_save: dict | None = None
        self.deletion_preview: dict | None = None
        self.reviews = 0
        self.stopped = False
        self.finish_conflict = False
        self.active = 0
        self.failed_actions: dict[str, int] = {}
        self.candidates: set[str] = set()

    def emit(self, event: str, **fields) -> None:
        record = {
            "event": event,
            "elapsed": round(time.monotonic() - self.budget.started, 3),
            **fields,
        }
        self.trace.append(record)
        self.app.progress(record)

    def observe_model(self, callback_context, llm_response):
        calls = (
            [p.function_call for p in (llm_response.content.parts or []) if p.function_call]
            if llm_response.content
            else []
        )
        self.finish_conflict = len(calls) > 1 and any(c.name == "finish_answer" for c in calls)
        return None

    async def run_tool(self, name: str, action, key: str = "") -> dict:
        self.budget.tool()
        if self.answer or self.stopped:
            return {"status": "denied", "message": "This turn is closed."}
        digest = hashlib.sha256((name + key).encode()).hexdigest()
        if self.failed_actions.get(digest, 0) >= 2:
            return {
                "status": "invalid_request",
                "message": "This action failed repeatedly. Change the action or finish with the limitation.",
            }
        self.active += 1
        self.emit("tool_start", tool=name)
        try:
            result = action()
            if inspect.isawaitable(result):
                result = await result
            screen(json.dumps(result, default=str))
            result.setdefault("status", "ok")
            if result["status"] not in ("ok", "empty"):
                self.failed_actions[digest] = self.failed_actions.get(digest, 0) + 1
            self.emit("tool_end", tool=name, status=result["status"], evidence_id=result.get("id"))
            return result
        except (LimitReached, asyncio.CancelledError, TimeoutError):
            raise
        except Exception as exc:
            self.failed_actions[digest] = self.failed_actions.get(digest, 0) + 1
            code = getattr(exc, "code", "invalid_request")
            self.emit("tool_end", tool=name, status=code)
            # Data/store errors have deliberately safe messages; no SDK exception is exposed.
            message = (
                str(exc)
                if hasattr(exc, "code")
                else "The tool could not process these arguments. Try a corrected request."
            )
            return {"status": code, "message": message}
        finally:
            self.active -= 1

    def artifact(self, result: dict, purpose: str, parents: list[str] | None = None) -> dict:
        screen(purpose)
        screen(json.dumps(result, default=str))
        self.app._result_counter += 1
        key = f"E{self.app._result_counter}"
        artifact = {
            **result,
            "id": key,
            "purpose": purpose,
            "scope": self.app.identity.scope,
            "queried_at": datetime.now(UTC).isoformat(),
            "parents": parents or [],
        }
        self.app.results[key] = artifact
        self.new_results.append(key)
        rows = artifact.get("rows", [])
        return {
            **artifact,
            "rows": rows[:20],
            "preview_only": len(rows) > 20,
            "stored_rows": len(rows),
        }
