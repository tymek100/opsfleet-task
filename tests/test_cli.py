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
    rendered = render_answer(answer, details=True)
    assert "revenue" in rendered and "100.0" in rendered
    assert "Scope: Calvin Klein" in rendered and "2026-01-01" in rendered


def test_default_summary_hides_diagnostics_and_details_renders_table(answer: Answer) -> None:
    from io import StringIO

    from rich.console import Console

    from retail_agent.render import display_answer

    summary = render_answer(answer)
    assert "SQL hash" not in summary and "/details" in summary
    stream = StringIO()
    display_answer(Console(file=stream, width=150, color_system=None), answer, details=True)
    output = stream.getvalue()
    assert "100.0" in output and "revenue" in output and "SQL hash" in output


def test_cli_storage_failure_is_actionable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, google_cloud_project="")
    monkeypatch.setattr(Settings, "load", lambda: settings)
    (tmp_path / "reports.sqlite3").mkdir()
    result = CliRunner().invoke(app, ["chat"])
    assert result.exit_code == 1
    assert "Cannot open local report storage" in result.output
    assert "Traceback" not in result.output


def test_clear_is_screen_only_and_requires_slash(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, answer: Answer
) -> None:
    from unittest.mock import Mock

    from retail_agent.agent import Analyst
    from retail_agent.cli import command, console
    from retail_agent.models import DEMO_USERS, AppError
    from tests.fixture_data import FixtureExecutor

    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "existing")
    analyst.history.append({"question": "Q1 revenue", "answer": "verified"})
    analyst.last_answer = answer
    rid = store.save("alice", "existing", "Q1", answer)
    clear_screen = Mock()
    monkeypatch.setattr(console, "clear", clear_screen)

    assert command("/clear", analyst) == ""
    clear_screen.assert_called_once_with()
    assert analyst.conversation == "existing"
    assert analyst.history == [{"question": "Q1 revenue", "answer": "verified"}]
    assert analyst.last_answer is answer
    assert store.read("alice", rid) == answer
    assert command("clear", analyst) is None
    with pytest.raises(AppError, match="without arguments"):
        command("/clear everything", analyst)
    clear_screen.assert_called_once_with()


def test_cli_suppresses_only_known_adk_notice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import warnings

    from retail_agent.agent import Analyst

    settings = Settings(data_dir=tmp_path, google_cloud_project="")
    monkeypatch.setattr(Settings, "load", lambda: settings)
    notice = "[EXPERIMENTAL] feature FeatureName.JSON_SCHEMA_FOR_FUNC_DECL is enabled."

    async def emit_warnings(analyst: Analyst) -> None:
        del analyst
        for message, module in (
            (notice, "google.adk.tools.set_model_response_tool"),
            ("Another ADK warning", "google.adk.tools.set_model_response_tool"),
            (notice, "another_library"),
        ):
            warnings.warn_explicit(message, UserWarning, "fixture.py", 1, module=module)

    monkeypatch.setattr("retail_agent.cli.chat_loop", emit_warnings)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = CliRunner().invoke(app, ["chat"])
        assert result.exit_code == 0, result.output
        assert [str(w.message) for w in captured] == ["Another ADK warning", notice]
        # The CLI's filter is restored on exit, even for the identical ADK notice.
        warnings.warn_explicit(
            notice,
            UserWarning,
            "fixture.py",
            1,
            module="google.adk.tools.set_model_response_tool",
        )
        assert len(captured) == 3


def test_rate_limit_is_red_without_adk_tracebacks_and_chat_continues(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    from collections.abc import AsyncGenerator

    from google.adk.models.google_llm import Gemini
    from google.adk.models.llm_request import LlmRequest
    from google.adk.models.llm_response import LlmResponse
    from google.genai import errors
    from rich.console import Console

    calls = 0

    async def limited(
        self: Gemini, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        nonlocal calls
        del self, llm_request, stream
        calls += 1
        raise errors.ClientError(
            429,
            {
                "error": {
                    "message": "PRIVATE_PROVIDER_DETAIL",
                    "details": [{"retryDelay": "200s"}],
                }
            },
        )
        yield LlmResponse()  # pragma: no cover

    monkeypatch.setattr(Settings, "load", lambda: settings)
    monkeypatch.setattr(Gemini, "generate_content_async", limited)
    monkeypatch.setattr(
        "retail_agent.cli.console",
        Console(
            force_terminal=True,
            no_color=False,
            color_system="standard",
            width=160,
            markup=False,
        ),
    )
    result = CliRunner().invoke(
        app,
        ["chat"],
        input="Q1 2026 revenue?\n/help\n/quit\n",
        color=True,
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("Gemini rate limit reached") == 1
    assert "\x1b[1;31m" in result.output
    assert "Traceback" not in result.output and "Node execution failed" not in result.output
    assert "Root node" not in result.output and "PRIVATE_PROVIDER_DETAIL" not in result.output
    assert "Show commands" in result.output and calls == 1
    log = (settings.data_dir / "events.log").read_text()
    assert '"error": "rate_limit"' in log and "PRIVATE_PROVIDER_DETAIL" not in log


def test_controlled_error_filter_preserves_unexpected_errors_and_is_restored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from retail_agent.models import RateLimitError
    from retail_agent.observability import quiet_controlled_adk_errors

    logger = logging.getLogger("google_adk.google.adk.workflow._node_runner")
    with quiet_controlled_adk_errors():
        try:
            raise RateLimitError()
        except RateLimitError:
            logger.exception("handled")
        try:
            raise RuntimeError("synthetic unexpected failure")
        except RuntimeError:
            logger.exception("unexpected")
    assert [record.message for record in caplog.records] == ["unexpected"]
    try:
        raise RateLimitError()
    except RateLimitError:
        logger.exception("outside CLI")
    assert caplog.records[-1].message == "outside CLI"


@pytest.mark.parametrize("existing_title", [None, "Other review", "Winter review v2"])
def test_natural_deletion_preview_matches_library_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: Answer, existing_title: str | None
) -> None:
    from tests.test_planning import Provider

    settings = Settings(data_dir=tmp_path, google_cloud_project="")
    monkeypatch.setattr(Settings, "load", lambda: settings)
    Provider(monkeypatch, [{"route": "delete_preview", "match": "Winter review v2"}])
    store = ReportStore(tmp_path / "reports.sqlite3")
    if existing_title:
        store.save("alice", "old", existing_title, answer)
    store.save("bob", "old", "Winter review v2", answer)
    store.close()
    result = CliRunner().invoke(
        app,
        ["chat", "--user", "alice"],
        input='Prepare a deletion preview for my saved report titled "Winter review v2".\n/quit\n',
    )
    assert result.exit_code == 0, result.output
    output = " ".join(result.output.split())
    store = ReportStore(tmp_path / "reports.sqlite3")
    try:
        assert len(store.list("alice")) == int(existing_title is not None)
        assert len(store.list("bob")) == 1
        pending = store.db.execute("SELECT count(*) FROM pending").fetchone()[0]
        if existing_title == "Winter review v2":
            assert "PERMANENT DELETION PREVIEW" in output
            assert output.count("/confirm ") == 1
            assert pending == 1
        else:
            assert output.count("No matching reports") == 1
            assert "Use /reports to see your saved reports." in output
            assert "Deletion preview prepared" not in output
            assert "/confirm" not in output and "confirmation token" not in output
            assert pending == 0
    finally:
        store.close()
