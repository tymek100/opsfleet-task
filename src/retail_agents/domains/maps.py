"""Bounded Google Maps MCP adapter. Credentials never enter tool arguments."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from typing import Any

from retail_agent.services.warehouse import DataError

MAPS_ENDPOINT = "https://mapstools.googleapis.com/mcp"
ALLOWED_TOOLS = frozenset({"compute_routes", "lookup_weather"})
MAX_RESPONSE_BYTES = 100_000
MAPS_LIMITATIONS = (
    "Google Maps supplies route/environment context, not warehouse capacity, a truck-safe "
    "route, carrier price, dispatch confirmation or delivery guarantee. Facility coordinates "
    "from TheLook are demonstration metadata. Live Maps data is retrieved now and is not "
    "a historical observation at the warehouse business cutoff. Preserve Google Maps "
    "attribution and source links in any answer using this result."
)


def validate_maps_arguments(tool_name: str, arguments: dict) -> None:
    """An enforced capability/pricing boundary; the model cannot enable Pro features."""
    if tool_name not in ALLOWED_TOOLS:
        raise DataError("denied", "Only compute_routes and lookup_weather are enabled.")
    if not isinstance(arguments, dict) or len(json.dumps(arguments).encode()) > 12_000:
        raise DataError("invalid_request", "Maps arguments must be an object under 12 KB.")
    if tool_name == "compute_routes":
        allowed = {
            "origin",
            "destination",
            "travel_mode",
            "routing_preference",
            "intermediate_waypoints",
            "departure_time",
            "arrival_time",
            "compute_alternative_routes",
            "include_polyline",
            "location_bias",
        }
        if set(arguments) - allowed:
            raise DataError("denied", "Unsupported Maps route option.")
        if (
            arguments.get("routing_preference", "ROUTING_PREFERENCE_TRAFFIC_UNAWARE")
            != "ROUTING_PREFERENCE_TRAFFIC_UNAWARE"
        ):
            raise DataError("denied", "Traffic-aware Pro routing is not enabled.")
        if arguments.get("travel_mode", "DRIVE") != "DRIVE":
            raise DataError("denied", "Only standard driving routes are enabled.")
        stops = arguments.get("intermediate_waypoints", [])
        if not isinstance(stops, list) or len(stops) > 10:
            raise DataError("denied", "At most ten intermediate route stops are allowed.")
        if not arguments.get("origin") or not arguments.get("destination"):
            raise DataError("invalid_request", "A route requires origin and destination.")
    else:
        allowed = {"location", "capabilities", "date", "hour", "language_code", "weather_options"}
        if set(arguments) - allowed:
            raise DataError("denied", "Only weather options are enabled.")
        if arguments.get("capabilities", ["WEATHER"]) != ["WEATHER"]:
            raise DataError(
                "denied", "Only WEATHER is enabled; pollen and air quality are disabled."
            )
        if not arguments.get("location"):
            raise DataError("invalid_request", "Weather requires a location.")


class MapsClient:
    """Create and close one native MCP session per bounded tool operation."""

    def __init__(self, api_key: str | None = None):
        self._api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "") if api_key is None else api_key

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def _request(self, tool_name: str | None, arguments: dict, timeout: float) -> Any:
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with asyncio.timeout(timeout):
            async with (
                httpx.AsyncClient(
                    headers={"X-Goog-Api-Key": self._api_key},
                    timeout=httpx.Timeout(timeout),
                    follow_redirects=False,
                ) as http,
                streamable_http_client(MAPS_ENDPOINT, http_client=http) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                return await (
                    session.list_tools()
                    if tool_name is None
                    else session.call_tool(tool_name, arguments=arguments)
                )

    async def describe(self, timeout: float = 10) -> dict:
        if not self.available:
            return {
                "status": "unavailable",
                "tools": [],
                "reason": "GOOGLE_MAPS_API_KEY is not configured.",
                "limitations": MAPS_LIMITATIONS,
            }
        try:
            response = await self._request(None, {}, max(0.1, min(timeout, 15)))
            tools = [
                tool.model_dump(mode="json", by_alias=True)
                for tool in response.tools
                if tool.name in ALLOWED_TOOLS
            ]
            return {
                "status": "ok",
                "tools": tools,
                "limitations": MAPS_LIMITATIONS,
                "policy": "Driving routes without traffic-aware Pro options, at most ten stops; WEATHER only.",
            }
        except asyncio.CancelledError:
            raise
        except Exception:
            return {
                "status": "unavailable",
                "tools": [],
                "reason": "Google Maps MCP discovery failed; check credentials, API enablement and connectivity.",
            }

    async def call(self, tool_name: str, arguments: dict, timeout: float = 20) -> dict:
        validate_maps_arguments(tool_name, arguments)
        if not self.available:
            return {
                "status": "unavailable",
                "reason": "GOOGLE_MAPS_API_KEY is not configured.",
                "limitations": MAPS_LIMITATIONS,
            }
        if timeout <= 0:
            raise DataError("limit_reached", "Maps deadline expired.")
        try:
            response = await self._request(tool_name, arguments, min(timeout, 30))
            payload = response.model_dump(mode="json", by_alias=True, exclude_none=True)
            if len(json.dumps(payload).encode()) > MAX_RESPONSE_BYTES:
                raise DataError(
                    "limit_reached", "Maps response exceeds 100 KB; request a simpler result."
                )
            return {
                "status": "error" if response.isError else "ok",
                "provider": "Google Maps",
                "tool": tool_name,
                "result": payload,
                "retrieved_at": dt.datetime.now(dt.UTC).isoformat(),
                "limitations": MAPS_LIMITATIONS,
                "trace_content": False,
                "storage_policy": "ephemeral-provider-content",
            }
        except (asyncio.CancelledError, DataError):
            raise
        except Exception:
            return {
                "status": "unavailable",
                "reason": "Google Maps MCP request failed; no route or weather fact was obtained.",
                "limitations": MAPS_LIMITATIONS,
            }
