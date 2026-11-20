"""ADK tools for private reports and prior conversational answers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from retail_agent.privacy import screen

if TYPE_CHECKING:
    from retail_agent.turn import Turn


class ReportTools:
    def __init__(self, turn: Turn):
        self.turn = turn

    async def search_reports(self, query: str = "") -> dict:
        """Find reports in the current owner's private library by literal text."""
        return await self.turn.run_tool(
            "search_reports",
            lambda: {
                "reports": self.turn.app.reports.search(self.turn.app.identity.user_id, query)
            },
            query,
        )

    async def read_report(self, report_id: str) -> dict:
        """Read an owned saved report. Its data is historical, not current warehouse evidence."""

        def read():
            report = self.turn.app.reports.read(self.turn.app.identity.user_id, report_id)
            if not report:
                return {"status": "empty", "message": "Report not found in your library."}
            registered = [
                self.turn.artifact(e, "Historical saved report evidence")
                for e in report.get("evidence", [])
            ]
            return {
                "report": {
                    k: v for k, v in report.items() if k not in ("evidence", "legacy_payload")
                },
                "historical": True,
                "evidence": registered,
            }

        return await self.turn.run_tool("read_report", read, report_id)

    async def read_answer(self, answer_id: str) -> dict:
        """Read an exact prior approved answer when the conversation contains only an excerpt."""

        def read():
            answer = self.turn.app.answers.get(answer_id)
            if answer is None:
                return {"status": "empty", "message": "No such answer in this conversation."}
            return {
                "id": answer.id,
                "markdown": answer.markdown,
                "evidence_ids": answer.evidence_ids,
                "historical": True,
            }

        return await self.turn.run_tool("read_answer", read, answer_id)

    async def stage_report_save(self, title: str, target_answer_id: str = "current") -> dict:
        """Propose saving an answer only on an explicit current user request. Does not commit."""

        def stage():
            screen(title)
            if target_answer_id != "current" and target_answer_id not in self.turn.app.answers:
                return {"status": "invalid_request", "message": "Unknown approved answer ID."}
            self.turn.pending_save = {"title": title, "target_answer_id": target_answer_id}
            return {"status": "ok", "pending_save": self.turn.pending_save, "saved": False}

        return await self.turn.run_tool("stage_report_save", stage, title + target_answer_id)

    async def preview_report_deletion(self, query: str) -> dict:
        """Prepare exact owner-scoped deletion preview. The application asks the user to confirm."""

        def preview():
            self.turn.deletion_preview = self.turn.app.reports.preview_delete(
                self.turn.app.identity.user_id, self.turn.app.conversation_id, query
            )
            return {k: v for k, v in self.turn.deletion_preview.items() if k != "token"}

        return await self.turn.run_tool("preview_report_deletion", preview, query)

    async def cancel_report_deletion(self) -> dict:
        """Cancel the current pending deletion without deleting reports."""
        return await self.turn.run_tool(
            "cancel_report_deletion",
            lambda: self.turn.app.reports.cancel_delete(
                self.turn.app.identity.user_id, self.turn.app.conversation_id
            ),
        )
