"""Per-question state and shared boundaries for every analyst tool."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from typing import TYPE_CHECKING

from retail_agent.budget import LimitReached
from retail_agent.contracts import Answer

if TYPE_CHECKING:
    from retail_agent.runtime import Analyst


class Turn:
    def __init__(self, app: Analyst, question: str):
        self.app, self.question = app, question
        self.budget = app.new_budget()
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
        self._observed_tools: str | None = None

    def emit(self, event: str, **fields) -> None:
        record = {
            "event": event,
            "elapsed": round(time.monotonic() - self.budget.started, 3),
            **fields,
        }
        self.trace.append(record)
        self.app.progress(record)
        self.app.observe(event, **{key: value for key, value in record.items() if key != "event"})

    def observe_request(self, callback_context, llm_request):
        if self.app.observation_mode == "synthetic":
            tools = [
                declaration.model_dump(mode="json", exclude_none=True)
                for tool in (llm_request.config.tools or [])
                for declaration in (tool.function_declarations or [])
            ]
            fingerprint = hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest()
            if fingerprint != self._observed_tools:
                self.app.observe("available_tools", available_tools=tools)
                self._observed_tools = fingerprint
        return None

    def observe_model(self, callback_context, llm_response):
        calls = (
            [p.function_call for p in (llm_response.content.parts or []) if p.function_call]
            if llm_response.content
            else []
        )
        for call in calls:
            self.app.observe("tool_call", name=call.name, args=call.args or {}, call_id=call.id)
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
            self.app.screen(json.dumps(result, default=str))
            result.setdefault("status", "ok")
            if result["status"] not in ("ok", "empty"):
                self.failed_actions[digest] = self.failed_actions.get(digest, 0) + 1
            self.emit("tool_end", tool=name, status=result["status"], evidence_id=result.get("id"))
            self.app.observe("tool_observation", name=name, result=result)
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
            result = {"status": code, "message": message}
            self.app.observe("tool_observation", name=name, result=result)
            return result
        finally:
            self.active -= 1

    def artifact(self, result: dict, purpose: str, parents: list[str] | None = None) -> dict:
        self.app.screen(purpose)
        self.app.screen(json.dumps(result, default=str))
        self.app._result_counter += 1
        key = f"E{self.app._result_counter}"
        artifact = {
            **result,
            "id": key,
            "purpose": purpose,
            "scope": self.app.identity.scope,
            "queried_at": self.app.now().isoformat(),
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
