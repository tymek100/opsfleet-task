"""Terminal client: model-authored Markdown plus trusted operation controls."""

import asyncio
import json
import logging
import signal
import sys
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from retail_agent.config import Settings
from retail_agent.contracts import DEMO_USERS, TurnResult
from retail_agent.observability import TracingSession, configure_tracing
from retail_agent.privacy import screen
from retail_agent.runtime import Analyst
from retail_agent.terminal import command_help, create_prompt_session

app = typer.Typer(help="Autonomous retail analysis with reviewed answers.", no_args_is_help=True)
console = Console()


def _start_tracing(enabled: bool, settings: Settings) -> TracingSession | None:
    if not enabled:
        return None
    try:
        session = configure_tracing(mode="metadata")
    except Exception:
        console.print("Phoenix tracing is unavailable; continuing without tracing.")
        return None
    try:
        from retail_agent.phoenix_prompts import sync_prompts
        from retail_agent.prompt_catalog import analyst_prompt, reviewer_prompt

        session.register_prompts(
            sync_prompts([analyst_prompt(settings), reviewer_prompt(settings)])
        )
    except Exception:
        console.print("Phoenix prompt synchronization failed; using repository instructions.")
    return session


def _close_tracing(session: TracingSession | None) -> None:
    if session is None:
        return
    try:
        complete = session.close(timeout_seconds=2)
        if not complete or session.failed_exports:
            console.print("Some Phoenix traces could not be exported; the answer is unaffected.")
    except Exception:
        console.print("Phoenix tracing could not finish; the answer is unaffected.")


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


_TOOL_STATUS_MESSAGES = {
    "describe_data": "Checking available data...",
    "load_skill": "Reading analysis guidance...",
    "load_skill_resource": "Reading supporting guidance...",
    "list_golden": "Browsing analysis examples...",
    "read_golden": "Reading an analysis example...",
    "query_data": "Looking up retail data...",
    "read_result": "Reading query results...",
    "analyze_results": "Analyzing the results...",
    "query_state_summary": "Summarizing sales by state...",
    "search_reports": "Searching your saved reports...",
    "read_report": "Reading a saved report...",
    "read_answer": "Reading an earlier answer...",
    "stage_report_save": "Preparing to save your report...",
    "preview_report_deletion": "Preparing a report deletion preview...",
    "cancel_report_deletion": "Cancelling the pending deletion...",
    "finish_answer": "Submitting the answer for review...",
}


@dataclass
class _QuestionStatus:
    started: float
    detail: str = "Considering your question..."

    def __rich__(self) -> Text:
        # Rich refreshes this even while the agent is waiting without emitting events.
        elapsed = int(monotonic() - self.started)
        return Text(f"Elapsed: {elapsed}s | Status: {self.detail}")


async def run_question(analyst: Analyst, prompt: str) -> TurnResult:
    indicator = _QuestionStatus(started=monotonic())
    with console.status(indicator, spinner="dots"):

        def progress(event: dict) -> None:
            name = event["event"]
            if name == "tool_start":
                detail = _TOOL_STATUS_MESSAGES.get(event["tool"], "Working on your request...")
            elif name == "review_start":
                detail = "Reviewing the answer..."
            elif name == "model_call":
                detail = (
                    "Checking the answer against the evidence..."
                    if event.get("role") == "reviewer"
                    else "Considering the next step..."
                )
            else:
                return
            indicator.detail = detail

        previous_progress = getattr(analyst, "progress", None)
        analyst.progress = progress
        task = asyncio.create_task(analyst.ask(prompt))
        loop = asyncio.get_running_loop()
        previous_handler = signal.getsignal(signal.SIGINT)
        loop.add_signal_handler(signal.SIGINT, task.cancel)
        try:
            result = await task
        finally:
            analyst.progress = previous_progress
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
    phoenix: Annotated[bool, typer.Option(help="Send metadata traces to local Phoenix.")] = False,
) -> None:
    """Answer one question; optionally capture its answer, evidence and metadata."""
    analyst = build(user, backend, golden_bootstrap)
    tracing = _start_tracing(phoenix, analyst.settings)
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
        _close_tracing(tracing)


HELP = command_help()


async def conversation(analyst: Analyst) -> None:
    console.print(
        f"Retail Insight Agent - DEMO identity: {analyst.identity.user_id}; scope: {analyst.identity.scope}"
    )
    console.print(
        f"Conversation: {analyst.conversation_id}. Type / for commands. Reports save only on request."
    )
    if analyst.settings.backend == "fixture":
        console.print("Data: frozen synthetic fixture (not live company results).")
    if analyst.settings.golden_bootstrap:
        console.print(
            "Golden retrieval: synthetic example methods enabled; current facts still require queries."
        )
    session = (
        create_prompt_session()
        if sys.stdin.isatty() and console.is_terminal and not console.is_dumb_terminal
        else None
    )
    while True:
        try:
            prompt = (
                await session.prompt_async()
                if session is not None
                else console.input("[bold]You> [/bold]")
            ).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not prompt:
            continue
        console.print()
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
                        console.print()
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("Investigation cancelled.")
        except Exception as exc:
            if hasattr(exc, "code"):
                console.print(str(exc), markup=False)
            else:
                console.print("The operation could not complete. Your library remains available.")


@app.command()
def chat(
    user: str = "alice",
    backend: str | None = None,
    golden_bootstrap: bool = False,
    phoenix: Annotated[bool, typer.Option(help="Send metadata traces to local Phoenix.")] = False,
) -> None:
    """Start an interactive conversation with ephemeral history and persistent reports."""
    analyst = build(user, backend, golden_bootstrap)
    tracing = _start_tracing(phoenix, analyst.settings)
    try:
        asyncio.run(conversation(analyst))
    finally:
        analyst.reports.close()
        _close_tracing(tracing)


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
