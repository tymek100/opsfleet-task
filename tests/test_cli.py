from pathlib import Path

import pytest
from typer.testing import CliRunner

from retail_agent.cli import app
from retail_agent.config import Settings
from retail_agent.models import Answer
from retail_agent.render import render_answer
from retail_agent.reports import ReportStore


def test_cli_library_roundtrip_without_cloud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: Answer
) -> None:
    settings = Settings(data_dir=tmp_path, google_cloud_project="")
    monkeypatch.setattr(Settings, "load", lambda: settings)

    def token(_: int) -> str:
        return "synthetic-confirmation"

    monkeypatch.setattr("retail_agent.reports.secrets.token_urlsafe", token)
    store = ReportStore(tmp_path / "reports.sqlite3")
    rid = store.save("alice", "old", "Q1 review", answer)
    store.save("bob", "old", "Q1 private", answer)
    store.close()
    result = CliRunner().invoke(
        app,
        ["chat", "--user", "alice"],
        input=(
            "/reports\n/delete Q1\n/cancel\n/reports\n/delete Q1\n"
            "/confirm synthetic-confirmation\n/confirm synthetic-confirmation\n/reports\n/quit\n"
        ),
    )
    assert result.exit_code == 0, result.output
    assert rid in result.output and "Q1 private" not in result.output
    assert "Cancelled. Nothing deleted." in result.output
    assert "Permanently deleted 1 reports" in result.output
    assert "already used" in result.output and "No saved reports" in result.output
    store = ReportStore(tmp_path / "reports.sqlite3")
    assert store.list("alice") == [] and len(store.list("bob")) == 1
    store.close()


def test_cli_unknown_identity_rejected() -> None:
    result = CliRunner().invoke(app, ["chat", "--user", "admin"])
    assert result.exit_code != 0 and "Choose alice, bob, or ceo" in result.output


def test_renderer_uses_actual_evidence_even_if_narrative_is_wrong(answer: Answer) -> None:
    answer.text = "The model could be wrong."
    rendered = render_answer(answer)
    assert "revenue" in rendered and "100.0" in rendered
    assert "Scope: Calvin Klein" in rendered and "2026-01-01" in rendered
