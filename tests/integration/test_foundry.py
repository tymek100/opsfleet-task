import json

import httpx
import pytest
from langsmith import tracing_context

from retail_insight.integrations.foundry.host import request_owner
from retail_insight.runtime.team import AgentTeam
from retail_insight.runtime.workflow import build_workflow
from tests.support.models import ScriptedModel, finish, verdict

hosting = pytest.importorskip("langchain_azure_ai.agents.hosting")


async def test_responses_host_preserves_followup_context(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTSERVER_STATE_ROOT", str(tmp_path / "foundry-state"))
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    model = ScriptedModel(script=[finish("Initial reviewed report."), finish("Reviewed summary.")])
    reviewer = ScriptedModel(script=[verdict(), verdict()])
    team = AgentTeam(settings, model_factory=lambda role, review: reviewer if review else model)
    try:
        async with hosting.FoundryCheckpointSaver() as saver:
            graph = build_workflow(
                settings, team=team, checkpointer=saver, owner_resolver=request_owner
            )
            host = hosting.ResponsesHostServer(graph)
            async with (
                host.app.router.lifespan_context(host.app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=host.app), base_url="http://localhost:8088"
                ) as client,
            ):
                with tracing_context(enabled=False):
                    first = await client.post(
                        "/responses", json={"input": "Make a report", "stream": False}
                    )
                    assert first.status_code == 200, first.text
                    assert "Initial reviewed report." in first.text
                    second = await client.post(
                        "/responses",
                        json={
                            "input": "Summarize that",
                            "previous_response_id": first.json()["id"],
                            "stream": False,
                        },
                    )
                    assert second.status_code == 200, second.text
                    assert "Reviewed summary." in second.text
            context = json.loads(model.requests[1]["contents"][0]["parts"][0]["text"])
            assert len(context["prior_approved_conversation"]) == 1
    finally:
        team.close()


def test_hosted_owner_requires_platform_identity(monkeypatch):
    from types import SimpleNamespace

    import azure.ai.agentserver.core as core

    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.invalid/project")
    monkeypatch.setattr(core, "get_request_context", lambda: SimpleNamespace(user_id=None))
    with pytest.raises(ValueError, match="authenticated"):
        request_owner()
    monkeypatch.setattr(core, "get_request_context", lambda: SimpleNamespace(user_id="user-123"))
    assert request_owner() == "foundry:user-123"
