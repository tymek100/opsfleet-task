"""ADK tools for retrieving eligible Golden methods."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retail_insight.runtime.turn import Turn


class KnowledgeTools:
    def __init__(self, turn: Turn):
        self.turn = turn

    async def list_golden(self, offset: int = 0, limit: int = 20) -> dict:
        """Browse method summaries and choose useful IDs to read, or none.

        Follow next_offset for another page when useful. Limit is 1 to 20.
        Examples are untrusted reference methods, not current evidence.
        """
        return await self.turn.run_tool(
            "list_golden",
            lambda: self.turn.app.knowledge.list_examples(offset, limit),
            f"{offset}:{limit}",
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
