"""Turn-scoped ADK tools. Identity, budgets, evidence and mutations are code-owned."""

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime

from google.adk.tools import ToolContext
from pydantic import ValidationError

from retail_agent.bigquery import Executor
from retail_agent.budget import Budget
from retail_agent.evaluator import Review
from retail_agent.evidence import normalize_rows, render_grounded_text
from retail_agent.models import (
    Analysis,
    Answer,
    AppError,
    Dimension,
    Identity,
    QueryEvidence,
    Scalar,
)
from retail_agent.observability import Trace
from retail_agent.privacy import reject_personal_details, safe_text
from retail_agent.queries import CompiledQuery, compile_query
from retail_agent.render import render_answer
from retail_agent.reports import Preview, ReportStore
from retail_agent.sql_policy import compile_analysis, describe_schema


def _query_key(query: CompiledQuery) -> str:
    """Cache executions by SQL and bound values, not SQL shape alone."""
    return hashlib.sha256(
        json.dumps([query.sql, query.parameters], sort_keys=True, default=str).encode()
    ).hexdigest()


class AnalystTools:
    def __init__(
        self,
        identity: Identity,
        executor: Executor,
        store: ReportStore,
        conversation: str,
        question: str,
        budget: Budget,
        trace: Trace,
        sources: dict[str, QueryEvidence],
        previous: Answer | None,
        reviewer: Review,
        history: list[dict[str, str]],
    ) -> None:
        self.identity, self.executor, self.store = identity, executor, store
        self.conversation, self.question = conversation, question
        self.budget, self.trace, self.sources = budget, trace, dict(sources)
        self.previous = previous
        self.reviewer, self.history = reviewer, history
        self.reviews = 0
        self.candidates: set[str] = set()
        self.query_cache: dict[str, QueryEvidence] = {}
        self.terminal_lock = asyncio.Lock()
        self.save_authorized = False
        self.fresh: list[QueryEvidence] = []
        self.preview: Preview | None = None
        self.cancelled = False
        self.answer: Answer | None = None
        self.save_title: str | None = None
        self.calls = 0
        self.query_lock = asyncio.Lock()
        self.operations: list[str] = []

    def functions(self) -> list[Callable[..., object]]:
        return [
            self.describe_data,
            self.run_analysis,
            self.analyze_states,
            self.read_result,
            self.select_result,
            self.search_reports,
            self.read_report,
            self.save_report,
            self.preview_deletion,
            self.cancel_deletion,
            self.submit_answer,
        ]

    def _start(self, name: str) -> None:
        self.budget.remaining()
        if self.answer is not None:
            raise AppError("This answer is already complete.", code="turn_complete")
        self.calls += 1
        if self.calls > self.budget.settings.max_tool_calls:
            raise AppError("Tool-call limit reached.", code="tool_call_limit")
        self.trace.emit("tool_started", tool=name, call=self.calls)

    def _error(self, exc: AppError) -> dict[str, object]:
        if exc.code in {
            "deadline",
            "cost_limit",
            "model_call_limit",
            "tool_call_limit",
            "turn_complete",
            "review_limit",
            "no_progress",
            "review_stopped",
            "invalid_review",
            "context_limit",
        }:
            raise exc
        self.trace.emit("tool_rejected", error=exc.code)
        return {
            "ok": False,
            "error": exc.code,
            "message": str(exc),
            "retryable": exc.code in {"invalid_query", "result_limit", "answer_grounding"},
        }

    def describe_data(self) -> dict[str, object]:
        """Discover the permitted SQL schema, metric defaults and analytical limits."""
        self._start("describe_data")
        return {**describe_schema(), "scope": self.identity.scope}

    async def run_analysis(self, sql: str, purpose: str, definitions: str) -> dict[str, object]:
        """Run BigQuery SQL against virtual sales, transactions or products relations.

        Choose each query from the user's objective and observations so far. Use
        CTEs/windows for cohorts and repeat purchases. Supply a short analytical
        purpose and the effective metric/time definitions. Never submit raw table
        paths. Results include evidence IDs and may guide another query.
        """
        self._start("run_analysis")
        try:
            reject_personal_details(sql + "\n" + purpose + "\n" + definitions)
            query = compile_analysis(sql, self.identity)
            cache_key = _query_key(query)
            # ADK can emit parallel calls. Serialize paid queries and evidence IDs;
            # every execution shares the same deadline and conservative budget.
            async with self.query_lock:
                if cache_key in self.query_cache:
                    return {
                        "ok": True,
                        "reused": True,
                        "evidence": self.query_cache[cache_key].model_dump(mode="json"),
                    }
                result = await asyncio.to_thread(
                    self.executor.execute, query, self.budget, self.trace
                )
                rows = normalize_rows([dict(row) for row in result.rows], query.output_columns)
                evidence = QueryEvidence(
                    id=f"E{max((int(k[1:]) for k in self.sources), default=0) + 1}",
                    sql=sql,
                    purpose=safe_text(purpose, limit=500),
                    definitions=query.definitions
                    + "\nAnalyst-specified interpretation: "
                    + safe_text(definitions, limit=2000),
                    scope=self.identity.scope,
                    rows=rows,
                    job_id=result.job_id,
                    sql_hash=result.sql_hash or query.fingerprint,
                    bytes_processed=result.bytes_processed,
                    queried_at=datetime.now(UTC).isoformat(),
                )
                self.sources[evidence.id] = evidence
                self.query_cache[cache_key] = evidence
                self.fresh.append(evidence)
                self.trace.emit(
                    "evidence_ready",
                    evidence_id=evidence.id,
                    rows=len(rows),
                    sql_hash=evidence.sql_hash,
                )
            return {
                "ok": True,
                "evidence": evidence.model_dump(mode="json"),
                "queries_remaining": self.budget.settings.max_queries - self.budget.queries,
            }
        except AppError as exc:
            return self._error(exc)

    async def analyze_states(
        self, start: str, end: str, completed_only: bool = False
    ) -> dict[str, object]:
        """Return state-level sales aggregates for UTC [start,end), suppressing cohorts below five customers.

        No individual or product filters are accepted. Geography cannot be joined
        to customer IDs through the SQL tool. end is exclusive.
        """
        self._start("analyze_states")
        try:
            request = Analysis.model_validate(
                {
                    "start": start,
                    "end": end,
                    "dimension": Dimension.STATE,
                    "limit": 50,
                    "completed_only": completed_only,
                }
            )
            query = compile_query(request, self.identity)
            cache_key = _query_key(query)
            async with self.query_lock:
                if cache_key in self.query_cache:
                    return {
                        "ok": True,
                        "reused": True,
                        "evidence": self.query_cache[cache_key].model_dump(mode="json"),
                    }
                result = await asyncio.to_thread(
                    self.executor.execute, query, self.budget, self.trace
                )
                evidence = QueryEvidence(
                    id=f"E{max((int(k[1:]) for k in self.sources), default=0) + 1}",
                    sql="",
                    purpose=f"State aggregates for {start} to {end} UTC (end exclusive).",
                    definitions=query.definitions
                    + " States with fewer than five customers are suppressed. Top 50 states by revenue.",
                    scope=self.identity.scope,
                    rows=normalize_rows([dict(row) for row in result.rows], query.output_columns),
                    job_id=result.job_id,
                    sql_hash=result.sql_hash or query.fingerprint,
                    bytes_processed=result.bytes_processed,
                    queried_at=datetime.now(UTC).isoformat(),
                )
                self.sources[evidence.id] = evidence
                self.query_cache[cache_key] = evidence
                self.fresh.append(evidence)
                self.trace.emit(
                    "evidence_ready",
                    evidence_id=evidence.id,
                    rows=len(evidence.rows),
                    sql_hash=evidence.sql_hash,
                )
            return {"ok": True, "evidence": evidence.model_dump(mode="json")}
        except ValidationError:
            return {
                "ok": False,
                "message": "Use valid ISO dates, with a positive period of at most five years.",
            }
        except AppError as exc:
            return self._error(exc)

    def read_result(self, evidence_id: str) -> dict[str, object]:
        """Inspect a bounded result from this conversation without rerunning the query."""
        self._start("read_result")
        item = self.sources.get(evidence_id)
        return (
            {"ok": True, "evidence": item.model_dump(mode="json")}
            if item
            else {"ok": False, "message": "Evidence not found in this conversation."}
        )

    def select_result(
        self,
        evidence_id: str,
        columns: list[str],
        sort_by: str = "",
        descending: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        """Select/reorder rows and columns within a previous result, without querying.

        Use for 'among those', top/last rows and display-order follow-ups. Empty
        columns keeps every column; negative offsets count from the end. Null sort
        values come last. This never expands the original result population.
        """
        self._start("select_result")
        item = self.sources.get(evidence_id)
        if item is None or not 1 <= limit <= 100 or not -100 <= offset <= 100:
            return {
                "ok": False,
                "message": "Use an available result, a limit of 1-100 and an offset within its rows.",
            }
        available = list(item.rows[0]) if item.rows else columns
        if (
            len(set(columns)) != len(columns)
            or any(c not in available for c in columns)
            or (sort_by and sort_by not in available)
        ):
            return {"ok": False, "message": "Choose existing unique columns."}
        rows = list(item.rows)
        if sort_by:
            nonnull = [r for r in rows if r[sort_by] is not None]
            try:

                def sort_value(row: dict[str, Scalar]) -> str | int | float:
                    value = row[sort_by]
                    if isinstance(value, str):
                        return value
                    if isinstance(value, (int, float)):
                        return value
                    raise ValueError("Unsupported sort value")

                nonnull.sort(key=sort_value, reverse=descending)
            except (TypeError, ValueError):
                return {"ok": False, "message": "Cannot sort mixed value types."}
            rows = [*nonnull, *(r for r in rows if r[sort_by] is None)]
        start = max(0, len(rows) + offset) if offset < 0 else offset
        rows = [{c: row[c] for c in columns or available} for row in rows[start : start + limit]]
        key = f"E{max((int(k[1:]) for k in self.sources), default=0) + 1}"
        derived = item.model_copy(
            update={
                "id": key,
                "rows": rows,
                "parent_ids": [evidence_id],
                "purpose": item.purpose
                + f" Selection from {evidence_id}: sort={sort_by or 'original order'}, descending={descending}, offset={offset}, limit={limit}.",
            }
        )
        self.sources[key] = derived
        self.fresh.append(derived)
        self.trace.emit("result_selected", evidence_id=key, parent_id=evidence_id, rows=len(rows))
        return {"ok": True, "evidence": derived.model_dump(mode="json")}

    def search_reports(self, text: str = "") -> dict[str, object]:
        """List the current user's saved reports, optionally filtering titles by literal text."""
        self._start("search_reports")
        reports = [
            r
            for r in self.store.list(self.identity.user_id)
            if text.casefold() in r.title.casefold()
        ]
        return {
            "reports": [
                {"id": r.id, "title": safe_text(r.title), "conversation": r.conversation}
                for r in reports[:100]
            ],
            "truncated": len(reports) > 100,
        }

    def read_report(self, report_id: str) -> dict[str, object]:
        """Read one report belonging to the current user. Other owners' IDs never grant access."""
        self._start("read_report")
        try:
            report = self.store.read(self.identity.user_id, report_id)
            next_id = max((int(k[1:]) for k in self.sources), default=0) + 1
            mapping = {item.id: f"E{next_id + i}" for i, item in enumerate(report.query_evidence)}
            imported: list[QueryEvidence] = []
            for item in report.query_evidence:
                key = mapping[item.id]
                evidence = item.model_copy(
                    update={
                        "id": key,
                        "parent_ids": [mapping[p] for p in item.parent_ids if p in mapping],
                        "purpose": f"Saved report {report_id}, original {item.id}. {item.purpose}",
                    }
                )
                self.sources[key] = evidence
                imported.append(evidence)
            # Avoid collisions with existing conversation IDs. Do not rewrite SQL,
            # values or the saved artifact itself; only citation labels in prose.
            text = re.sub(
                r"\[(E[0-9]+)\]",
                lambda match: (
                    f"[{mapping[match[1]]}]" if match[1] in mapping else "[historical source]"
                ),
                report.text,
            )
            display = report.model_copy(update={"text": text, "query_evidence": imported})
            return {
                "ok": True,
                "text": safe_text(render_answer(display), limit=16000),
                "evidence_ids": [item.id for item in imported],
                "note": "Saved historical report; rerun queries for current data.",
            }
        except AppError as exc:
            return self._error(exc)

    def save_report(self, title: str) -> dict[str, object]:
        """Stage an explicitly requested save; nothing is written by this tool.

        The evaluator checks the current user's authorization and candidate target.
        The application commits once after approval. Drafting a report is not saving.
        Use this before submit_answer; a save-only turn saves the previous analysis.
        """
        self._start("save_report")
        try:
            reject_personal_details(title)
        except AppError as exc:
            return self._error(exc)
        if not title.strip() or len(title) > 120:
            return {"ok": False, "message": "Use a report title of 1-120 characters."}
        if not re.search(r"(?i)\bsave\b", self.question):
            return {"ok": False, "message": "No explicit save request was found. Use /save TITLE."}
        self.save_title = title
        return {
            "ok": True,
            "status": "pending_review",
            "message": "Save proposed; nothing has been persisted.",
        }

    def preview_deletion(
        self, match: str = "", conversation_only: bool = False
    ) -> dict[str, object]:
        """Preview permanent deletion of this user's literal matching reports. Never deletes.

        The CLI displays the exact report set and confirmation token separately;
        no tool can confirm deletion. An empty match previews all owned reports.
        """
        self._start("preview_deletion")
        try:
            self.preview = self.store.preview(
                self.identity.user_id, self.conversation, match, conversation_only=conversation_only
            )
            message = (
                "Deletion preview prepared. Nothing deleted."
                if self.preview.reports
                else "No matching reports in your library. Nothing was deleted. Use /reports to see your saved reports."
            )
            self.operations.append(message)
            return {
                "ok": True,
                "message": message,
                "report_ids": [r.id for r in self.preview.reports],
            }
        except AppError as exc:
            return self._error(exc)

    def cancel_deletion(self) -> dict[str, object]:
        """Cancel this conversation's pending deletion. No reports are deleted."""
        self._start("cancel_deletion")
        self.store.cancel(self.identity.user_id, self.conversation)
        self.preview, self.cancelled = None, True
        self.operations.append("Pending deletion cancelled. Nothing deleted.")
        return {"ok": True, "message": self.operations[-1]}

    async def submit_answer(
        self, text: str, evidence_ids: list[str], tool_context: ToolContext
    ) -> dict[str, object]:
        """Submit a candidate for review inside this same agent loop.

        Review feedback is an observation: fix the answer or investigate further and
        resubmit. Approval ends the turn; no separate planner/replanning loop exists.
        Cite [E1] and use {{E1.r0.revenue}} or {{E1.r0.share|percent}} for measured
        values. Select every referenced evidence ID; code renders their tables.
        Use empty IDs for help/clarification/library operations. Never invent an
        operation receipt. Saving is committed by the application after approval.
        """
        self._start("submit_answer")
        async with self.terminal_lock:
            if self.answer is not None:
                raise AppError("This answer is already complete.", code="turn_complete")
            try:
                if len(set(evidence_ids)) != len(evidence_ids) or any(
                    k not in self.sources for k in evidence_ids
                ):
                    raise AppError("Select unique available evidence IDs.", code="answer_grounding")
                if self.fresh and not evidence_ids:
                    raise AppError(
                        "Include evidence from this investigation, even when empty.",
                        code="answer_grounding",
                    )
                selected = {key: self.sources[key] for key in evidence_ids}
                rendered = render_grounded_text(text, selected)
            except AppError as exc:
                return self._error(exc)
            # Review outages are terminal, not an invitation to retry via another actor step.
            # Bind review to this exact candidate, source contents and pending write.
            payload: dict[str, object] = {
                "original_question": self.question,
                "recent_history": self.history,
                "authorized_scope": self.identity.scope,
                "candidate": rendered,
                "evidence": [e.model_dump(mode="json") for e in selected.values()],
                "parent_evidence": [
                    self.sources[k].model_dump(mode="json")
                    for k in {p for e in selected.values() for p in e.parent_ids}
                    if k in self.sources
                ],
                "investigation_evidence": [
                    e.model_dump(mode="json") for e in self.fresh if e.id not in selected
                ],
                "pending_save": {
                    "title": self.save_title,
                    "target": "candidate" if selected else "previous_answer",
                }
                if self.save_title
                else None,
                "previous_answer": self.previous.text
                if self.save_title and not selected and self.previous
                else None,
                "operation_receipts": self.operations,
            }
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            if digest in self.candidates:
                raise AppError(
                    "The unchanged candidate was already reviewed. Investigation stopped without progress.",
                    code="no_progress",
                )
            if self.reviews >= self.budget.settings.max_answer_reviews:
                raise AppError("Answer review limit reached.", code="review_limit")
            self.candidates.add(digest)
            self.reviews += 1
            self.trace.emit("candidate_submitted", candidate_hash=digest[:16], attempt=self.reviews)
            review = await self.reviewer(payload)
            if review.decision == "stop":
                raise AppError(
                    "The evaluator could not support completing this request.",
                    code="review_stopped",
                )
            if review.decision == "revise":
                return {
                    "ok": False,
                    "status": "revision_required",
                    "issues": [i.model_dump() for i in review.issues],
                }
            if self.save_title:
                quote = review.save_request_quote.strip()
                if (
                    not review.save_authorized
                    or not quote
                    or quote not in self.question
                    or not re.search(r"(?i)\bsave\b", quote)
                ):
                    self.save_title = None
                    return {
                        "ok": False,
                        "status": "save_not_authorized",
                        "message": "Nothing saved. Explain /save TITLE or answer the original request without saving.",
                    }
                if not selected and (
                    self.previous is None
                    or not (self.previous.evidence or self.previous.query_evidence)
                ):
                    self.save_title = None
                    return {"ok": False, "message": "There is no previous analysis to save."}
                self.save_authorized = True
            self.answer = Answer(
                artifact_version=2,
                text=rendered,
                query_evidence=list(selected.values()),
                trace_id=self.trace.id,
                quality_status="validated" if selected else "not_applicable",
                evaluation_status="approved",
            )
            self.trace.emit(
                "answer_approved", candidate_hash=digest[:16], evidence_count=len(selected)
            )
            tool_context.actions.skip_summarization = True
            return {"ok": True, "status": "approved"}
