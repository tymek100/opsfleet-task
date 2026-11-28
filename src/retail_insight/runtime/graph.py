"""Our inherited LangGraph loop. No prebuilt agent or tool-execution factory."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict, get_type_hints

from google.genai import types
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import ConfigDict, ValidationError, create_model

from retail_insight.config import Settings
from retail_insight.observability.tracing import span
from retail_insight.runtime.model import BaseLlm, LlmRequest
from retail_insight.runtime.provider import AccountedModel, ProviderUnavailable


@dataclass
class ToolActions:
    skip_summarization: bool = False


@dataclass
class ToolContext:
    actions: ToolActions = field(default_factory=ToolActions)


class LoopState(TypedDict):
    messages: list[types.Content]
    calls: list[Any]
    repairs: int


class CustomAgentLoop:
    """Specialists inherit this graph and supply prompts, models and registered tools.

    State is private to one question. Only approved answers/evidence are retained
    by the conversation, preventing an unreviewed draft from becoming memory.
    """

    model: BaseLlm | None
    settings: Settings
    agent_name: str
    screen: Callable[[str], str]

    def compile_loop(self, turn, spec, functions):
        if self.model is None:
            raise RuntimeError("A model must be bound before graph execution")
        provider = self.model
        registry = {fn.__name__: fn for fn in functions}
        schemas = {}
        declarations = []
        for name, fn in registry.items():
            hints = get_type_hints(fn)
            fields: dict[str, Any] = {
                key: (
                    hints.get(key, Any),
                    param.default if param.default is not inspect.Parameter.empty else ...,
                )
                for key, param in inspect.signature(fn).parameters.items()
                if key != "tool_context"
            }
            schema = create_model(
                name + "Arguments", __config__=ConfigDict(extra="forbid"), **fields
            )
            schemas[name] = schema
            declarations.append(
                types.FunctionDeclaration(
                    name=name,
                    description=inspect.getdoc(fn) or name,
                    parameters_json_schema=schema.model_json_schema(),
                )
            )
        model = AccountedModel(model=provider.model, delegate=provider).bind(
            turn.budget, turn.emit, prompt=spec, screener=self.screen
        )

        async def model_node(state):
            config = spec.config.model_copy(deep=True)
            config.system_instruction = spec.instruction
            config.tools = [types.Tool(function_declarations=declarations)]
            request = LlmRequest(
                model=provider.model,
                contents=state["messages"],
                config=config,
                tools_dict=registry,
            )
            turn.observe_request(None, request)
            response = None
            async for item in model.generate_content_async(request):
                response = item
            if response is None or response.error_code or response.content is None:
                raise ProviderUnavailable("The model returned no usable decision.")
            turn.observe_model(None, response)
            calls = [p.function_call for p in response.content.parts or [] if p.function_call]
            messages = [*state["messages"], response.content]
            repairs = state["repairs"]
            if not calls:
                repairs += 1
                turn.emit("completion_protocol_repair", attempt=repairs)
                messages.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                text="Submit the complete answer through finish_answer with its evidence IDs; drafts are not published."
                            )
                        ],
                    )
                )
            return {"messages": messages, "calls": calls, "repairs": repairs}

        async def execute(call):
            name = call.name
            try:
                if name not in registry:
                    result = {
                        "status": "invalid_request",
                        "message": "Unknown tool. Choose an available tool.",
                    }
                elif name == "finish_answer" and turn.finish_conflict:
                    result = {
                        "status": "invalid_request",
                        "message": "Submit finish_answer alone, after observing the other results.",
                    }
                else:
                    args = schemas[name].model_validate(call.args or {}).model_dump()
                    if "tool_context" in inspect.signature(registry[name]).parameters:
                        args["tool_context"] = ToolContext()
                    result = registry[name](**args)
                    if inspect.isawaitable(result):
                        result = await result
            except ValidationError:
                result = {
                    "status": "invalid_request",
                    "message": "Arguments do not match the tool schema. Correct the argument names and types.",
                }
            return types.Part(
                function_response=types.FunctionResponse(
                    name=name or "unknown", id=call.id, response=result
                )
            )

        async def tools_node(state):
            # TaskGroup cancels siblings when a deadline or budget failure occurs.
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(execute(call)) for call in state["calls"]]
            return {
                "messages": [
                    *state["messages"],
                    types.Content(role="user", parts=[t.result() for t in tasks]),
                ],
                "calls": [],
            }

        async def review_node(state):
            part = await execute(state["calls"][0])
            return {
                "messages": [*state["messages"], types.Content(role="user", parts=[part])],
                "calls": [],
            }

        def route(state):
            if turn.answer or turn.stopped or state["repairs"] >= 2:
                return END
            if not state["calls"]:
                return "model"
            return (
                "review"
                if len(state["calls"]) == 1 and state["calls"][0].name == "finish_answer"
                else "tools"
            )

        graph = StateGraph(LoopState)

        def traced(name, fn):
            async def node(state):
                with span(f"{self.agent_name}.{name}"):
                    return await fn(state)

            return node

        async def publish(state):
            return {}

        graph.add_node("model", traced("model", model_node))
        graph.add_node("tools", traced("tools", tools_node))
        graph.add_node("review", traced("review", review_node))
        graph.add_node("publish", traced("publish", publish))
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", route, ["model", "tools", "review", END])
        graph.add_edge("tools", "model")
        graph.add_conditional_edges(
            "review",
            lambda state: "publish" if turn.answer else END if turn.stopped else "model",
            ["publish", "model", END],
        )
        graph.add_edge("publish", END)
        return graph.compile(name=self.agent_name)

    async def run_loop(self, turn, spec, functions, prompt):
        graph = self.compile_loop(turn, spec, functions)
        try:
            with tracing_context(enabled=False):
                await graph.ainvoke(
                    {
                        "messages": [types.Content(role="user", parts=[types.Part(text=prompt)])],
                        "calls": [],
                        "repairs": 0,
                    },
                    config={"recursion_limit": self.settings.max_model_calls * 3 + 4},
                )
        except ExceptionGroup as exc:
            # Preserve application deadline/budget outcomes across concurrent tools.
            raise exc.exceptions[0] from None
