"""Terminal client: model-authored Markdown plus trusted operation controls."""

import asyncio
import json
import logging
import signal
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from retail_agent.config import Settings
from retail_agent.contracts import DEMO_USERS, TurnResult
from retail_agent.privacy import screen
from retail_agent.runtime import Analyst

app = typer.Typer(help="Autonomous retail analysis with reviewed answers.", no_args_is_help=True)
console = Console()


def build(user: str, backend: str | None, bootstrap: bool) -> Analyst:
    if user not in DEMO_USERS:
        raise typer.BadParameter("Choose alice, bob or ceo; these are simulated demo identities.")
    settings = Settings.load()
    if backend:
        if backend not in ("bigquery", "fixture"):
            raise typer.BadParameter("Backend must be bigquery or fixture.")
        settings.backend = backend
    if bootstrap:
        settings.golden_bootstrap = True
    # SDK logs can contain arbitrary generated arguments; the app records metadata itself.
    for name in ("google.adk", "google_genai", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    warnings.filterwarnings("ignore", message=r".*FeatureName.JSON_SCHEMA_FOR_FUNC_DECL.*")
    return Analyst(settings, DEMO_USERS[user])


def show_preview(preview: dict) -> None:
    reports = preview.get("reports", [])
    screen(json.dumps(reports, default=str))
    if not reports:
        console.print("No matching reports in your library.")
        return
    table = Table("Report ID", "Title")
    for report in reports:
        table.add_row(str(report["id"]), str(report["title"]))
    console.print(table)
    console.print("This exact selection will be permanently deleted.")
    console.print(f"Confirm: /confirm {preview['token']}    Cancel: /cancel", markup=False)


def display(result: TurnResult) -> None:
    if result.answer:
        console.print(Markdown(result.answer.markdown))
        for receipt in result.answer.receipts:
            if receipt.get("status") == "saved":
                console.print(f"Saved: {receipt['title']} ({receipt['id']})", markup=False)
            else:
                console.print(receipt.get("message", "Operation did not complete."), markup=False)
    else:
        console.print(result.message, markup=False)
    if result.deletion_preview:
        show_preview(result.deletion_preview)


async def run_question(analyst: Analyst, prompt: str) -> TurnResult:
    with console.status("Analyst is considering your question...", spinner="dots") as status:

        def progress(event: dict) -> None:
            name = event["event"]
            if name == "tool_start":
                detail = f"Using {event['tool']}"
            elif name == "review_start":
                detail = "Reviewing the proposed answer"
            elif name == "model_call":
                detail = (
                    "Reviewer is checking evidence"
                    if event.get("role") == "reviewer"
                    else "Analyst is choosing the next action"
                )
            else:
                return
            status.update(f"{detail} ({event['elapsed']:.0f}s)")

        analyst.progress = progress
        task = asyncio.create_task(analyst.ask(prompt))
        loop = asyncio.get_running_loop()
        previous_handler = signal.getsignal(signal.SIGINT)
        loop.add_signal_handler(signal.SIGINT, task.cancel)
        try:
            result = await task
        finally:
            loop.remove_signal_handler(signal.SIGINT)
            signal.signal(signal.SIGINT, previous_handler)
    return result


@app.command()
def ask(
    prompt: Annotated[str, typer.Argument(help="Question in English.")],
    user: str = "alice",
    backend: str | None = None,
    golden_bootstrap: bool = False,
    output_json: Path | None = None,
) -> None:
    """Answer one question; optionally capture its answer, evidence and metadata."""
    analyst = build(user, backend, golden_bootstrap)
    try:
        result = asyncio.run(run_question(analyst, prompt))
        display(result)
        if output_json:
            output_json.parent.mkdir(parents=True, exist_ok=True)
            output_json.write_text(json.dumps(asdict(result), indent=2, default=str) + "\n")
        if result.answer is None:
            raise typer.Exit(1)
    finally:
        analyst.reports.close()


HELP = """Commands:
/help             Show commands
/details          Inspect latest query evidence and metadata
/reports          List your saved reports
/read ID          Display an owned saved report
/delete TEXT      Preview reports matching literal text
/confirm TOKEN    Permanently delete the exact previewed reports
/cancel           Cancel deletion
/new              Clear this conversation
/exit             Exit
Ask naturally to analyze data, create a report, or explicitly save an answer.
"""


async def conversation(analyst: Analyst) -> None:
    console.print(
        f"Retail assistant - DEMO identity: {analyst.identity.user_id}; scope: {analyst.identity.scope}"
    )
    console.print(
        f"Conversation: {analyst.conversation_id}. /help for commands. Reports save only on request."
    )
    if analyst.settings.backend == "fixture":
        console.print("Data: frozen synthetic fixture (not live company results).")
    if analyst.settings.golden_bootstrap:
        console.print(
            "Golden retrieval: synthetic example methods enabled; current facts still require queries."
        )
    while True:
        try:
            prompt = console.input("\n\n[bold]You> [/bold]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not prompt:
            continue
        command, _, argument = prompt.partition(" ")
        try:
            match command:
                case "/exit" | "/quit":
                    break
                case "/help":
                    console.print(HELP, markup=False)
                case "/new":
                    analyst.reports.cancel_delete(analyst.identity.user_id, analyst.conversation_id)
                    analyst.clear_context()
                    console.print("Conversation cleared.")
                case "/details":
                    evidence = analyst.last_result.evidence if analyst.last_result else []
                    screen(json.dumps(evidence, default=str))
                    console.print_json(data=evidence)
                case "/reports":
                    reports = analyst.reports.search(analyst.identity.user_id)
                    screen(json.dumps(reports, default=str))
                    console.print_json(data=reports)
                case "/read":
                    report = analyst.reports.read(analyst.identity.user_id, argument)
                    if report:
                        console.print(Markdown(screen(report["markdown"])))
                    else:
                        console.print("Report not found in your library.")
                case "/delete":
                    show_preview(
                        analyst.reports.preview_delete(
                            analyst.identity.user_id, analyst.conversation_id, argument
                        )
                    )
                case "/confirm":
                    console.print_json(data=analyst.confirm_delete(argument))
                case "/cancel":
                    console.print_json(
                        data=analyst.reports.cancel_delete(
                            analyst.identity.user_id, analyst.conversation_id
                        )
                    )
                case _:
                    if prompt.startswith("/"):
                        console.print("Unknown command. Use /help.")
                    else:
                        display(await run_question(analyst, prompt))
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("Investigation cancelled.")
        except Exception as exc:
            if hasattr(exc, "code"):
                console.print(str(exc), markup=False)
            else:
                console.print("The operation could not complete. Your library remains available.")


@app.command()
def chat(user: str = "alice", backend: str | None = None, golden_bootstrap: bool = False) -> None:
    """Start an interactive conversation with ephemeral history and persistent reports."""
    analyst = build(user, backend, golden_bootstrap)
    try:
        asyncio.run(conversation(analyst))
    finally:
        analyst.reports.close()


@app.command()
def import_legacy(path: Path, user: str = "alice") -> None:
    """Copy your legacy reports into the new library; the source remains unchanged."""
    analyst = build(user, "fixture", False)
    try:
        console.print_json(data=analyst.reports.import_legacy(path, analyst.identity.user_id))
        console.print(
            "Imported copies belong to the new library. The original source is unchanged."
        )
    finally:
        analyst.reports.close()


if __name__ == "__main__":
    app()
