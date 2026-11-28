from io import StringIO
from unittest.mock import Mock

from rich.console import Console
from typer.testing import CliRunner

from retail_insight import cli
from retail_insight.agent import RetailAgent
from retail_insight.cli import app, handle_command


def test_cli_commands_need_no_external_services():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0 and "chat" in result.output


def test_save_never_overwrites_and_new_clears_state(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "console", Console(file=StringIO()))
    agent = Mock(spec=RetailAgent)
    path = tmp_path / "report.md"
    handle_command(f"/save {path}", agent, "First answer")
    assert path.read_text() == "First answer\n"
    handle_command(f"/save {path}", agent, "Second answer")
    assert path.read_text() == "First answer\n"
    assert handle_command("/new", agent, "First answer") == ""
    agent.reset.assert_called_once()
