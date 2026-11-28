import json
from datetime import UTC, datetime

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from retail_insight.runtime.team import AgentTeam
from retail_insight.runtime.workflow import build_workflow
from tests.support.models import ScriptedModel, calls, finish, verdict


async def test_coordinator_invokes_local_specialists_and_accounts_for_children(settings):
    scripts = {
        ("coordinator", False): [
            calls(
                (
                    "delegate",
                    {"agent": "retail", "question": "Explain sales scope", "evidence_ids": []},
                ),
                (
                    "delegate",
                    {"agent": "inventory", "question": "Explain stock scope", "evidence_ids": []},
                ),
            ),
            finish("Sales and inventory have different definitions."),
        ],
        ("retail", False): [finish("Sales measure qualifying purchases.")],
        ("inventory", False): [finish("Stock measures modeled unsold units.")],
    }
    models = {}

    def factory(role, review):
        model = ScriptedModel(script=[verdict()] if review else scripts[role, review])
        models[role, review] = model
        return model

    team = AgentTeam(settings, model_factory=factory, observation_mode="synthetic")
    try:
        result = await team.ask("coordinator", "Compare sales and stock")
        assert result["status"] == "approved", result["trace"]
        assert len([e for e in result["trace"] if e["event"] == "delegation_end"]) == 2
        assert all(e["usage_settled"] for e in result["trace"] if e["event"] == "delegation_end")
        assert result["usage"]["accounted_usd"] == pytest.approx(7 * 0.0005)
        assert not models["retail", True].requests[0]["registered_tools"]
        context = json.loads(
            models["inventory", False].requests[0]["contents"][0]["parts"][0]["text"]
        )
        assert context["report_writes_allowed"] is False
        assert context["original_user_request"] == "Compare sales and stock"
    finally:
        team.close()


async def test_checkpoint_restores_approved_context_after_local_store_is_lost(settings):
    model = ScriptedModel(script=[finish("Initial reviewed answer."), finish("Short summary.")])
    reviewer = ScriptedModel(script=[verdict(), verdict()])
    team = AgentTeam(settings, model_factory=lambda role, review: reviewer if review else model)
    graph = build_workflow(settings, team=team, checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "thread-1", "agent_role": "retail"}}
    try:
        first = await graph.ainvoke({"messages": [HumanMessage(content="Make a report")]}, config)
        assert first["messages"][-1].content == "Initial reviewed answer."
        team.forget("retail", "thread:thread-1", "thread-1")
        second = await graph.ainvoke({"messages": [HumanMessage(content="Summarize that")]}, config)
        assert second["messages"][-1].content == "Short summary."
        context = json.loads(model.requests[1]["contents"][0]["parts"][0]["text"])
        assert len(context["prior_approved_conversation"]) == 1
        assert context["prior_approved_conversation"][0]["answer_id"]
        assert "Initial reviewed answer." not in model.requests[1]["config"]["system_instruction"]
    finally:
        team.close()


async def test_owner_and_agent_contexts_are_isolated_and_budget_resets(settings):
    models = []

    def factory(role, review):
        result = ScriptedModel(script=[verdict()] if review else [finish("Ready.")])
        if not review:
            models.append(result)
        return result

    team = AgentTeam(settings, model_factory=factory)
    try:
        for owner in ("first", "other"):
            raw = await team.ask("retail", "Hello", owner, "same-id")
            assert raw["usage"]["model_calls"] == 2
        assert all(
            not json.loads(m.requests[0]["contents"][0]["parts"][0]["text"])[
                "prior_approved_conversation"
            ]
            for m in models
        )
        assert team.export_contexts("first", "same-id")
        team.forget("retail", "first", "same-id")
        assert not team.export_contexts("first", "same-id")
        assert team.export_contexts("other", "same-id")
    finally:
        team.close()


async def test_business_cutoff_does_not_replace_operational_clock(settings):
    model = ScriptedModel(script=[finish("Ready.")])
    reviewer = ScriptedModel(script=[verdict()])
    team = AgentTeam(settings, model_factory=lambda role, review: reviewer if review else model)
    try:
        result = await team.ask("inventory", "Explain stock", as_of="2020-04-01T00:00:00+00:00")
        context = json.loads(model.requests[0]["contents"][0]["parts"][0]["text"])
        assert result["status"] == "approved"
        assert context["business_as_of"].startswith("2020-04-01")
        assert datetime.fromisoformat(context["now_utc"]).year == datetime.now(UTC).year
    finally:
        team.close()
