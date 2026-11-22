"""Reviewed completion and authorized report commits."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import TYPE_CHECKING

from google.adk.tools import ToolContext

from retail_agent.budget import LimitReached
from retail_agent.contracts import Answer
from retail_agent.privacy import screen
from retail_agent.provider import ProviderUnavailable
from retail_agent.reviewer import evaluate

if TYPE_CHECKING:
    from retail_agent.turn import Turn


class CompletionTools:
    def __init__(self, turn: Turn):
        self.turn = turn

    async def finish_answer(
        self, markdown: str, evidence_ids: list[str], outcome: str, tool_context: ToolContext
    ) -> dict:
        """Submit your complete Markdown for review. Outcome: answer, clarification, refusal, partial."""
        self.turn.budget.tool(completion=True)
        if self.turn.finish_conflict or self.turn.active:
            return {
                "status": "invalid_request",
                "message": "Submit finish_answer alone after observing other tool results.",
            }
        if self.turn.answer or self.turn.stopped:
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
        if any(i not in self.turn.app.results for i in evidence_ids):
            return {"status": "invalid_request", "message": "Use only actual evidence IDs."}
        fingerprint = hashlib.sha256(
            json.dumps([markdown, evidence_ids, self.turn.pending_save]).encode()
        ).hexdigest()
        if fingerprint in self.turn.candidates:
            return {
                "status": "revise",
                "message": "This unchanged candidate was already reviewed. Address the issues or narrow the answer.",
            }
        if self.turn.reviews >= self.turn.app.settings.max_answer_reviews:
            raise LimitReached("review_attempts")
        self.turn.candidates.add(fingerprint)
        self.turn.reviews += 1
        evidence = [self.turn.app.results[i] for i in dict.fromkeys(evidence_ids)]
        target = (
            self.turn.app.answers.get(self.turn.pending_save["target_answer_id"])
            if self.turn.pending_save
            else None
        )
        payload = {
            "question": self.turn.question,
            "scope": self.turn.app.identity.scope,
            "conversation": self.turn.app.context_history(),
            "candidate": {"markdown": markdown, "outcome": outcome},
            "evidence": evidence,
            "other_results_manifest": self.turn.app.result_manifest(),
            "retrieved_methods": self.turn.retrieved,
            "loaded_skills": list(self.turn.loaded_skills.values()),
            "pending_save": self.turn.pending_save,
            "save_target": {"id": target.id, "markdown": target.markdown} if target else None,
        }
        self.turn.app.observe(
            "answer_candidate",
            candidate={"markdown": markdown, "evidence_ids": evidence_ids, "outcome": outcome},
            evidence=evidence,
            conversation=payload["conversation"],
        )
        self.turn.emit("review_start", attempt=self.turn.reviews)
        review_model = self.turn.app.reviewer_model or self.turn.app.model
        if review_model is None:
            raise ProviderUnavailable("The evaluator model is not configured.")
        review = await evaluate(
            payload,
            review_model,
            self.turn.budget,
            self.turn.app.settings,
            self.turn.emit,
            review_skill=self.turn.app.skills.review_skill(),
        )
        self.turn.app.observe("review_result", review=review.model_dump())
        self.turn.emit(
            "review_end",
            decision=review.decision,
            issue_categories=[i.category for i in review.issues],
        )
        if review.decision == "stop":
            self.turn.stopped = True
            tool_context.actions.skip_summarization = True
            return {"status": "stopped"}
        if self.turn.pending_save and not review.save_authorized:
            self.turn.pending_save = None
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
        if self.turn.pending_save:
            saved_answer = target or answer
            try:
                receipt = self.turn.app.reports.save(
                    self.turn.app.identity.user_id,
                    self.turn.pending_save["title"],
                    saved_answer.markdown,
                    [self.turn.app.results[i] for i in saved_answer.evidence_ids],
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
        self.turn.answer = answer
        self.turn.emit(
            "answer_approved",
            answer_id=answer.id,
            sha256=hashlib.sha256(markdown.encode()).hexdigest(),
        )
        return {"status": "approved", "answer_id": answer.id}
