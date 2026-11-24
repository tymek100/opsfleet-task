"""Cancellation crosses an actual HTTP/SSE A2A connection to the running agent."""

import asyncio
import socket

import pytest
import uvicorn

from retail_agents.client import AgentClient
from retail_agents.server import create_app
from tests.multi_agent.test_transport import AS_OF, SECRET, ReviewedRuntime


@pytest.mark.allow_hosts(["127.0.0.1"])
async def test_cancel_streaming_client_stops_remote_execution(settings, monkeypatch):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class WaitingRuntime(ReviewedRuntime):
        async def ask(self, question):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    monkeypatch.setattr("retail_agents.server.RoleAnalyst", WaitingRuntime)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    app = create_app("inventory", settings, secret=SECRET, demo_token="local-only", public_url=f"http://127.0.0.1:{port}")
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    request = None
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        client = AgentClient({"inventory": f"http://127.0.0.1:{port}"}, SECRET)
        request = asyncio.create_task(client.ask("inventory", "Wait", as_of=AS_OF, stream=True))
        await asyncio.wait_for(entered.wait(), timeout=5)
        await asyncio.sleep(0.1)  # Allow the initial working event to reach the client.
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(request, timeout=6)
        await asyncio.wait_for(cancelled.wait(), timeout=5)
    finally:
        if request is not None and not request.done():
            request.cancel()
        server.should_exit = True
        await asyncio.wait_for(serving, timeout=5)
        listener.close()
