"""Run/grade separation, state isolation, and fresh per-prompt allowances."""

import json

import pytest
from rich.text import Text
from typer.testing import CliRunner

from evaluation.cli import app as cli
from evaluation.data import load_cases
from evaluation.graders.runner import grade_run
from evaluation.runners.artifacts import frozen_cases, read_json
from evaluation.runners.conversation import run_cases
from retail_insight.agents.retail.agent import RetailAnalyst as Analyst
from tests.support.models import ScriptedModel, calls, finish, verdict


async def test_real_runtime_capture_and_frozen_regrade(settings, tmp_path):
    case = load_cases("totals-q1")[0]
    models = []

    def factory(config, identity, **kwargs):
        model = ScriptedModel(
            script=[
                calls(
                    (
                        "query_data",
                        {
                            "sql": "SELECT SUM(sale_price) AS revenue FROM sales WHERE brand = 'Calvin Klein' AND purchased_at >= TIMESTAMP '2026-01-01' AND purchased_at < TIMESTAMP '2026-04-01'",
                            "purpose": "Measure revenue",
                        },
                    )
                ),
                finish("Qualifying revenue was 798 [E1].", ["E1"]),
            ]
        )
        models.append(model)
        return Analyst(
            config,
            identity,
            model=model,
            reviewer_model=ScriptedModel(script=[verdict()]),
            **kwargs,
        )

    run = await run_cases(
        [case],
        settings,
        artifact_root=tmp_path / "runs",
        suite="control",
        repetitions=2,
        max_cost_usd=2,
        deadline_seconds=60,
        app_factory=factory,
        progress=lambda _: None,
    )
    manifest = read_json(run / "manifest.json")
    assert manifest["completed_trials"] == 2
    trials = [read_json(p) for p in sorted((run / "trials").glob("*.json"))]
    assert all(t["turns"][0]["status"] == "approved" for t in trials)
    assert all(
        t["turns"][0]["observations"][0]["result"]["rows"] == [{"revenue": 798.0}] for t in trials
    )
    assert all(t["turns"][0]["candidates"][0]["review"]["decision"] == "approve" for t in trials)
    assert trials[0]["turns"][0]["context"]["prior_approved_conversation"] == []
    assert "offline-placeholder" not in (run / "manifest.json").read_text()
    sent = json.dumps(models[0].requests)
    assert "reference_answer" not in sent and "source_key" not in sent
    before = [len(model.requests) for model in models]
    grade = await grade_run(run, grade_candidates=False, progress=lambda _: None)
    assert [len(model.requests) for model in models] == before
    assert read_json(grade / "summary.json")["statuses"] == {"UNJUDGEABLE": 2}
    frozen = frozen_cases(run)
    assert frozen[0] == case
    path = next((run / "fixtures").glob("*.sql"))
    path.write_text(path.read_text() + "\n-- changed\n")
    with pytest.raises(ValueError, match="modified"):
        frozen_cases(run)


async def test_run_limit_keeps_unexecuted_trials(settings, tmp_path):
    invoked = []

    def factory(*args, **kwargs):
        invoked.append(True)
        raise AssertionError("Deadline should prevent construction")

    run = await run_cases(
        load_cases("totals-q1"),
        settings,
        artifact_root=tmp_path,
        suite="control",
        repetitions=3,
        max_cost_usd=1,
        deadline_seconds=1e-12,
        app_factory=factory,
        progress=lambda _: None,
    )
    assert not invoked
    assert all(read_json(p)["status"] == "NOT_EXECUTED" for p in (run / "trials").glob("*.json"))
    grade = await grade_run(run, progress=lambda _: None)
    summary = read_json(grade / "summary.json")
    assert summary["planned"] == 3 and summary["not_executed"] == 3
    assert summary["task_success_over_planned"]["denominator"] == 3
    assert summary["repetition_group_coverage"]["numerator"] == 0


def test_cli_requires_explicit_live_limits_and_pilot_acknowledgment():
    runner = CliRunner()
    assert runner.invoke(cli, ["run"]).exit_code != 0
    result = runner.invoke(cli, ["run", "--max-cost-usd", "1", "--deadline-seconds", "60"])
    assert result.exit_code != 0
    assert "--allow-unreviewed" in Text.from_ansi(result.output).plain
    assert runner.invoke(cli, ["validate"]).exit_code == 0
