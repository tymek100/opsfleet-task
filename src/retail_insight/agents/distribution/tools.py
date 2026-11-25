"""Distribution capabilities: scoped warehouse queries and optional Maps MCP."""

import json

from retail_insight.tools.analytics import DataTools
from retail_insight.tools.domain import DomainTools, common_tools


def build_tools(turn):
    data, domain, maps = DataTools(turn), DomainTools(turn), MapsTools(turn)
    return [
        *common_tools(turn),
        data.describe_data,
        domain.query_data,
        maps.describe_maps,
        maps.call_maps,
    ]


class MapsTools:
    def __init__(self, turn):
        self.turn = turn

    async def describe_maps(self) -> dict:
        """Discover available Google Maps MCP tool schemas and capability limits."""

        async def describe():
            return await self.turn.app.maps.describe()

        return await self.turn.run_tool("describe_maps", describe)

    async def call_maps(self, tool_name: str, arguments_json: str, purpose: str) -> dict:
        """Call an allowed Maps MCP tool using its discovered schema; never confirms delivery."""

        async def call():
            arguments = json.loads(arguments_json)
            if self.turn.app.maps.available:
                # Configured conservative allowance, not a promise about vendor billing.
                self.turn.budget.reserve(0.01)
            result = await self.turn.app.maps.call(
                tool_name, arguments, timeout=min(20, self.turn.budget.work_remaining())
            )
            if result.get("status") not in ("ok", "empty"):
                return result
            return self.turn.artifact(result, purpose)

        return await self.turn.run_tool("call_maps", call, tool_name + arguments_json)
