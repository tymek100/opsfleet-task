"""Agent packaging preserves reviewed execution and capability boundaries."""

from importlib import import_module
from pathlib import Path

import pytest

from retail_insight.agents.registry import create_agent
from retail_insight.contracts import WORKSPACE_IDENTITY
from tests.support.models import ScriptedModel, finish, verdict


@pytest.mark.parametrize(
    ("role", "required", "forbidden", "skill"),
    [
        (
            "retail",
            {"query_data", "query_state_summary"},
            {"delegate", "call_maps"},
            "product-ranking-analysis",
        ),
        (
            "inventory",
            {"query_data", "describe_data"},
            {"delegate", "call_maps", "query_state_summary"},
            "inventory-analysis",
        ),
        (
            "distribution",
            {"query_data", "describe_maps", "call_maps"},
            {"delegate", "query_state_summary"},
            "distribution-analysis",
        ),
        (
            "coordinator",
            {"list_agents", "delegate"},
            {"query_data", "describe_data", "call_maps", "query_state_summary"},
            "cross-domain-analysis",
        ),
    ],
)
async def test_each_agent_keeps_its_capabilities_and_reviewed_completion(
    settings, role, required, forbidden, skill
):
    candidate = "Which period should I analyze?"
    model = ScriptedModel(script=[finish(candidate, outcome="clarification")])
    reviewer = ScriptedModel(script=[verdict()])
    app = create_agent(
        role,
        settings,
        WORKSPACE_IDENTITY,
        gateway=object(),
        model=model,
        reviewer_model=reviewer,
    )
    try:
        result = await app.ask("Analyze our performance.")
        assert result.status == "approved", result.trace
        assert result.answer.markdown == candidate
        tools = set(model.requests[0]["registered_tools"])
        assert required <= tools
        assert not tools & forbidden
        assert not tools & {"list_golden", "read_golden"}
        assert not hasattr(app, "knowledge")
        assert "finish_answer" in tools
        assert reviewer.requests[0]["registered_tools"] == []
        assert skill in {entry["name"] for entry in app.skills.list()}
        assert app.skills.load(skill)["instructions"]
        module_path = import_module(type(app).__module__).__file__
        assert module_path is not None
        prompt_path = Path(module_path).with_name("prompt.md")
        assert prompt_path.read_text() in app.prompt_spec().instruction
        assert type(app).__module__ == f"retail_insight.agents.{role}.agent"
    finally:
        app.reports.db.close()


def test_unknown_agent_cannot_fall_back_to_an_authorized_role(settings):
    with pytest.raises(ValueError):
        create_agent("unknown", settings, WORKSPACE_IDENTITY, gateway=object())
