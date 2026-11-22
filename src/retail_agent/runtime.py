"""One ADK analyst conversation, composable tools and reviewed completion."""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from retail_agent.budget import LimitReached
from retail_agent.config import Settings
from retail_agent.contracts import Answer, Identity, TurnResult
from retail_agent.observability import CaptureMode, Observer, observation, record_observation, span
from retail_agent.privacy import screen
from retail_agent.provider import AccountedModel, ProviderUnavailable, make_gemini
from retail_agent.services.golden import GoldenStore
from retail_agent.services.reports import ReportStore
from retail_agent.services.warehouse import QueryGateway
from retail_agent.skills import SkillCatalog
from retail_agent.tools import build_tools
from retail_agent.turn import Turn


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
        clock: Callable[[], datetime] | None = None,
        observer: Observer | None = None,
        observation_mode: CaptureMode = "metadata",
    ):
        self.settings, self.identity = settings, identity
        if observation_mode not in ("metadata", "synthetic"):
            raise ValueError("Capture mode must be metadata or synthetic")
        self.clock = clock or (lambda: datetime.now(UTC))
        self.observer = observer
        self.observation_mode: CaptureMode = observation_mode
        self.observer_errors = 0
        self.turn_id = ""
        self._trace_ids: dict[str, str] = {}
        # Framework exception logs can contain generated arguments. Emit our metadata instead.
        logging.getLogger("google_adk").setLevel(logging.CRITICAL)
        self.model = model
        self.reviewer_model = reviewer_model
        self.skills = SkillCatalog()
        self.gateway = gateway or QueryGateway(
            brands=identity.brands,
            project=settings.google_cloud_project,
            backend=settings.backend,
            fixture_path=settings.fixture_path,
            max_bytes=settings.max_query_bytes,
            source_dataset=settings.warehouse_source_dataset,
            clock=clock,
        )
        self.knowledge = GoldenStore(
            settings.golden_path, identity.brands, bootstrap=settings.golden_bootstrap
        )
        self.reports = reports or ReportStore(
            settings.data_dir / "reports-v2.sqlite3", clock=lambda: self.now().timestamp()
        )
        self.progress = progress or (lambda event: None)
        self.conversation_id = uuid.uuid4().hex[:12]
        self.results: dict[str, dict] = {}
        self.answers: dict[str, Answer] = {}
        self.history: list[dict] = []
        self.last_result: TurnResult | None = None
        self._result_counter = 0

    async def ask(self, question: str) -> TurnResult:
        self.turn_id = uuid.uuid4().hex
        self.observer_errors = 0
        with span(
            "retail.prompt",
            **{
                "session.id": self.conversation_id,
                "retail.turn_id": self.turn_id,
                "openinference.span.kind": "CHAIN",
            },
        ) as current:
            context = current.get_span_context()
            self._trace_ids = {
                "trace_id": format(context.trace_id, "032x") if context.is_valid else "",
                "span_id": format(context.span_id, "016x") if context.is_valid else "",
            }
            result = await self._ask(question)
            self.observe("turn_result", result=asdict(result), capture_errors=self.observer_errors)
            current.set_attribute("retail.status", result.status)
            current.set_attribute("retail.capture_errors", self.observer_errors)
            return result

    def now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("The application clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    def observe(self, event: str, **fields) -> None:
        """Capture only explicit application data; instrumentation failure is nonfatal."""
        try:
            record = observation(
                {
                    "event": event,
                    "conversation_id": self.conversation_id,
                    "turn_id": self.turn_id,
                    **self._trace_ids,
                    **fields,
                },
                mode=self.observation_mode,
                secrets=(self.settings.gemini_api_key.get_secret_value(),),
            )
            record_observation(record, self.observation_mode)
            if self.observer is not None:
                self.observer(record)
        except Exception:
            self.observer_errors += 1

    async def _ask(self, question: str) -> TurnResult:
        started = time.monotonic()
        try:
            question = screen(question.strip())
            if not question or len(question) > 6000:
                raise ValueError("Ask a question containing 1-6,000 characters.")
        except ValueError as exc:
            return TurnResult(None, "input_rejected", str(exc), [], {}, [], 0)
        # Approved context is bounded and ephemeral. No raw ADK reasoning is persisted.
        cutoff = self.now().timestamp() - 90 * 86400
        self.history = [h for h in self.history if h["timestamp"] >= cutoff][-6:]
        begin_turn = getattr(self.gateway, "begin_turn", None)
        if begin_turn:
            begin_turn()
        turn = Turn(self, question)
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
                    tools=build_tools(turn),
                    before_model_callback=turn.observe_request,
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
                now = self.now()
                context = {
                    "trusted_scope": self.identity.scope,
                    "now_utc": now.isoformat(),
                    "today_utc": now.date().isoformat(),
                    "prior_approved_conversation": self.context_history(),
                    "available_results": self.result_manifest(),
                    "available_skills": self.skills.list(role="analyst"),
                    "user_question": question,
                }
                self.observe("initial_context", context=context)
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
            message = (
                "This question reached its cost allowance before a reviewed answer was ready. "
                "/details shows completed queries."
                if code == "cost_budget"
                else "This investigation reached its shared limit before a reviewed answer was ready. Try a narrower question; /details shows completed queries."
            )
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
                    "timestamp": self.now().timestamp(),
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
                        "at": self.now().isoformat(),
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
