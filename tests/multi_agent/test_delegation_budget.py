"""Concurrent delegation must distinguish pending usage from exhausted allowance."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from retail_insight.agents.coordinator.tools import DelegationTools
from retail_insight.agents.registry import create_agent
from retail_insight.contracts import WORKSPACE_IDENTITY
from retail_insight.runtime.turn import Turn
from tests.support.models import ScriptedModel, calls, finish, verdict


def response(agent, usage=0.05):
    return {
        "status": "approved",
        "scope": "all brands",
        "as_of": None,
        "snapshot_at": None,
        "task_id": f"{agent}-task",
        "context_id": f"{agent}-context",
        "evidence": [],
        "markdown": f"{agent} observations",
        "usage": {"accounted_usd": usage},
    }


def coordinator(settings, ask, cap=1):
    return create_agent(
        "coordinator",
        settings.model_copy(update={"question_budget_usd": cap}),
        WORKSPACE_IDENTITY,
        client=SimpleNamespace(ask=ask),
        model=ScriptedModel(),
    )


@pytest.mark.parametrize("cap", [1, 2])
async def test_parallel_tools_wait_only_when_needed_and_complete_within_original_cap(settings, cap):
    release = asyncio.Event()
    started = asyncio.Event()
    waiting = asyncio.Event()
    grants = []

    async def ask(agent, *args, **kwargs):
        grants.append((agent, kwargs))
        assert turn.budget.accounted_usd + turn.budget.review_reserve <= cap
        started.set()
        await release.wait()
        return response(agent)

    app = coordinator(settings, ask, cap)
    app.progress = lambda event: waiting.set() if event["event"] == "delegation_wait" else None
    turn = Turn(app, "Compare sales and stock")
    turn.budget.spent_usd = 0.028476  # Actual pre-delegation spend in the reported regression.
    tools = DelegationTools(turn)
    tasks = []
    try:
        tasks.append(asyncio.create_task(tools.delegate("retail", "Sales", [])))
        await asyncio.wait_for(started.wait(), 1)
        started.clear()
        tasks.append(asyncio.create_task(tools.delegate("inventory", "Stock", [])))
        await asyncio.wait_for((waiting if cap == 1 else started).wait(), 1)
        assert len(grants) == (1 if cap == 1 else 2)
        assert not tasks[1].done()
        # Queue time must reduce the next child's deadline rather than extend the prompt.
        turn.budget.started -= 5
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 1)
        assert [result["status"] for result in results] == ["ok", "ok"]
        assert len(grants) == 2
        assert turn.budget.spent_usd == pytest.approx(0.128476)
        assert turn.budget.reserved_usd == 0
        assert app.children == {"retail": "retail-context", "inventory": "inventory-context"}
        if cap == 1:
            assert grants[1][1]["deadline_seconds"] < grants[0][1]["deadline_seconds"] - 4
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        app.reports.close()


@pytest.mark.parametrize("usage", [None, float("nan"), True, "transport_error", "cancelled"])
async def test_unknown_child_cost_wakes_waiter_without_releasing_its_reservation(settings, usage):
    release = asyncio.Event()
    started = asyncio.Event()
    waiting = asyncio.Event()
    sent = []

    async def ask(agent, *args, **kwargs):
        sent.append(agent)
        started.set()
        await release.wait()
        if usage == "transport_error":
            raise RuntimeError("Unknown remote usage")
        return response(agent, usage)

    app = coordinator(settings, ask)
    app.progress = lambda event: waiting.set() if event["event"] == "delegation_wait" else None
    turn = Turn(app, "Compare sales and stock")
    tools = DelegationTools(turn)
    tasks = []
    try:
        tasks.append(asyncio.create_task(tools.delegate("retail", "Sales", [])))
        await asyncio.wait_for(started.wait(), 1)
        tasks.append(asyncio.create_task(tools.delegate("inventory", "Stock", [])))
        await asyncio.wait_for(waiting.wait(), 1)
        if usage == "cancelled":
            tasks[0].cancel()
        else:
            release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 1)
        assert isinstance(results[1], dict)
        assert results[1]["status"] == "limit"
        assert results[1]["reason"] == "cost_budget"
        assert sent == ["retail"]
        assert turn.budget.reserved_usd == pytest.approx(0.75)
        assert tools._inflight == 0
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        app.reports.close()


async def test_waiting_for_budget_preserves_parent_review_time(settings):
    started = asyncio.Event()
    release = asyncio.Event()

    async def ask(agent, *args, **kwargs):
        started.set()
        await release.wait()
        return response(agent)

    app = coordinator(
        settings.model_copy(update={"turn_timeout_seconds": 0.15, "review_reserve_seconds": 0.05}),
        ask,
    )
    turn = Turn(app, "Compare sales and stock")
    tools = DelegationTools(turn)
    task = asyncio.create_task(tools.delegate("retail", "Sales", []))
    try:
        await asyncio.wait_for(started.wait(), 1)
        result = await asyncio.wait_for(tools.delegate("inventory", "Stock", []), 1)
        assert result["status"] == "limit"
        assert result["reason"] == "deadline"
        assert turn.budget.reserved_usd == pytest.approx(0.75)
        assert turn.budget.remaining() > 0
    finally:
        release.set()
        await task
        app.reports.close()


async def test_review_observes_actual_delegation_outcomes_in_real_adk_loop(settings):
    async def ask(agent, *args, **kwargs):
        await asyncio.sleep(0)
        return response(agent)

    app = coordinator(settings, ask)
    app.model = ScriptedModel(
        script=[
            calls(
                ("delegate", {"agent": "retail", "question": "Sales", "evidence_ids": []}),
                ("delegate", {"agent": "inventory", "question": "Stock", "evidence_ids": []}),
            ),
            finish("A scripted comparison.", ["E1", "E2"]),
        ]
    )
    reviewer = ScriptedModel(script=[verdict()])
    app.reviewer_model = reviewer
    try:
        result = await app.ask("Compare sales and stock")
        assert result.status == "approved", result.trace
        payload = json.loads(reviewer.requests[0]["contents"][0]["parts"][0]["text"])
        completed = [
            event for event in payload["delegation_execution"] if event["event"] == "delegation_end"
        ]
        assert {event["agent"] for event in completed} == {"retail", "inventory"}
        assert all(event["usage_settled"] for event in completed)
        assert 0 < payload["available_work_usd"] < 1
    finally:
        app.reports.close()
