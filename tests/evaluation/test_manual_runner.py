"""Real ADK capture, isolated reports, and shared limits for authored conversations."""

import asyncio
import json

import pytest

from evaluation.runners.artifacts import digest, read_json
from evaluation.runners.manual import InitialReport, Scenario, run_manual
from retail_insight.agents.retail.agent import RetailAnalyst as Analyst
from tests.support.models import ScriptedModel, finish, verdict


def scenario(name="scenario-01"):
    return Scenario(
        id=name,
        prompt="What was our revenue?",
        follow_up="Use Q1 2026.",
        intent="HARNESS_ONLY_REFERENCE_CANARY",
        checks=["HARNESS_ONLY_ACCEPTANCE_CANARY"],
    )


def test_archived_scenario_ignores_retired_retrieval_setting():
    archived = {**scenario().model_dump(), "golden_enabled": True}
    loaded = Scenario.model_validate(archived)
    assert loaded.prompt == scenario().prompt
    assert "golden_enabled" not in loaded.model_dump()


async def test_capture_preserves_followup_context_but_isolates_cases_and_reference_metadata(
    settings, tmp_path
):
    models, allowances, directories = [], [], []

    def factory(config, identity, **kwargs):
        def respond(_):
            allowances.append(app.settings.question_budget_usd)
            return finish("Which reporting period?", outcome="clarification")

        model = ScriptedModel(script=[respond, respond])
        models.append(model)
        directories.append(config.data_dir)
        app = Analyst(
            config,
            identity,
            model=model,
            reviewer_model=ScriptedModel(script=[verdict(), verdict()]),
            **kwargs,
        )
        return app

    first = scenario()
    first.initial_reports = [
        InitialReport(owner="workspace", title="Owned", markdown="Owned test report"),
        InitialReport(owner="archived-workspace", title="Private", markdown="Other owner's report"),
    ]
    run = await run_manual(
        [first, scenario("scenario-02")],
        settings,
        output_root=tmp_path / "runs",
        backend="fixture",
        max_cost_usd=2,
        deadline_seconds=60,
        app_factory=factory,
        progress=lambda _: None,
    )
    state = read_json(run / "progress.json")
    assert state["status"] == "captured" and state["executed_turns"] == 4
    assert len(set(directories)) == 2 and all(not path.exists() for path in directories)
    first_turn = read_json(run / "cases/scenario-01/turn-1.json")
    followup = read_json(run / "cases/scenario-01/turn-2.json")
    next_case = read_json(run / "cases/scenario-02/turn-1.json")
    assert first_turn["context"]["prior_approved_conversation"] == []
    assert len(followup["context"]["prior_approved_conversation"]) == 1
    assert next_case["context"]["prior_approved_conversation"] == []
    assert len(first_turn["reports_before"]) == 2 and next_case["reports_before"] == []
    assert first_turn["timeline"][-1]["event"] == "turn_result"
    assert any(event["event"] == "tool_call" for event in first_turn["timeline"])
    assert allowances[1] == pytest.approx(2 - first_turn["usage"]["accounted_usd"])
    assert all(digest(run / name) == value for name, value in state["turn_hashes"].items())
    sent = json.dumps([model.requests for model in models])
    assert "HARNESS_ONLY" not in sent
    assert "offline-placeholder" not in (run / "manifest.json").read_text()
    assert (run / "cases/scenario-01/transcript.md").read_text().count("**User:**") == 2
    manifest = read_json(run / "manifest.json")
    assert manifest["data_source"]["fixture_sha256"] == digest(run / "data/warehouse.sql")


async def test_expired_shared_deadline_records_all_unexecuted_turns(settings, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("No model construction after deadline")

    run = await run_manual(
        [scenario()],
        settings,
        output_root=tmp_path / "runs",
        backend="fixture",
        max_cost_usd=1,
        deadline_seconds=1e-12,
        app_factory=forbidden,
        progress=lambda _: None,
    )
    state = read_json(run / "progress.json")
    assert state["status"] == "incomplete" and state["accounted_usd"] == 0
    assert state["captured_turns"] == 2 and state["executed_turns"] == 0
    assert all(
        read_json(path)["status"] == "NOT_EXECUTED"
        for path in (run / "cases/scenario-01").glob("turn-*.json")
    )


async def test_interruption_preserves_partial_capture_and_unknown_usage_reservation(
    settings, tmp_path
):
    class CancelledAnalyst(Analyst):
        async def ask(self, question):
            raise asyncio.CancelledError()

    def factory(config, identity, **kwargs):
        return CancelledAnalyst(
            config,
            identity,
            model=ScriptedModel(script=[asyncio.CancelledError()]),
            reviewer_model=ScriptedModel(script=[]),
            **kwargs,
        )

    with pytest.raises(asyncio.CancelledError):
        await run_manual(
            [scenario()],
            settings,
            output_root=tmp_path / "runs",
            backend="fixture",
            max_cost_usd=1,
            deadline_seconds=60,
            app_factory=factory,
            progress=lambda _: None,
        )
    run = next((tmp_path / "runs").iterdir())
    state = read_json(run / "progress.json")
    assert state["status"] == "interrupted" and state["accounted_usd"] == 1
    turn = read_json(run / "cases/scenario-01/turn-1.json")
    assert turn["status"] == "ERROR" and turn["usage"]["usage_unknown"]
