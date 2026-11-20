"""Terminal presentation and trusted confirmation controls, without providers."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from rich.console import Console
from rich.markdown import Markdown
from typer.testing import CliRunner

from retail_agent import cli
from retail_agent.contracts import DEMO_USERS, Answer, TurnResult
from retail_agent.services.reports import ReportStore


def turn(
    markdown: str | None, *, evidence: list[dict] | None = None, preview: dict | None = None
) -> TurnResult:
    return TurnResult(
        answer=Answer("A1", markdown, ["E1"], "answer", True) if markdown is not None else None,
        status="approved" if markdown is not None else "unavailable",
        message="The model service could not complete this request." if markdown is None else "",
        trace=[],
        usage={},
        evidence=evidence or [],
        elapsed_seconds=0.1,
        deletion_preview=preview,
    )


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    output = StringIO()
    monkeypatch.setattr(
        cli, "console", Console(file=output, width=100, force_terminal=False, color_system=None)
    )
    return output


@pytest.mark.parametrize(
    "markdown",
    [
        "Revenue was **375.00**. No table requested.",
        "| Product | Revenue |\n| --- | ---: |\n| Alpha top | 200.00 |",
    ],
)
def test_display_only_renders_model_markdown_without_evidence_appendices(
    terminal: StringIO, markdown: str
) -> None:
    result = turn(
        markdown,
        evidence=[
            {
                "id": "E1",
                "rows": [{"INTERNAL_EVIDENCE_APPENDIX": 999}],
                "definitions": "Internal SQL policy should not be displayed.",
            }
        ],
    )
    cli.display(result)
    expected = StringIO()
    Console(file=expected, width=100, force_terminal=False, color_system=None).print(
        Markdown(markdown)
    )
    assert terminal.getvalue() == expected.getvalue()
    assert "INTERNAL_EVIDENCE_APPENDIX" not in terminal.getvalue()
    assert "SQL policy" not in terminal.getvalue()


def test_real_operation_receipts_are_separate_from_analytical_markdown(terminal: StringIO) -> None:
    result = turn("The report is ready.")
    assert result.answer is not None
    result.answer.receipts = [
        {
            "operation": "save",
            "status": "failed",
            "message": "Storage failed; the report was not saved.",
        }
    ]
    cli.display(result)
    assert "Storage failed; the report was not saved." in terminal.getvalue()
    assert "Saved:" not in terminal.getvalue()


def test_deletion_preview_displays_database_selection_and_exact_token(terminal: StringIO) -> None:
    preview = {
        "reports": [
            {"id": "report-one", "title": "Denim Q1"},
            {"id": "report-two", "title": "Denim Q2"},
        ],
        "token": "trusted-opaque-token",
    }
    cli.display(turn("Please review the deletion selection below.", preview=preview))
    rendered = terminal.getvalue()
    assert "report-one" in rendered and "report-two" in rendered
    assert "Denim Q1" in rendered and "Denim Q2" in rendered
    assert "Confirm: /confirm trusted-opaque-token" in rendered
    assert "permanently deleted" in rendered


def test_ask_failure_returns_nonzero_exit_and_closes_store(
    monkeypatch: pytest.MonkeyPatch, terminal: StringIO
) -> None:
    closed: list[bool] = []

    async def ask(_prompt: str) -> TurnResult:
        return turn(None)

    analyst = SimpleNamespace(ask=ask, reports=SimpleNamespace(close=lambda: closed.append(True)))
    monkeypatch.setattr(cli, "build", lambda *_args: analyst)
    result = CliRunner().invoke(cli.app, ["ask", "Summarize sales."])
    assert result.exit_code == 1
    assert "could not complete" in terminal.getvalue()
    assert closed == [True]


@pytest.mark.asyncio
async def test_new_conversation_cancels_pending_deletion_without_removing_reports(
    monkeypatch: pytest.MonkeyPatch, terminal: StringIO, tmp_path: Path
) -> None:
    store = ReportStore(tmp_path / "reports.sqlite3")
    report = store.save("alice", "Denim review", "Original report.", [], "A1")
    preview = store.preview_delete("alice", "conversation-one", "Denim")
    cleared: list[bool] = []
    analyst = SimpleNamespace(
        identity=DEMO_USERS["alice"],
        conversation_id="conversation-one",
        settings=SimpleNamespace(backend="fixture", golden_bootstrap=False),
        reports=store,
        clear_context=lambda: cleared.append(True),
        confirm_delete=lambda token: store.confirm_delete("alice", "conversation-one", token),
    )
    prompts = iter(["/new", f"/confirm {preview['token']}", "/exit"])
    monkeypatch.setattr(cli.console, "input", lambda _prompt: next(prompts))
    try:
        await cli.conversation(cast(cli.Analyst, analyst))
        assert cleared == [True]
        assert store.read("alice", report["id"]) is not None
        assert "Conversation cleared." in terminal.getvalue()
        assert '"deleted_ids": []' in terminal.getvalue()
        assert "invalid, expired or already used" in terminal.getvalue()
    finally:
        store.close()
