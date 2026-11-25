"""Shared evaluation admission across references, A2A calls and independent judges."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from evaluation.multi_agent import runner
from evaluation.multi_agent.oracle import Snapshot
from retail_insight.config import Settings


async def test_partial_reservation_waits_for_concurrent_usage_then_reuses_actual_remainder():
    budget = runner.RunBudget(2)
    budget.used = 0.1  # BigQuery reference capture already billed.
    first = await budget.reserve_up_to(2)
    assert first == pytest.approx(1.9)
    waiting = asyncio.create_task(budget.reserve_up_to(2))
    await asyncio.sleep(0)
    assert not waiting.done()
    await budget.settle(first, 0.2)
    second = await asyncio.wait_for(waiting, timeout=1)
    assert second == pytest.approx(1.7)
    assert budget.used + budget.reserved <= 2
    await budget.settle(second, None)
    assert budget.used == pytest.approx(2)
    assert await budget.reserve_up_to(0.65) == 0


async def test_expired_budget_refuses_even_a_small_affordable_operation():
    budget = runner.RunBudget(2, deadline=0)
    assert await budget.reserve_up_to(0.1) == 0
    assert not await budget.reserve(0.1)
    assert budget.reserved == 0


@pytest.mark.parametrize("cap", [2.01, 40, float("nan"), float("inf"), 0])
async def test_direct_runner_rejects_invalid_budget_before_setup(monkeypatch, cap):
    def forbidden():
        raise AssertionError("No configuration or provider work before budget validation")

    monkeypatch.setattr(Settings, "load", forbidden)
    with pytest.raises(ValueError, match="at most \\$2"):
        await runner.run(max_cost_usd=cap)


@pytest.mark.parametrize("unknown_usage", [False, True])
async def test_two_dollar_run_counts_snapshot_agents_and_both_judges(
    settings, monkeypatch, tmp_path, unknown_usage
):
    snapshot = Snapshot.load(runner.HERE / "fixture.json")
    snapshot.capture_cost_usd = 0.1
    capture_limits = []
    grants = []

    def capture(*args, **kwargs):
        capture_limits.append(kwargs["max_cost_usd"])
        assert kwargs["deadline"] > 0
        return snapshot

    async def preflight(*args):
        return {}

    async def ask(*args, **kwargs):
        grants.append(kwargs["max_cost_usd"])
        return {
            "status": "approved",
            "markdown": "Offline scripted answer",
            "context_id": "same-conversation",
            "trace": [{"event": "scripted"}],
            "usage": {} if unknown_usage else {"accounted_usd": 0.2},
        }

    class Judge:
        def __init__(self, *args, **kwargs):
            assert not unknown_usage, "Unknown agent usage exhausts the cap; no judge may run"
            assert kwargs["max_cost_usd"] <= 2
            self.accounted_usd = 0.0
            self.calls = []

        async def close(self):
            pass

    async def grade(raw, prompt, number, reference, judge, prior):
        judge.accounted_usd = 0.1
        return {"status": "PASS", "scores": []}

    async def trajectory(role, case, turns, judge):
        judge.accounted_usd = 0.1
        return {"status": "PASS", "scores": []}

    publisher = SimpleNamespace(url="http://localhost:6006/offline", record=lambda *a, **kw: None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "load", lambda: settings)
    monkeypatch.setattr(runner, "ensure_phoenix", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "client_for", lambda *a, **kw: None)
    monkeypatch.setattr(
        runner, "configure_tracing", lambda *a, **kw: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(runner, "provenance", lambda: {})
    monkeypatch.setattr(runner, "preflight", preflight)
    monkeypatch.setattr(runner, "Publisher", lambda *a: publisher)
    monkeypatch.setattr(runner, "GeminiJudge", Judge)
    monkeypatch.setattr(runner, "grade", grade)
    monkeypatch.setattr("evaluation.multi_agent.snapshot.capture", capture)
    monkeypatch.setattr("evaluation.multi_agent.trajectory.evaluate", trajectory)
    monkeypatch.setattr(
        "retail_insight.a2a.client.AgentClient", lambda **kw: SimpleNamespace(ask=ask)
    )

    directory, code = await runner.run(
        suite="coordinator", only="scenario-01", backend="bigquery", token="offline-token"
    )
    manifest = json.loads((directory / "manifest.json").read_text())
    assert code == (2 if unknown_usage else 0)
    assert capture_limits == [2]
    assert grants == pytest.approx([1.9] if unknown_usage else [1.9, 1.6])
    assert manifest["max_cost_usd"] == 2
    assert manifest["reference_capture_cost_usd"] == 0.1
    assert manifest["accounted_usd"] == pytest.approx(2 if unknown_usage else 0.8)
    assert manifest["planned_turns"] == 2
    if unknown_usage:
        assert manifest["turn_counts"] == {"ERROR": 2}
        follow_up = json.loads((directory / "coordinator/scenario-01/turn-2.json").read_text())
        assert follow_up["status"] == "NOT_EXECUTED"
