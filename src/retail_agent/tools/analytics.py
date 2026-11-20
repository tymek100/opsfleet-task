"""ADK tools for scoped queries and stored result analysis."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from retail_agent.services.warehouse import analyze_results

if TYPE_CHECKING:
    from retail_agent.turn import Turn


class DataTools:
    def __init__(self, turn: Turn):
        self.turn = turn

    async def describe_data(self, topic_or_relations: str = "") -> dict:
        """Discover authorized relations, columns, joins and adjustable metric definitions."""
        return await self.turn.run_tool(
            "describe_data", lambda: self.turn.app.gateway.describe_data(topic_or_relations)
        )

    async def query_data(self, sql: str, purpose: str, parameters_json: str = "{}") -> dict:
        """Execute read-only BigQuery SQL over sales, transactions or products; return evidence."""

        async def query():
            parameters = json.loads(parameters_json)
            if not isinstance(parameters, dict):
                raise ValueError("Parameters must be an object")
            self.turn.budget.query()
            result = await self.turn.app.gateway.query(
                sql, parameters, timeout=min(40, self.turn.budget.work_remaining())
            )
            return self.turn.artifact(result, purpose)

        return await self.turn.run_tool("query_data", query, sql + parameters_json)

    async def read_result(self, result_id: str, offset: int = 0, limit: int = 20) -> dict:
        """Read a bounded page of stored evidence. Beyond stored rows, query a smaller result."""

        def read():
            if offset < 0 or not 1 <= limit <= 100:
                raise ValueError("Invalid page")
            result = self.turn.app.results[result_id]
            rows = result.get("rows", [])
            return self.turn.artifact(
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

        return await self.turn.run_tool("read_result", read, f"{result_id}:{offset}:{limit}")

    async def analyze_results(self, result_ids: list[str], sql: str, purpose: str) -> dict:
        """Analyze stored evidence with SQL; table names are result IDs such as E1. No external IO."""

        async def analyze():
            parents = {i: self.turn.app.results[i] for i in result_ids}
            result = await analyze_results(
                parents, sql, timeout=min(5, self.turn.budget.work_remaining())
            )
            return self.turn.artifact(result, purpose, result_ids)

        return await self.turn.run_tool("analyze_results", analyze, sql)

    async def query_state_summary(
        self, start: str, end: str, status_definition: str = "qualifying"
    ) -> dict:
        """Get privacy-filtered state aggregates; never individual customer geography."""

        async def query():
            self.turn.budget.query()
            result = await self.turn.app.gateway.state_summary(
                start, end, status_definition, timeout=min(40, self.turn.budget.work_remaining())
            )
            return self.turn.artifact(result, "State aggregates")

        return await self.turn.run_tool(
            "query_state_summary", query, start + end + status_definition
        )
