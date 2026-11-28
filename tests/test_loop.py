import asyncio

import pytest
from google.genai import types

from retail_insight.core.loop import AgentLoop
from retail_insight.core.tool import Tool, ToolArgs


class ScriptedModel:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    async def generate(self, messages, instruction, tools):
        self.requests.append(list(messages))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        pass


def text(value):
    return types.Content(role="model", parts=[types.Part(text=value)])


def call(name="lookup", args=None):
    return types.Content(
        role="model",
        parts=[
            types.Part(
                function_call=types.FunctionCall(name=name, args=args or {}, id="call-1"),
                thought_signature=b"opaque-signature",
            )
        ],
    )


async def test_tool_loop_preserves_signature_results_and_follow_up():
    async def lookup():
        return {"revenue": 100}

    requested = call()
    model = ScriptedModel(requested, text("Revenue is 100."), text("Revenue reached 100."))
    agent = AgentLoop(model, "Retail prompt", [Tool("lookup", "Read totals", ToolArgs, lookup)])
    assert await agent.ask("Revenue?") == "Revenue is 100."
    assert model.requests[1][1] is requested
    result = model.requests[1][2].parts[0].function_response
    assert result.response == {"revenue": 100} and result.id == "call-1"
    assert await agent.ask("Summarize") == "Revenue reached 100."
    assert len(model.requests) == 3  # Follow-up did not require another lookup.
    assert len(agent.history) == 6
    agent.reset()
    assert agent.history == [] and agent.last_tools == []


async def test_bad_arguments_return_observation_so_model_can_recover():
    executed = []

    async def lookup():
        executed.append(True)
        return {"value": 1}

    model = ScriptedModel(call(args={"injected": True}), call(), text("One."))
    agent = AgentLoop(model, "", [Tool("lookup", "Read", ToolArgs, lookup)])
    assert await agent.ask("Read") == "One."
    assert len(executed) == 1
    assert "error" in agent.last_tools[0]["result"]


async def test_call_limit_stops_before_an_unnecessary_query():
    executed = []

    async def lookup():
        executed.append(True)
        return {}

    agent = AgentLoop(
        ScriptedModel(call()), "", [Tool("lookup", "Read", ToolArgs, lookup)], max_model_calls=1
    )
    with pytest.raises(RuntimeError, match="limit"):
        await agent.ask("Investigate forever")
    assert not executed and not agent.history


async def test_failed_turn_does_not_pollute_previous_history():
    model = ScriptedModel(text("Hello"), RuntimeError("offline failure"), text("Hello again"))
    agent = AgentLoop(model, "", [])
    await agent.ask("Hi")
    previous = list(agent.history)
    with pytest.raises(RuntimeError):
        await agent.ask("Failed question")
    assert agent.history == previous
    assert await agent.ask("Retry") == "Hello again"
    assert len(model.requests[-1]) == 3


async def test_cancellation_does_not_save_incomplete_history():
    started = asyncio.Event()

    class WaitingModel(ScriptedModel):
        async def generate(self, messages, instruction, tools):
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("Cancelled model unexpectedly resumed")

    agent = AgentLoop(WaitingModel(), "", [])
    task = asyncio.create_task(agent.ask("Wait"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not agent.history


async def test_only_visible_text_is_returned():
    response = types.Content(
        role="model", parts=[types.Part(text="internal", thought=True), types.Part(text="Hello")]
    )
    agent = AgentLoop(ScriptedModel(response), "", [])
    assert await agent.ask("Hi") == "Hello"
