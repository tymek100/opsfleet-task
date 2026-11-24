"""Exercise the real MCP initialize/list/call protocol against an isolated local server."""

import asyncio
import json
import socket

import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP

from retail_agents.domains.maps import MapsClient
from retail_agents.ephemeral import contains_maps, scrub_maps


def test_ephemeral_redaction_preserves_correlation_without_provider_content():
    source = {
        "artifact_id": "distribution/task/E1",
        "provider": "Google Maps",
        "tool": "compute_routes",
        "storage_policy": "ephemeral-provider-content",
        "purpose": "Drive from private-address",
        "result": {"routes": [{"distanceMeters": 1234}], "attribution": "private-url"},
        "arguments": {"origin": "private-address"},
        "status": "ok",
        "scope": "Calvin Klein",
    }
    wrapped = {"observations": [source], "non_maps": {"value": 42}}
    assert contains_maps(wrapped)
    redacted = scrub_maps(wrapped)
    assert redacted["observations"][0]["artifact_id"] == "distribution/task/E1"
    assert redacted["non_maps"] == {"value": 42}
    assert "private" not in json.dumps(redacted)
    assert "1234" not in json.dumps(redacted)
    assert "result" in source  # Redaction must not remove the reviewer's in-memory evidence.


@pytest.mark.asyncio
@pytest.mark.allow_hosts(["127.0.0.1"])
async def test_maps_client_uses_native_mcp_and_filters_discovered_capabilities(monkeypatch):
    server = FastMCP(
        "isolated-maps-contract", stateless_http=True, json_response=True, log_level="ERROR"
    )

    @server.tool()
    async def compute_routes(origin: dict, destination: dict) -> dict:
        return {
            "routes": [{"distanceMeters": 1234, "duration": "120s"}],
            "attribution": {"googleMapsLinks": ["https://maps.google.com/"]},
        }

    @server.tool()
    async def forbidden_tool() -> str:
        return "not exposed"

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    application = uvicorn.Server(
        uvicorn.Config(server.streamable_http_app(), log_level="error", lifespan="on")
    )
    running = asyncio.create_task(application.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not application.started:
                await asyncio.sleep(0.01)
        monkeypatch.setattr(
            "retail_agents.domains.maps.MAPS_ENDPOINT", f"http://127.0.0.1:{port}/mcp"
        )
        client = MapsClient(api_key="local-contract-only")
        description = await client.describe(timeout=5)
        assert description["status"] == "ok"
        assert [tool["name"] for tool in description["tools"]] == ["compute_routes"]
        response = await client.call(
            "compute_routes",
            {"origin": {"address": "Synthetic A"}, "destination": {"address": "Synthetic B"}},
            timeout=5,
        )
        assert response["status"] == "ok"
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["routes"][0]["distanceMeters"] == 1234
        assert contains_maps(response)
    finally:
        application.should_exit = True
        await asyncio.wait_for(running, timeout=5)
        listener.close()
