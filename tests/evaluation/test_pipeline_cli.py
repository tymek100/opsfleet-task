"""CLI admission and defaults for the end-to-end workflow, without model calls."""

from types import SimpleNamespace

from typer.testing import CliRunner

from evaluation.cli import app as cli
from retail_insight.config import Settings


def test_cli_uses_default_grading_and_immediate_progress(settings, monkeypatch):
    received = {}

    async def execute(*args, **kwargs):
        received.update(kwargs)
        kwargs["progress"]("Phoenix experiment: http://localhost:6006/test")
        return SimpleNamespace(exit_code=0)

    monkeypatch.setattr(Settings, "load", lambda: settings)
    monkeypatch.setattr("evaluation.runners.pipeline.run_pipeline", execute)
    monkeypatch.setattr("evaluation.graders.judge.GeminiJudge", lambda *args, **kwargs: object())
    result = CliRunner().invoke(
        cli,
        [
            "run",
            "--max-cost-usd",
            "1",
            "--deadline-seconds",
            "30",
            "--allow-unreviewed",
            "--phoenix-url",
            "http://127.0.0.1:6007",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Phoenix experiment:" in result.output
    assert received["grade_candidates"] and received["repetitions"] == 1


def test_invalid_configuration_is_incomplete_without_exposing_inputs(settings, monkeypatch):
    monkeypatch.setattr(Settings, "load", lambda: settings)
    result = CliRunner().invoke(
        cli,
        [
            "run",
            "--max-cost-usd",
            "1",
            "--deadline-seconds",
            "30",
            "--allow-unreviewed",
            "--phoenix-url",
            "http://user:secret-canary@localhost:6006",
        ],
    )
    assert result.exit_code == 2
    assert "Invalid evaluation configuration" in result.output
    assert "secret-canary" not in result.output


def test_unknown_suite_reports_setup_error_before_credentials_lookup():
    result = CliRunner().invoke(
        cli, ["run", "--suite", "nonexistent", "--max-cost-usd", "1", "--deadline-seconds", "30"]
    )
    assert result.exit_code == 2
    assert "Unknown suite" in result.output
