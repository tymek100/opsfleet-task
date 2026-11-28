"""One LangGraph analyst conversation, composable tools and reviewed completion."""

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime

from retail_insight.config import Settings
from retail_insight.contracts import WORKSPACE_IDENTITY, Answer, Identity, TurnResult
from retail_insight.integrations.reports import ReportStore
from retail_insight.observability.tracing import (
    CaptureMode,
    Observer,
    observation,
    record_observation,
    span,
)
from retail_insight.runtime.budget import Budget, LimitReached
from retail_insight.runtime.context import DelegationContext
from retail_insight.runtime.graph import CustomAgentLoop
from retail_insight.runtime.model import BaseLlm
from retail_insight.runtime.privacy import screen
from retail_insight.runtime.prompts import reviewer_prompt
from retail_insight.runtime.provider import ProviderUnavailable, make_gemini
from retail_insight.runtime.turn import Turn
from retail_insight.tools.context import ContextTools


class Analyst(CustomAgentLoop):
    agent_name = "analyst"
    prompt_span_name = "agent.prompt"

    def prompt_spec(self):
        raise NotImplementedError("Each agent supplies its own prompt")

    def build_tools(self, turn):
        raise NotImplementedError("Each agent registers its own capabilities")

    def build_skills(self):
        raise NotImplementedError("Each agent supplies its guidance catalog")

    def build_gateway(self, clock):
        raise ValueError("This agent requires an explicitly configured data gateway")

    def new_budget(self):
        return Budget(self.settings, review_prompt_bytes=self.review_prompt_bytes())

    def review_prompt_bytes(self) -> int:
        model = self.reviewer_model or self.model
        return reviewer_prompt(
            self.settings,
            guidance=self.skills.review_skill(),
            model=model.model if model is not None else None,
        ).request_overhead_bytes

    def extra_context(self) -> dict:
        return {}

    def __init__(
        self,
        settings: Settings,
        identity: Identity = WORKSPACE_IDENTITY,
        *,
        model: BaseLlm | None = None,
        reviewer_model: BaseLlm | None = None,
        gateway=None,
        reports=None,
        progress=None,
        clock: Callable[[], datetime] | None = None,
        observer: Observer | None = None,
        observation_mode: CaptureMode = "metadata",
        screener: Callable[[str], str] = screen,
    ):
        self.settings = settings
        # Identity remains a storage namespace, never a brand-access policy.
        self.identity = Identity(identity.user_id, None)
        self.screen = screener
        if observation_mode not in ("metadata", "synthetic"):
            raise ValueError("Capture mode must be metadata or synthetic")
        self.clock = clock or (lambda: datetime.now(UTC))
        self.observer = observer
        self.observation_mode: CaptureMode = observation_mode
        self.observer_errors = 0
        self.turn_id = ""
        self._trace_ids: dict[str, str] = {}
        # Framework exception logs can contain generated arguments. Emit our metadata instead.
        self.model = model
        self.reviewer_model = reviewer_model
        self.skills = self.build_skills()
        self.gateway = gateway if gateway is not None else self.build_gateway(clock)
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

    async def ask(
        self, question: str, *, delegation: DelegationContext | None = None
    ) -> TurnResult:
        self.turn_id = uuid.uuid4().hex
        self.observer_errors = 0
        with span(
            self.prompt_span_name,
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
            try:
                record_observation(
                    observation(
                        {"event": "prompt_input", "question": question},
                        mode=self.observation_mode,
                        secrets=(self.settings.gemini_api_key.get_secret_value(),),
                    ),
                    self.observation_mode,
                )
            except Exception:
                self.observer_errors += 1
            try:
                result = await self._ask(question, delegation=delegation)
            except BaseException:
                self.observe("prompt_error", status="interrupted")
                raise
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

    async def _ask(
        self, question: str, *, delegation: DelegationContext | None = None
    ) -> TurnResult:
        started = time.monotonic()
        try:
            question = self.screen(question.strip())
            if not question or len(question) > 6000:
                raise ValueError("Ask a question containing 1-6,000 characters.")
            if delegation is not None:
                # Copy and validate at entry: later caller mutations cannot change authority.
                delegation = DelegationContext.model_validate_json(delegation.model_dump_json())
                self.screen(delegation.model_dump_json())
        except ValueError as exc:
            return TurnResult(None, "input_rejected", str(exc), [], {}, [], 0)
        # Approved context is bounded and ephemeral. No unreviewed model text is persisted.
        cutoff = self.now().timestamp() - 90 * 86400
        self.history = [h for h in self.history if h["timestamp"] >= cutoff][-6:]
        begin_turn = getattr(self.gateway, "begin_turn", None)
        if begin_turn:
            begin_turn()
        turn = Turn(self, question, delegation)
        status, message = "incomplete", "The analyst could not complete a reviewed answer."
        try:
            if delegation:
                for source in delegation.evidence:
                    artifact = turn.artifact(
                        {
                            **source,
                            "forwarded_by": delegation.source_agent,
                            "forwarded_evidence_id": source.get("id"),
                        },
                        "Forwarded evidence; verify source, scope and applicability",
                    )
                    turn.delegated_evidence_ids.append(artifact["id"])
            if self.model is None:
                self.model = make_gemini(self.settings)
            async with asyncio.timeout(self.settings.turn_timeout_seconds):
                prompt_spec = self.prompt_spec()
                now = self.now()
                context = {
                    "trusted_scope": self.identity.scope,
                    "now_utc": now.isoformat(),
                    "today_utc": now.date().isoformat(),
                    **self.extra_context(),
                    # Only application-generated handles/counts are eager context.
                    # Historical text and evidence descriptions require a real tool call.
                    "prior_approved_conversation": [
                        {"answer_id": item["answer_id"]} for item in self.history
                    ],
                    "available_result_count": len(self.results),
                    "delegated_evidence_count": len(turn.delegated_evidence_ids),
                    "available_skills": self.skills.list(role="analyst"),
                    "user_question": question,
                    **turn.request_context(),
                }
                self.observe("initial_context", context=context)
                prompt = json.dumps(context, ensure_ascii=False)
                await self.run_loop(
                    turn,
                    prompt_spec,
                    [ContextTools(turn).read_context, *self.build_tools(turn)],
                    prompt,
                )
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
