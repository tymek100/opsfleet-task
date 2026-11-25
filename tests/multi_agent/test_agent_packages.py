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


@pytest.mark.parametrize("role", ["retail", "inventory", "distribution", "coordinator"])
def test_service_business_cutoff_does_not_replace_operational_clock(settings, role):
    from datetime import UTC, datetime

    from retail_insight.a2a.server import Executor
    from retail_insight.integrations.bigquery.domains import compile_domain_query
    from retail_insight.integrations.bigquery.retail import compile_query

    cutoff = datetime(2020, 4, 1, tzinfo=UTC)
    snapshot = datetime(2020, 5, 1, tzinfo=UTC)
    before = datetime.now(UTC)
    executor = Executor(role, settings, store=object(), client=object())
    app = executor.create_runtime(
        WORKSPACE_IDENTITY,
        "clock-contract",
        "request-clock-contract",
        {"as_of": cutoff.isoformat(), "snapshot_at": snapshot.isoformat()},
        {},
    )
    try:
        assert before <= app.now() <= datetime.now(UTC)
        assert app.as_of == cutoff.isoformat()
        assert app.snapshot_at == snapshot.isoformat()
        if role == "coordinator":
            assert not hasattr(app.gateway, "query")
            return
        assert app.gateway.clock() == cutoff
        assert app.gateway.snapshot_at == snapshot
        common = {
            "as_of": app.gateway.clock(),
            "snapshot_at": app.gateway.snapshot_at,
            "source_dataset": app.gateway.source_dataset,
        }
        compiled = (
            compile_query("SELECT CURRENT_TIMESTAMP() FROM sales", app.identity.brands, **common)
            if role == "retail"
            else compile_domain_query(
                "SELECT CURRENT_TIMESTAMP() FROM stock",
                app.identity.brands,
                role=role,
                **common,
            )
        )
        assert "CURRENT_TIMESTAMP" not in compiled
        assert cutoff.isoformat() in compiled
        assert "FOR SYSTEM_TIME AS OF" in compiled
        assert snapshot.isoformat() in compiled
    finally:
        app.reports.close()
