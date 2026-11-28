"""The whole agent loop: model -> tools -> model, or model -> END."""

from __future__ import annotations

import asyncio
from typing import Literal, Protocol, TypedDict

from google.genai import types
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from retail_insight.core.tool import Tool


class Model(Protocol):
    async def generate(
        self, messages: list[types.Content], instruction: str, tools: list[Tool]
    ) -> types.Content: ...
    async def close(self) -> None: ...


class AgentState(TypedDict):
    messages: list[types.Content]
    model_calls: int
    answer: str


def tool_calls(content: types.Content) -> list[types.FunctionCall]:
    return [part.function_call for part in content.parts or [] if part.function_call]


class AgentLoop:
    """Inherit this class and supply your prompt, model and tools."""

    def __init__(
        self,
        model: Model,
        instruction: str,
        tools: list[Tool],
        *,
        max_model_calls=8,
        timeout_seconds=120,
    ):
        self.model, self.instruction = model, instruction
        self.tools = {tool.name: tool for tool in tools}
        if len(self.tools) != len(tools):
            raise ValueError("Tool names must be unique.")
        self.max_model_calls, self.timeout_seconds = max_model_calls, timeout_seconds
        self.history: list[types.Content] = []
        self.last_tools: list[dict] = []
        graph = StateGraph(AgentState)
        graph.add_node("model", self.call_model)
        graph.add_node("tools", self.call_tools)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", self.next_step, {"tools": "tools", "done": END})
        graph.add_edge("tools", "model")
        self.graph = graph.compile()

    async def call_model(self, state: AgentState) -> dict:
        if state["model_calls"] >= self.max_model_calls:
            raise RuntimeError("Reached the model-call limit. Try a narrower question.")
        response = await self.model.generate(
            state["messages"], self.instruction, list(self.tools.values())
        )
        answer = "".join(
            part.text for part in response.parts or [] if part.text and not part.thought
        )
        if not tool_calls(response) and not answer.strip():
            raise RuntimeError("The model returned neither a tool call nor an answer.")
        return {
            "messages": [*state["messages"], response],
            "model_calls": state["model_calls"] + 1,
            "answer": answer,
        }

    def next_step(self, state: AgentState) -> Literal["tools", "done"]:
        return "tools" if tool_calls(state["messages"][-1]) else "done"

    async def call_tools(self, state: AgentState) -> dict:
        # Leave room for the model to read the results and answer.
        if state["model_calls"] >= self.max_model_calls:
            raise RuntimeError("Reached the model-call limit before executing more tools.")
        calls = tool_calls(state["messages"][-1])
        if len(calls) > 4:
            raise RuntimeError("Too many simultaneous tool requests (maximum four).")
        responses = []
        for call in calls:
            tool = self.tools.get(call.name or "")
            result = (
                await tool.invoke(call.args or {})
                if tool
                else {"error": "Unknown tool. Use an available tool name."}
            )
            self.last_tools.append({"tool": call.name, "arguments": call.args, "result": result})
            responses.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=call.name, id=call.id, response=result
                    )
                )
            )
        return {"messages": [*state["messages"], types.Content(role="user", parts=responses)]}

    async def ask(self, question: str) -> str:
        if not question.strip():
            raise ValueError("Enter a question.")
        self.last_tools = []
        initial: AgentState = {
            "messages": [
                *self.history,
                types.Content(role="user", parts=[types.Part(text=question)]),
            ],
            "model_calls": 0,
            "answer": "",
        }
        # LangGraph depends on LangSmith internally; explicitly disable ambient tracing.
        with tracing_context(enabled=False):
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.graph.ainvoke(
                    initial, config={"recursion_limit": self.max_model_calls * 2 + 1}
                )
        # A failed/cancelled turn must not leave dangling tool calls in conversation history.
        self.history = result["messages"]
        return result["answer"]

    def reset(self):
        self.history.clear()
        self.last_tools.clear()

    async def close(self):
        await self.model.close()
