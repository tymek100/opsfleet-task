"""Local CLI; explicit save and confirmation remain outside the model."""

import asyncio
import logging
import sqlite3
from uuid import uuid4

import typer
from rich.console import Console

from retail_agent.agent import Analyst
from retail_agent.bigquery import BigQueryExecutor
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, AppError
from retail_agent.render import render_answer, render_preview
from retail_agent.reports import ReportStore

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
console = Console(markup=False)
HELP = """/help                         Show commands
/save TITLE                   Explicitly save the latest successful analysis
/reports                      List your private reports
/read ID                      Read your report
/delete TEXT                  Preview literal matching reports (/delete * = all)
/delete-conversation          Preview this conversation's reports
/confirm TOKEN                Permanently delete the previewed set
/cancel                       Cancel pending deletion
/new                          Clear context and start a new conversation
/quit                         Exit
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
    if verb == "/reports":
        return "\n".join(f"{r.id} | {r.title}" for r in store.list(user)) or "No saved reports."
    if verb == "/save":
        if not arg or analyst.last_answer is None:
            raise AppError("Use /save TITLE after a successful analysis.")
        rid = store.save(user, conversation, arg, analyst.last_answer)
        return f"Saved report {rid}."
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
    if text.casefold().strip(".! ") in ("save this report", "save this", "save the report"):
        return command("/save Retail analysis", analyst)
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
    store = ReportStore(settings.data_dir / "reports.sqlite3")
    analyst = Analyst(settings, DEMO_USERS[user], executor, store, uuid4().hex[:12])
    console.print(f"Retail assistant — DEMO identity: {user}; scope: {analyst.identity.scope}")
    console.print(
        f"Conversation: {analyst.conversation}. /help for commands. Reports save only on request."
    )
    try:
        asyncio.run(chat_loop(analyst))
    finally:
        store.close()


async def chat_loop(analyst: Analyst) -> None:
    while True:
        try:
            text = console.input("\nYou> ").strip()
            if text in ("/quit", "/exit"):
                break
            if not text:
                continue
            response = command(text, analyst)
            if response is not None:
                console.print(response)
                continue
            with console.status("Analyzing authorized data…"):
                answer = await analyst.ask(text)
            console.print(render_answer(answer))
            if analyst.preview is not None:
                console.print(render_preview(analyst.preview))
        except (EOFError, KeyboardInterrupt):
            break
        except AppError as exc:
            console.print(f"Unable to complete: {exc}")
        except sqlite3.Error:
            console.print(
                "Local storage failed. The operation was not confirmed; check disk access."
            )


if __name__ == "__main__":
    app()
