"""CLI admission and defaults for the end-to-end workflow, without model calls."""

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from evaluation.cli import app as cli
from retail_insight.config import Settings


@pytest.mark.parametrize(
    "budget_args, expected",
    [([], 5.0), (["--max-cost-usd", "5"], 5.0), (["--max-cost-usd", "0.5"], 0.5)],
)
def test_cli_uses_default_grading_and_immediate_progress(
    settings, monkeypatch, budget_args, expected
):
    received = {}

    async def execute(*args, **kwargs):
        received.update(kwargs)
        kwargs["progress"]("Foundry experiment: https://ai.azure.com/test")
        return SimpleNamespace(exit_code=0)

    monkeypatch.setattr(Settings, "load", lambda: settings)
    monkeypatch.setattr("evaluation.runners.pipeline.run_pipeline", execute)
    monkeypatch.setattr("evaluation.graders.judge.GeminiJudge", lambda *args, **kwargs: object())
    result = CliRunner().invoke(
        cli,
        [
            "run",
            *budget_args,
            "--deadline-seconds",
            "30",
            "--allow-unreviewed",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Foundry experiment:" in result.output
    assert received["grade_candidates"] and received["repetitions"] == 1
    assert received["max_cost_usd"] == expected


def test_unknown_suite_reports_setup_error_before_credentials_lookup():
    result = CliRunner().invoke(
        cli, ["run", "--suite", "nonexistent", "--max-cost-usd", "1", "--deadline-seconds", "30"]
    )
    assert result.exit_code == 2
    assert "Unknown suite" in result.output


@pytest.mark.parametrize(
    "command", ["run", "run-conversations", "run-multi-agent", "grade", "calibrate"]
)
@pytest.mark.parametrize("value", ["5.01", "40", "nan", "inf", "0"])
def test_cli_rejects_invalid_budget_before_credentials_or_provider(
    command, value, monkeypatch, tmp_path
):
    def forbidden():
        raise AssertionError("Budget rejection must precede settings and credentials lookup")

    monkeypatch.setattr(Settings, "load", forbidden)
    args = [command, "--max-cost-usd", value, "--deadline-seconds", "30"]
    if command == "grade":
        args += ["--run", str(tmp_path)]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 2, result.output
    assert "--max-cost-usd" in result.output


def test_multiagent_defaults_to_five_dollars_and_one_conversation(monkeypatch):
    received = {}

    async def execute(**kwargs):
        received.update(kwargs)
        return "offline-artifacts", 0

    monkeypatch.setattr("evaluation.multi_agent.runner.run", execute)
    result = CliRunner().invoke(cli, ["run-multi-agent"])
    assert result.exit_code == 0, result.output
    assert received["max_cost_usd"] == 5
    assert received["concurrency"] == 1
