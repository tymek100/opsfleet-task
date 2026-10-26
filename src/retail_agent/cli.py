"""Local CLI; explicit save and confirmation remain outside the model."""

import asyncio
import logging
import sqlite3
import sys
import warnings
from contextlib import suppress
from uuid import uuid4

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console

from retail_agent.agent import Analyst
from retail_agent.bigquery import BigQueryExecutor
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, AppError
from retail_agent.observability import quiet_controlled_adk_errors
from retail_agent.render import display_answer, render_answer, render_preview
from retail_agent.reports import ReportStore

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
console = Console(markup=False)
HELP = """/help                         Show commands
/clear                        Clear the screen; keep conversation context
/save TITLE                   Explicitly save the latest successful analysis
/reports                      List your private reports
/read ID                      Read your report
/details [ID]                 Show source tables and diagnostics for latest analysis or report
/delete TEXT                  Preview literal matching reports (/delete * = all)
/delete-conversation          Preview this conversation's reports
/confirm TOKEN                Permanently delete the previewed set
/cancel                       Cancel pending deletion
/new                          Clear context and start a new conversation
/quit                         Exit
Use Up/Down arrows to recall prompts and commands from this CLI session.
Natural-language analysis and deletion previews also supported. Demo identity is fixed at startup."""


@app.command()
def users() -> None:
    """List the explicitly simulated local identities."""
    for identity in DEMO_USERS.values():
        console.print(f"{identity.user_id}: {identity.scope}")


@app.command()
def doctor() -> None:
    """Check configuration presence without exposing secrets or making provider calls."""
    settings = Settings.load()
    console.print(f"Project configured: {bool(settings.google_cloud_project)}")
    console.print(f"Gemini key configured: {bool(settings.gemini_api_key.get_secret_value())}")
    console.print(f"Model: {settings.gemini_model}")
    console.print("This checks presence only. Live checks require credentials and internet access.")


def command(text: str, analyst: Analyst) -> str | None:
    """Deterministic command dispatch; no provider is needed for report confirmation."""
    user, conversation, store = analyst.identity.user_id, analyst.conversation, analyst.store
    verb, _, arg = text.partition(" ")
    arg = arg.strip()
    if verb == "/help":
        return HELP
    if verb == "/clear":
        if arg:
            raise AppError("Use /clear without arguments.")
        console.clear()
        return ""
    if verb == "/reports":
        return "\n".join(f"{r.id} | {r.title}" for r in store.list(user)) or "No saved reports."
    if verb == "/save":
        if not arg or analyst.last_answer is None:
            raise AppError("Use /save TITLE after a successful analysis.")
        rid = store.save(user, conversation, arg, analyst.last_answer)
        return f"Saved report {rid}."
    if verb == "/details":
        answer = store.read(user, arg) if arg else analyst.last_answer
        if answer is None:
            raise AppError("No analysis is available yet.")
        return render_answer(answer, details=True)
    if verb == "/read":
        return render_answer(store.read(user, arg))
    if verb in ("/delete", "/delete-conversation"):
        if verb == "/delete" and not arg:
            raise AppError("Use /delete TEXT or /delete * for all your reports.")
        analyst.preview = store.preview(
            user,
            conversation,
            "" if arg == "*" else arg,
            conversation_only=verb == "/delete-conversation",
        )
        return render_preview(analyst.preview)
    if verb == "/cancel":
        store.cancel(user, conversation)
        analyst.preview = None
        return "Cancelled. Nothing deleted."
    if verb == "/confirm":
        count = store.confirm(user, conversation, arg)
        analyst.reset_context()
        return f"Permanently deleted {count} reports. Conversation context cleared."
    if verb == "/new":
        store.cancel(user, conversation)
        analyst.reset_context()
        analyst.conversation = uuid4().hex[:12]
        return f"New conversation: {analyst.conversation}"
    if text.startswith("/"):
        raise AppError("Unknown command. Use /help.")
    return None


@app.command()
def chat(user: str = typer.Option("alice", help="Simulated identity: alice, bob, ceo")) -> None:
    """Start a local chat using Gemini and read-only BigQuery queries."""
    if user not in DEMO_USERS:
        raise typer.BadParameter("Choose alice, bob, or ceo.")
    settings = Settings.load()
    logging.getLogger("google").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    try:
        executor = BigQueryExecutor(settings.google_cloud_project)
    except Exception:
        console.print(
            "BigQuery credentials unavailable. Run gcloud auth application-default login."
        )
        raise typer.Exit(1) from None
    try:
        store = ReportStore(settings.data_dir / "reports.sqlite3")
    except (sqlite3.Error, OSError):
        console.print("Cannot open local report storage. Check disk space and permissions.")
        raise typer.Exit(1) from None
    analyst = Analyst(settings, DEMO_USERS[user], executor, store, uuid4().hex[:12])
    console.print(f"Retail assistant — DEMO identity: {user}; scope: {analyst.identity.scope}")
    console.print(
        f"Conversation: {analyst.conversation}. /help for commands. Reports save only on request."
    )
    try:
        with quiet_controlled_adk_errors(), warnings.catch_warnings():
            # Keep this known ADK notice out of interactive output only. Other
            # warnings and direct runtime/test usage retain their usual behavior.
            warnings.filterwarnings(
                "ignore",
                message=r"^\[EXPERIMENTAL\] feature FeatureName\.JSON_SCHEMA_FOR_FUNC_DECL is enabled\.$",
                category=UserWarning,
                module=r"^google\.adk\.",
            )
            asyncio.run(chat_loop(analyst))
    finally:
        with suppress(sqlite3.Error, OSError):
            store.close()


async def chat_loop(analyst: Analyst) -> None:
    # Keep input history local to this CLI process; piped input needs no terminal editor.
    session = (
        PromptSession[str](history=InMemoryHistory())
        if sys.stdin.isatty() and console.is_terminal
        else None
    )
    while True:
        try:
            text = (
                await session.prompt_async("\nYou> ")
                if session is not None
                else console.input("\nYou> ")
            ).strip()
            if text in ("/quit", "/exit"):
                break
            if not text:
                continue
            verb, _, arg = text.partition(" ")
            if verb in ("/details", "/read"):
                answer = (
                    analyst.store.read(analyst.identity.user_id, arg.strip())
                    if arg.strip()
                    else analyst.last_answer
                    if verb == "/details"
                    else None
                )
                if answer is None:
                    raise AppError("Provide a report ID or run an analysis first.")
                display_answer(console, answer, details=verb == "/details")
                continue
            response = command(text, analyst)
            if response is not None:
                console.print(response)
                continue
            with console.status("Generating answer…"):
                answer = await analyst.ask(text)
            display_answer(console, answer)
            if analyst.preview is not None:
                console.print(render_preview(analyst.preview))
        except (EOFError, KeyboardInterrupt):
            break
        except AppError as exc:
            console.print(
                f"Unable to complete: {exc}", style="bold red", markup=False, highlight=False
            )
        except OSError:
            console.print(
                "Local files are unavailable. Check disk access; you can continue chatting."
            )
        except sqlite3.Error:
            console.print(
                "Local storage failed. The operation was not confirmed; check disk access."
            )


if __name__ == "__main__":
    app()
