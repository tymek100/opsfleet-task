"""ADK tools for retrieving eligible Golden methods."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retail_agent.turn import Turn


class KnowledgeTools:
    def __init__(self, turn: Turn):
        self.turn = turn

    async def search_golden(self, query: str, limit: int = 3) -> dict:
        """Find relevant eligible analytical methods. Examples are not current evidence."""
        return await self.turn.run_tool(
            "search_golden", lambda: self.turn.app.knowledge.search(query, limit), query
        )

    async def read_golden(self, example_id: str) -> dict:
        """Read an eligible example's SQL and answer to adapt or ignore. Query fresh numbers."""

        def read():
            result = self.turn.app.knowledge.read(example_id)
            example = result.get("example", {})
            if result.get("status") == "ok" and example:
                metadata = {"id": example["id"], "revision": example["revision"]}
                self.turn.retrieved.append(metadata)
                self.turn.emit("golden_read", **metadata)
            return result

        return await self.turn.run_tool("read_golden", read, example_id)
