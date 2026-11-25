"""ADK tools for private reports and prior conversational answers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from retail_insight.runtime.privacy import screen

if TYPE_CHECKING:
    from retail_insight.runtime.turn import Turn


class ReportTools:
    def __init__(self, turn: Turn):
        self.turn = turn

    def _observation(self, operation: str, result: dict) -> dict:
        """Make actual library/conversation observations available to the reviewer."""
        evidence = self.turn.artifact(
            {
                "evidence_type": "report_operation",
                "operation": operation,
                "observation": {"status": "ok", **result},
            },
            f"Observed {operation}; report content is historical, not current warehouse data",
        )
        # Preserve existing report/answer IDs and response fields. The separate handle
        # can be submitted to finish_answer; these observations need no warehouse SQL.
        return {**result, "evidence_id": evidence["id"]}

    async def search_reports(self, query: str = "") -> dict:
        """Find owned reports by literal text; evidence_id supports library claims in review."""
        return await self.turn.run_tool(
            "search_reports",
            lambda: self._observation(
                "search_reports",
                {"reports": self.turn.app.reports.search(self.turn.app.identity.user_id, query)},
            ),
            query,
        )

    async def read_report(self, report_id: str) -> dict:
        """Read an owned historical report; evidence_id supports claims about its saved text."""

        def read():
            report = self.turn.app.reports.read(self.turn.app.identity.user_id, report_id)
            if not report:
                return self._observation(
                    "read_report",
                    {"status": "empty", "message": "Report not found in your library."},
                )
            registered = [
                self.turn.artifact(e, "Historical saved report evidence")
                for e in report.get("evidence", [])
            ]
            return self._observation(
                "read_report",
                {
                    "report": {
                        k: v for k, v in report.items() if k not in ("evidence", "legacy_payload")
                    },
                    "historical": True,
                    "evidence": registered,
                },
            )

        return await self.turn.run_tool("read_report", read, report_id)

    async def read_answer(self, answer_id: str) -> dict:
        """Read an exact prior approved answer; evidence_id supports historical text claims."""

        def read():
            answer = self.turn.app.answers.get(answer_id)
            if answer is None:
                return self._observation(
                    "read_answer",
                    {"status": "empty", "message": "No such answer in this conversation."},
                )
            return self._observation(
                "read_answer",
                {
                    "id": answer.id,
                    "markdown": answer.markdown,
                    "evidence_ids": answer.evidence_ids,
                    "historical": True,
                },
            )

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
        """Preview owned deletions with evidence_id. Only the application can request confirmation."""

        def preview():
            self.turn.deletion_preview = self.turn.app.reports.preview_delete(
                self.turn.app.identity.user_id, self.turn.app.conversation_id, query
            )
            return self._observation(
                "preview_report_deletion",
                {
                    "status": self.turn.deletion_preview["status"],
                    "message": self.turn.deletion_preview["message"],
                    "reports": [
                        {"id": report["id"], "title": report["title"]}
                        for report in self.turn.deletion_preview["reports"]
                    ],
                },
            )

        return await self.turn.run_tool("preview_report_deletion", preview, query)

    async def cancel_report_deletion(self) -> dict:
        """Cancel pending deletion without deleting reports; evidence_id supports the receipt."""
        return await self.turn.run_tool(
            "cancel_report_deletion",
            lambda: self._observation(
                "cancel_report_deletion",
                self.turn.app.reports.cancel_delete(
                    self.turn.app.identity.user_id, self.turn.app.conversation_id
                ),
            ),
        )
