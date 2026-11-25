"""Human-visible CLI contracts with real rendering and a scripted ADK agent."""

from io import StringIO

import pytest
from rich.console import Console
from typer.testing import CliRunner

from retail_insight.contracts import Answer, TurnResult
from retail_insight.interfaces import cli
from tests.support.models import finish, verdict


@pytest.fixture
def output(monkeypatch):
    stream = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=stream, width=100, color_system=None))
    return stream


def test_display_renders_only_model_markdown_and_real_receipts(output):
    result = TurnResult(
        Answer(
            "A1",
            "Revenue is **65.65**.",
            ["E1"],
            "answer",
            True,
            [{"status": "saved", "title": "Quarterly", "id": "report-id"}],
        ),
        "approved",
        "",
        [],
        {},
        [{"id": "E1", "rows": [{"secret_debug": 123}]}],
        0.1,
    )
    cli.display(result)
    rendered = output.getvalue()
    assert "Revenue is 65.65." in rendered
    assert "Saved: Quarterly (report-id)" in rendered
    assert "secret_debug" not in rendered and "[E1]" not in rendered


async def test_piped_conversation_has_one_blank_line_after_question_and_before_next_prompt(
    make_agent, output, monkeypatch
):
    app = make_agent([finish("Which quarter?", outcome="clarification")], [verdict()])
    monkeypatch.setattr("sys.stdin", StringIO("Compare revenue.\n/exit\n"))
    await cli.conversation(app)
    rendered = output.getvalue()
    assert "Reports save only on request.\nData:" in rendered
    lines = [line.rstrip() for line in rendered.splitlines()]
    index = lines.index("Which quarter?")
    assert lines[index - 1] == "You>"
    assert lines[index + 1 : index + 3] == ["", "You>"]
    assert "Which quarter?" in rendered and len(app.model.requests) == 1


def test_status_timer_advances_without_events_and_detail_changes_independently(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(cli, "monotonic", lambda: now[0])
    status = cli._QuestionStatus(started=100)
    assert status.__rich__().plain == "Elapsed: 0s | Status: Considering your question..."
    now[0] += 7
    assert "Elapsed: 7s" in status.__rich__().plain
    status.detail = "Reviewing the answer..."
    assert status.__rich__().plain == "Elapsed: 7s | Status: Reviewing the answer..."
    next_question = cli._QuestionStatus(started=now[0])
    assert "Elapsed: 0s" in next_question.__rich__().plain


async def test_run_question_restores_original_callback_after_completion(make_agent, output):
    app = make_agent([finish("Which year?", outcome="clarification")], [verdict()])
    events = []
    callback = events.append
    app.progress = callback
    result = await cli.run_question(app, "Compare Q1.")
    assert result.status == "approved"
    assert app.progress is callback
    assert events == []


def test_ask_failure_returns_nonzero_and_closes_storage(make_agent, monkeypatch):
    app = make_agent([finish("Unsupported claim.")], [verdict("stop")])
    monkeypatch.setattr(cli, "build", lambda *_args: app)
    result = CliRunner().invoke(cli.app, ["ask", "Describe revenue."])
    assert result.exit_code == 1
    import sqlite3

    with pytest.raises(sqlite3.ProgrammingError):
        app.reports.db.execute("SELECT 1")


async def test_new_command_cancels_pending_delete_and_preserves_saved_reports(
    make_agent, output, monkeypatch
):
    app = make_agent()
    report = app.reports.save("alice", "Quarterly", "Historical report.", [], "A1")
    previous_conversation = app.conversation_id
    token = app.reports.preview_delete("alice", previous_conversation, "")["token"]
    monkeypatch.setattr("sys.stdin", StringIO("/new\n/exit\n"))
    await cli.conversation(app)
    assert app.history == [] and app.results == {} and app.answers == {}
    assert (
        app.reports.confirm_delete("alice", previous_conversation, token)["status"]
        == "invalid_confirmation"
    )
    assert app.reports.read("alice", report["id"]) is not None
