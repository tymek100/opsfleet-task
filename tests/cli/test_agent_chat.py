"""Explicit agent selection routes follow-ups to the intended A2A service."""

from io import StringIO

import pytest
from rich.console import Console
from typer.testing import CliRunner

from retail_insight.interfaces import agent_cli, stack_cli


@pytest.mark.parametrize("agent", ["coordinator", "retail", "inventory", "distribution"])
def test_named_agent_chat_routes_followups_and_new_conversations(agent, tmp_path, monkeypatch):
    key = tmp_path / ".artifacts/agents/secrets/a2a_signing_key"
    key.parent.mkdir(parents=True)
    key.write_text("test-signing-key")
    monkeypatch.setattr(agent_cli, "repository_root", lambda: tmp_path)
    output = StringIO()
    monkeypatch.setattr(agent_cli, "console", Console(file=output, color_system=None))
    calls = []

    class Client:
        def __init__(self, urls, token, *, signed):
            assert urls[agent] == f"http://127.0.0.1:{agent_cli.HOST_PORTS[agent]}"
            assert token == "test-signing-key" and signed

        async def ask(self, role, question, identity, context_id, **options):
            calls.append((role, question, identity, context_id, options))
            return {
                "context_id": f"context-{len(calls)}",
                "status": "approved",
                "markdown": "Done.",
            }

    monkeypatch.setattr(agent_cli, "AgentClient", Client)
    result = CliRunner().invoke(
        agent_cli.app,
        [agent, "--context-id", "previous", "--max-cost-usd", "0.5", "--deadline-seconds", "60"],
        input="/help\n/unknown\nFirst question\nFollow-up\n/new\nFresh question\n/exit\n",
    )
    assert result.exit_code == 0, result.exception
    assert [call[:4] for call in calls] == [
        (agent, "First question", "workspace", "previous"),
        (agent, "Follow-up", "workspace", "context-1"),
        (agent, "Fresh question", "workspace", None),
    ]
    assert all(call[4] == {"max_cost_usd": 0.5, "deadline_seconds": 60.0} for call in calls)
    assert agent_cli.AGENT_LABELS[agent] in output.getvalue()
    assert "test-signing-key" not in output.getvalue()
    assert "Type / for commands" in output.getvalue()
    assert "Unknown command. Use /help." in output.getvalue()
    assert "Type / to browse commands" in output.getvalue()
    assert "/reports" not in output.getvalue()


def test_agent_name_is_required_and_validated_before_connecting(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid command must not connect to a service")

    monkeypatch.setattr(agent_cli, "AgentClient", forbidden)
    runner = CliRunner()
    assert runner.invoke(agent_cli.app, ["unknown-agent"]).exit_code == 2
    help_text = runner.invoke(agent_cli.app, ["--help"])
    assert help_text.exit_code == 0
    for role in agent_cli.HOST_PORTS:
        assert role in help_text.stdout


@pytest.mark.parametrize(
    "arguments, role", [([], "coordinator"), (["--agent", "inventory"], "inventory")]
)
def test_legacy_stack_chat_uses_the_same_client(monkeypatch, arguments, role):
    calls = []
    monkeypatch.setattr(stack_cli, "run_chat", lambda *args: calls.append(args))
    result = CliRunner().invoke(stack_cli.app, ["chat", *arguments])
    assert result.exit_code == 0
    assert calls == [(role, 1.0, 180, None)]


@pytest.mark.parametrize("agent", ["coordinator", "retail", "inventory", "distribution"])
def test_interactive_agent_chat_uses_shared_prompt_session(agent, tmp_path, monkeypatch):
    key = tmp_path / ".artifacts/agents/secrets/a2a_signing_key"
    key.parent.mkdir(parents=True)
    key.write_text("test-signing-key")
    monkeypatch.setattr(agent_cli, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(agent_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setenv("TERM", "xterm-256color")
    output = StringIO()
    monkeypatch.setattr(agent_cli, "console", Console(file=output, force_terminal=True))
    questions = iter(["/help", "/new", "/quit"])
    sessions = []

    class Session:
        def prompt(self):
            return next(questions)

    def create_session(*, commands):
        sessions.append(commands)
        return Session()

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def ask(self, *args, **kwargs):
            pytest.fail("Local slash commands must never call a paid agent")

    monkeypatch.setattr(agent_cli, "create_prompt_session", create_session)
    monkeypatch.setattr(agent_cli, "AgentClient", Client)
    agent_cli.run_chat(agent)
    assert len(sessions) == 1
    assert [c.name for c in sessions[0]] == ["/help", "/new", "/exit", "/quit"]
    assert "Started a new conversation." in output.getvalue()
