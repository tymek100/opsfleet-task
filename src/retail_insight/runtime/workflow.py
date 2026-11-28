"""Deployable multi-agent graph; each role runs the inherited custom agent loop."""

from __future__ import annotations

import uuid
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from retail_insight.config import Settings
from retail_insight.runtime.team import AGENT_TYPES, AgentTeam


class WorkflowInput(TypedDict):
    messages: list[AnyMessage]


class WorkflowState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    approved_contexts: dict
    result: dict


def build_workflow(settings=None, *, team=None, checkpointer=None, owner_resolver=None):
    settings = settings or Settings.load()
    team = team or AgentTeam(settings)

    def role_for(config):
        role = config.get("configurable", {}).get("agent_role", "coordinator")
        if role not in AGENT_TYPES:
            raise ValueError("Unknown agent role")
        return role

    def role_node(role):
        async def invoke(state: WorkflowState, config: RunnableConfig):
            identifier = config.get("configurable", {}).get("thread_id") or uuid.uuid4().hex
            owner = owner_resolver() if owner_resolver else "thread:" + identifier
            messages = state.get("messages", [])
            question = next(
                (m.content for m in reversed(messages) if isinstance(m, HumanMessage)), None
            )
            if not isinstance(question, str) or not question.strip():
                raise ValueError("A text user message is required")
            # Only checkpointed state reaches this field; public input is messages only.
            team.restore_contexts(owner, identifier, state.get("approved_contexts", {}))
            result = await team.ask(role, question, owner, identifier)
            return {
                "messages": [AIMessage(content=result["markdown"])],
                "approved_contexts": team.export_contexts(owner, identifier),
                "result": {k: result.get(k) for k in ("status", "usage", "trace_id", "context_id")},
            }

        return invoke

    graph = StateGraph(WorkflowState, input_schema=WorkflowInput)
    for role in AGENT_TYPES:
        graph.add_node(role, role_node(role))
        graph.add_edge(role, END)
    graph.add_conditional_edges(START, lambda state, config: role_for(config), list(AGENT_TYPES))
    return graph.compile(checkpointer=checkpointer, name="retail_insight")


def create_graph(config=None):
    """LangGraph CLI factory. Foundry supplies its durable checkpointer separately."""
    return build_workflow()
