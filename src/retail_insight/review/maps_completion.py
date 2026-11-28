"""Reviewed completion with the Maps-derived report storage boundary."""

from retail_insight.integrations.maps.privacy import contains_maps
from retail_insight.review.completion import CompletionTools
from retail_insight.runtime.graph import ToolContext


class MapsCompletionTools(CompletionTools):
    async def finish_answer(
        self, markdown: str, evidence_ids: list[str], outcome: str, tool_context: ToolContext
    ) -> dict:
        """Submit complete Markdown for review; Maps-derived content remains ephemeral."""
        if self.turn.pending_save and contains_maps(self.turn.app.results):
            self.turn.pending_save = None
            return {
                "status": "revise",
                "message": "Maps-derived content cannot be stored in reports with this integration. The save was cancelled; explain that limitation and submit the answer without claiming a saved report.",
            }
        return await super().finish_answer(markdown, evidence_ids, outcome, tool_context)
