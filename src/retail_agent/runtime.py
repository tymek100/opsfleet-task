"""One ADK analyst conversation, composable tools and reviewed completion."""

import asyncio
import hashlib
import inspect
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.genai import types

from retail_agent.budget import Budget, LimitReached
from retail_agent.config import Settings
from retail_agent.contracts import Answer, Identity, TurnResult
from retail_agent.data import QueryGateway, analyze_results
from retail_agent.knowledge import GoldenStore
from retail_agent.privacy import screen
from retail_agent.provider import AccountedModel, ProviderUnavailable, make_gemini
from retail_agent.reports import ReportStore
from retail_agent.reviewer import evaluate


class Analyst:
    def __init__(
        self,
        settings: Settings,
        identity: Identity,
        *,
        model: BaseLlm | None = None,
        reviewer_model: BaseLlm | None = None,
        gateway=None,
        reports=None,
        progress=None,
    ):
        self.settings, self.identity = settings, identity
        # Framework exception logs can contain generated arguments. Emit our metadata instead.
        logging.getLogger("google_adk").setLevel(logging.CRITICAL)
        self.model = model
        self.reviewer_model = reviewer_model
        self.gateway = gateway or QueryGateway(
            brands=identity.brands,
            project=settings.google_cloud_project,
            backend=settings.backend,
            fixture_path=settings.fixture_path,
            max_bytes=settings.max_query_bytes,
        )
        self.knowledge = GoldenStore(
            settings.golden_path, identity.brands, bootstrap=settings.golden_bootstrap
        )
        self.reports = reports or ReportStore(settings.data_dir / "reports-v2.sqlite3")
        self.progress = progress or (lambda event: None)
        self.conversation_id = uuid.uuid4().hex[:12]
        self.results: dict[str, dict] = {}
        self.answers: dict[str, Answer] = {}
        self.history: list[dict] = []
        self.last_result: TurnResult | None = None
        self._result_counter = 0

    async def ask(self, question: str) -> TurnResult:
        started = time.monotonic()
        try:
            question = screen(question.strip())
            if not question or len(question) > 6000:
                raise ValueError("Ask a question containing 1-6,000 characters.")
        except ValueError as exc:
            return TurnResult(None, "input_rejected", str(exc), [], {}, [], 0)
        # Approved context is bounded and ephemeral. No raw ADK reasoning is persisted.
        cutoff = time.time() - 90 * 86400
        self.history = [h for h in self.history if h["timestamp"] >= cutoff][-6:]
        begin_turn = getattr(self.gateway, "begin_turn", None)
        if begin_turn:
            begin_turn()
        turn = _Turn(self, question)
        status, message = "incomplete", "The analyst could not complete a reviewed answer."
        runner = None
        try:
            if self.model is None:
                self.model = make_gemini(self.settings)
            async with asyncio.timeout(self.settings.turn_timeout_seconds):
                agent = LlmAgent(
                    name="retail_analyst",
                    model=AccountedModel(model=self.model.model, delegate=self.model).bind(
                        turn.budget, turn.emit
                    ),
                    instruction=(Path(__file__).parent / "prompts/analyst.md").read_text(),
                    tools=turn.tools(),
                    after_model_callback=turn.observe_model,
                    generate_content_config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=self.settings.max_output_tokens,
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel(self.settings.thinking_level)
                        ),
                    ),
                )
                sessions = InMemorySessionService()
                session = await sessions.create_session(
                    app_name="retail", user_id=self.identity.user_id
                )
                runner = Runner(app_name="retail", agent=agent, session_service=sessions)
                context = {
                    "trusted_scope": self.identity.scope,
                    "today_utc": datetime.now(UTC).date().isoformat(),
                    "prior_approved_conversation": self.context_history(),
                    "available_results": self.result_manifest(),
                    "user_question": question,
                }
                prompt = json.dumps(context, ensure_ascii=False)
                # Only a bounded protocol correction; business actions loop inside ADK.
                for attempt in range(2):
                    async for _ in runner.run_async(
                        user_id=self.identity.user_id,
                        session_id=session.id,
                        new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
                        run_config=RunConfig(max_llm_calls=self.settings.max_model_calls),
                    ):
                        pass
                    if turn.answer or turn.stopped:
                        break
                    turn.emit("completion_protocol_repair", attempt=attempt + 1)
                    prompt = "Your draft was not published. Submit the complete answer through finish_answer with its evidence IDs."
                if turn.answer:
                    status, message = "approved", ""
                elif turn.stopped:
                    message = "The evaluator could not approve a supported answer within this investigation."
        except (TimeoutError, LimitReached) as exc:
            code = exc.code if isinstance(exc, LimitReached) else "deadline"
            turn.emit("limit_reached", code=code)
            status = code
            message = "This investigation reached its shared limit before a reviewed answer was ready. Try a narrower question; /details shows completed queries."
        except asyncio.CancelledError:
            turn.emit("cancelled")
            raise
        except (ProviderUnavailable, ValueError) as exc:
            status = "unavailable"
            message = (
                str(exc)
                if isinstance(exc, ProviderUnavailable)
                else "The request could not pass its data or model boundary checks."
            )
            turn.emit("failure", code=type(exc).__name__)
        except Exception as exc:
            status = "failed"
            message = "The investigation encountered an error. No unreviewed answer was published."
            turn.emit("failure", code=type(exc).__name__)
        finally:
            if runner is not None:
                try:
                    async with asyncio.timeout(2):
                        await runner.close()
                except Exception:
                    turn.emit("cleanup_incomplete")
        if turn.answer:
            self.answers[turn.answer.id] = turn.answer
            self.history.append(
                {
                    "question": question,
                    "answer_id": turn.answer.id,
                    "markdown": turn.answer.markdown,
                    "evidence_ids": turn.answer.evidence_ids,
                    "timestamp": time.time(),
                }
            )
        result = TurnResult(
            turn.answer,
            status,
            message,
            turn.trace,
            turn.budget.snapshot(),
            [self.results[i] for i in turn.new_results],
            round(time.monotonic() - started, 3),
            turn.deletion_preview,
        )
        self.last_result = result
        try:
            self._write_trace(result)
        except OSError:
            turn.emit("trace_write_failed")
        return result

    def context_history(self) -> list[dict]:
        """Bound context without pretending excerpts are complete prior answers."""
        selected = []
        allowance = min(16_000, self.settings.max_review_bytes // 3)
        for record in reversed(self.history):
            entry = dict(record)
            if len(entry["markdown"].encode()) > 4000:
                entry["markdown"] = entry["markdown"].encode()[:4000].decode(errors="ignore")
                entry["excerpt_only"] = True
            if len(json.dumps([entry, *selected]).encode()) > allowance:
                break
            selected.append(entry)
        return list(reversed(selected))

    def result_manifest(self) -> list[dict]:
        return [
            {
                "id": k,
                "purpose": v.get("purpose", ""),
                "columns": v.get("columns"),
                "stored_rows": len(v.get("rows", [])),
                "truncated": v.get("truncated", False),
            }
            for k, v in list(self.results.items())[-30:]
        ]

    def _write_trace(self, result: TurnResult) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        with (self.settings.data_dir / "events-v2.jsonl").open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "conversation": self.conversation_id,
                        "status": result.status,
                        "elapsed_seconds": result.elapsed_seconds,
                        "usage": result.usage,
                        "events": result.trace,
                    }
                )
                + "\n"
            )

    def clear_context(self) -> None:
        self.results.clear()
        self.answers.clear()
        self.history.clear()
        self.last_result = None

    def confirm_delete(self, token: str) -> dict:
        receipt = self.reports.confirm_delete(self.identity.user_id, self.conversation_id, token)
        if receipt.get("deleted_ids"):
            self.clear_context()
        return receipt


class _Turn:
    def __init__(self, app: Analyst, question: str):
        self.app, self.question = app, question
        self.budget = Budget(app.settings)
        self.trace: list[dict] = []
        self.answer: Answer | None = None
        self.new_results: list[str] = []
        self.retrieved: list[dict] = []
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

    def tools(self) -> list:
        return [
            self.describe_data,
            self.search_golden,
            self.read_golden,
            self.query_data,
            self.read_result,
            self.analyze_results,
            self.query_state_summary,
            self.search_reports,
            self.read_report,
            self.read_answer,
            self.stage_report_save,
            self.preview_report_deletion,
            self.cancel_report_deletion,
            self.finish_answer,
        ]

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

    async def describe_data(self, topic_or_relations: str = "") -> dict:
        """Discover authorized relations, columns, joins and adjustable metric definitions."""
        return await self.run_tool(
            "describe_data", lambda: self.app.gateway.describe_data(topic_or_relations)
        )

    async def search_golden(self, query: str, limit: int = 3) -> dict:
        """Find relevant eligible analytical methods. Examples are not current evidence."""
        return await self.run_tool(
            "search_golden", lambda: self.app.knowledge.search(query, limit), query
        )

    async def read_golden(self, example_id: str) -> dict:
        """Read an eligible example's SQL and answer to adapt or ignore. Query fresh numbers."""

        def read():
            result = self.app.knowledge.read(example_id)
            example = result.get("example", {})
            if result.get("status") == "ok" and example:
                metadata = {"id": example["id"], "revision": example["revision"]}
                self.retrieved.append(metadata)
                self.emit("golden_read", **metadata)
            return result

        return await self.run_tool("read_golden", read, example_id)

    async def query_data(self, sql: str, purpose: str, parameters_json: str = "{}") -> dict:
        """Execute read-only BigQuery SQL over sales, transactions or products; return evidence."""

        async def query():
            parameters = json.loads(parameters_json)
            if not isinstance(parameters, dict):
                raise ValueError("Parameters must be an object")
            self.budget.query()
            result = await self.app.gateway.query(
                sql, parameters, timeout=min(40, self.budget.work_remaining())
            )
            return self.artifact(result, purpose)

        return await self.run_tool("query_data", query, sql + parameters_json)

    async def read_result(self, result_id: str, offset: int = 0, limit: int = 20) -> dict:
        """Read a bounded page of stored evidence. Beyond stored rows, query a smaller result."""

        def read():
            if offset < 0 or not 1 <= limit <= 100:
                raise ValueError("Invalid page")
            result = self.app.results[result_id]
            rows = result.get("rows", [])
            return self.artifact(
                {
                    **result,
                    "rows": rows[offset : offset + limit],
                    "parent_total_rows": result.get("total_rows"),
                    "page_offset": offset,
                    "stored_rows_in_parent": len(rows),
                },
                f"Page of {result_id}",
                [result_id],
            )

        return await self.run_tool("read_result", read, f"{result_id}:{offset}:{limit}")

    async def analyze_results(self, result_ids: list[str], sql: str, purpose: str) -> dict:
        """Analyze stored evidence with SQL; table names are result IDs such as E1. No external IO."""

        async def analyze():
            parents = {i: self.app.results[i] for i in result_ids}
            result = await analyze_results(
                parents, sql, timeout=min(5, self.budget.work_remaining())
            )
            return self.artifact(result, purpose, result_ids)

        return await self.run_tool("analyze_results", analyze, sql)

    async def query_state_summary(
        self, start: str, end: str, status_definition: str = "qualifying"
    ) -> dict:
        """Get privacy-filtered state aggregates; never individual customer geography."""

        async def query():
            self.budget.query()
            result = await self.app.gateway.state_summary(
                start, end, status_definition, timeout=min(40, self.budget.work_remaining())
            )
            return self.artifact(result, "State aggregates")

        return await self.run_tool("query_state_summary", query, start + end + status_definition)

    async def search_reports(self, query: str = "") -> dict:
        """Find reports in the current owner's private library by literal text."""
        return await self.run_tool(
            "search_reports",
            lambda: {"reports": self.app.reports.search(self.app.identity.user_id, query)},
            query,
        )

    async def read_report(self, report_id: str) -> dict:
        """Read an owned saved report. Its data is historical, not current warehouse evidence."""

        def read():
            report = self.app.reports.read(self.app.identity.user_id, report_id)
            if not report:
                return {"status": "empty", "message": "Report not found in your library."}
            registered = [
                self.artifact(e, "Historical saved report evidence")
                for e in report.get("evidence", [])
            ]
            return {
                "report": {
                    k: v for k, v in report.items() if k not in ("evidence", "legacy_payload")
                },
                "historical": True,
                "evidence": registered,
            }

        return await self.run_tool("read_report", read, report_id)

    async def read_answer(self, answer_id: str) -> dict:
        """Read an exact prior approved answer when the conversation contains only an excerpt."""

        def read():
            answer = self.app.answers.get(answer_id)
            if answer is None:
                return {"status": "empty", "message": "No such answer in this conversation."}
            return {
                "id": answer.id,
                "markdown": answer.markdown,
                "evidence_ids": answer.evidence_ids,
                "historical": True,
            }

        return await self.run_tool("read_answer", read, answer_id)

    async def stage_report_save(self, title: str, target_answer_id: str = "current") -> dict:
        """Propose saving an answer only on an explicit current user request. Does not commit."""

        def stage():
            screen(title)
            if target_answer_id != "current" and target_answer_id not in self.app.answers:
                return {"status": "invalid_request", "message": "Unknown approved answer ID."}
            self.pending_save = {"title": title, "target_answer_id": target_answer_id}
            return {"status": "ok", "pending_save": self.pending_save, "saved": False}

        return await self.run_tool("stage_report_save", stage, title + target_answer_id)

    async def preview_report_deletion(self, query: str) -> dict:
        """Prepare exact owner-scoped deletion preview. The application asks the user to confirm."""

        def preview():
            self.deletion_preview = self.app.reports.preview_delete(
                self.app.identity.user_id, self.app.conversation_id, query
            )
            return {k: v for k, v in self.deletion_preview.items() if k != "token"}

        return await self.run_tool("preview_report_deletion", preview, query)

    async def cancel_report_deletion(self) -> dict:
        """Cancel the current pending deletion without deleting reports."""
        return await self.run_tool(
            "cancel_report_deletion",
            lambda: self.app.reports.cancel_delete(
                self.app.identity.user_id, self.app.conversation_id
            ),
        )

    async def finish_answer(
        self, markdown: str, evidence_ids: list[str], outcome: str, tool_context: ToolContext
    ) -> dict:
        """Submit your complete Markdown for review. Outcome: answer, clarification, refusal, partial."""
        self.budget.tool(completion=True)
        if self.finish_conflict or self.active:
            return {
                "status": "invalid_request",
                "message": "Submit finish_answer alone after observing other tool results.",
            }
        if self.answer or self.stopped:
            tool_context.actions.skip_summarization = True
            return {"status": "closed"}
        if outcome not in ("answer", "clarification", "refusal", "partial") or not markdown.strip():
            return {
                "status": "invalid_request",
                "message": "Provide nonempty Markdown and a supported outcome.",
            }
        try:
            screen(markdown)
        except ValueError:
            return {"status": "denied", "message": "Remove personal contact information."}
        if any(i not in self.app.results for i in evidence_ids):
            return {"status": "invalid_request", "message": "Use only actual evidence IDs."}
        fingerprint = hashlib.sha256(
            json.dumps([markdown, evidence_ids, self.pending_save]).encode()
        ).hexdigest()
        if fingerprint in self.candidates:
            return {
                "status": "revise",
                "message": "This unchanged candidate was already reviewed. Address the issues or narrow the answer.",
            }
        if self.reviews >= self.app.settings.max_answer_reviews:
            raise LimitReached("review_attempts")
        self.candidates.add(fingerprint)
        self.reviews += 1
        evidence = [self.app.results[i] for i in dict.fromkeys(evidence_ids)]
        target = (
            self.app.answers.get(self.pending_save["target_answer_id"])
            if self.pending_save
            else None
        )
        payload = {
            "question": self.question,
            "scope": self.app.identity.scope,
            "conversation": self.app.context_history(),
            "candidate": {"markdown": markdown, "outcome": outcome},
            "evidence": evidence,
            "other_results_manifest": self.app.result_manifest(),
            "retrieved_methods": self.retrieved,
            "pending_save": self.pending_save,
            "save_target": {"id": target.id, "markdown": target.markdown} if target else None,
        }
        self.emit("review_start", attempt=self.reviews)
        review_model = self.app.reviewer_model or self.app.model
        if review_model is None:
            raise ProviderUnavailable("The evaluator model is not configured.")
        review = await evaluate(
            payload,
            review_model,
            self.budget,
            self.app.settings,
            self.emit,
        )
        self.emit(
            "review_end",
            decision=review.decision,
            issue_categories=[i.category for i in review.issues],
        )
        if review.decision == "stop":
            self.stopped = True
            tool_context.actions.skip_summarization = True
            return {"status": "stopped"}
        if self.pending_save and not review.save_authorized:
            self.pending_save = None
            return {
                "status": "revise",
                "issues": [
                    "Save was not authorized by the user's request. The proposed save is cancelled. Correct any claim that it was saved."
                ],
            }
        if review.decision == "revise":
            return {"status": "revise", "issues": [i.model_dump() for i in review.issues]}
        tool_context.actions.skip_summarization = True
        answer = Answer(
            f"A{uuid.uuid4().hex[:10]}", markdown, list(dict.fromkeys(evidence_ids)), outcome, True
        )
        if self.pending_save:
            saved_answer = target or answer
            try:
                receipt = self.app.reports.save(
                    self.app.identity.user_id,
                    self.pending_save["title"],
                    saved_answer.markdown,
                    [self.app.results[i] for i in saved_answer.evidence_ids],
                    saved_answer.id,
                )
                answer.receipts.append(
                    {
                        "operation": "save",
                        "status": "saved",
                        "id": receipt["id"],
                        "title": receipt["title"],
                    }
                )
            except Exception:
                answer.receipts.append(
                    {
                        "operation": "save",
                        "status": "failed",
                        "message": "The answer was approved, but the report could not be saved.",
                    }
                )
        self.answer = answer
        self.emit(
            "answer_approved",
            answer_id=answer.id,
            sha256=hashlib.sha256(markdown.encode()).hexdigest(),
        )
        return {"status": "approved", "answer_id": answer.id}
