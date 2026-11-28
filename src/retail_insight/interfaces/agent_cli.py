"""Run a coordinator or specialist LangGraph locally."""

from __future__ import annotations

import asyncio
import sys
from enum import StrEnum
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown

from retail_insight.config import Settings
from retail_insight.interfaces.progress import ThinkingStatus
from retail_insight.interfaces.terminal import COMMANDS, command_help, create_prompt_session
from retail_insight.observability.tracing import configure_from_env
from retail_insight.runtime.team import AgentTeam

app = typer.Typer(help="Run a coordinator or specialist LangGraph.", no_args_is_help=True)
console = Console()
CHAT_COMMANDS = tuple(c for c in COMMANDS if c.name in {"/help", "/new", "/exit", "/quit"})
AGENT_LABELS = {
    "coordinator": "Coordinator",
    "retail": "Retail agent",
    "inventory": "Inventory agent",
    "distribution": "Distribution agent",
}


class AgentName(StrEnum):
    coordinator = "coordinator"
    retail = "retail"
    inventory = "inventory"
    distribution = "distribution"


def run_chat(
    agent: str,
    max_cost_usd: float = 1.0,
    deadline_seconds: float = 180,
    context_id: str | None = None,
) -> None:
    """Use the selected local graph, retaining its conversation across follow-ups."""
    if agent not in AGENT_LABELS:
        raise typer.BadParameter("Unknown agent.")
    settings = Settings.load().model_copy(
        update={"question_budget_usd": max_cost_usd, "turn_timeout_seconds": deadline_seconds}
    )
    client = AgentTeam(settings)
    tracing = configure_from_env()
    loop = asyncio.new_event_loop()
    label = AGENT_LABELS[agent]
    console.print(f"{label} — full dataset access. Type / for commands.")
    session = (
        create_prompt_session(commands=CHAT_COMMANDS)
        if sys.stdin.isatty() and console.is_terminal and not console.is_dumb_terminal
        else None
    )
    conversation = context_id
    while True:
        try:
            question = (
                session.prompt() if session is not None else console.input("[bold]You> [/bold]")
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if question.lower() in {"/exit", "/quit"}:
            break
        if not question:
            continue
        if question.lower() in {"/", "/help"}:
            console.print(command_help(CHAT_COMMANDS), markup=False)
            continue
        if question.lower() == "/new":
            conversation = None
            console.print("Started a new conversation.")
            continue
        if question.startswith("/"):
            console.print("Unknown command. Use /help.")
            continue
        console.print()
        try:
            with console.status(ThinkingStatus(), spinner="dots"):
                result = loop.run_until_complete(
                    client.ask(
                        agent,
                        question,
                        "workspace",
                        conversation,
                        max_cost_usd=max_cost_usd,
                        deadline_seconds=deadline_seconds,
                    )
                )
            conversation = result.get("context_id", conversation)
            console.print(Markdown(result.get("markdown") or "No reviewed answer was returned."))
            console.print(
                f"[dim]Context: {conversation} · Status: {result.get('status', 'unknown')}[/dim]"
            )
        except KeyboardInterrupt:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            console.print("Stopped. No unfinished answer was published.")
        except Exception as exc:
            console.print(f"[red]Request failed:[/red] {type(exc).__name__}: {exc}")
        console.print()

    client.close()
    loop.close()
    if tracing:
        tracing.close()


@app.command()
def chat(
    agent: Annotated[
        AgentName, typer.Argument(help="Agent to talk to. Use coordinator for cross-domain tasks.")
    ],
    max_cost_usd: float = typer.Option(1.0, min=0.01, max=10),
    deadline_seconds: float = typer.Option(180, min=10, max=600),
    context_id: str | None = typer.Option(None, help="Resume a conversation with this agent."),
) -> None:
    """Run the selected LangGraph; no containers are required."""
    run_chat(agent.value, max_cost_usd, deadline_seconds, context_id)


if __name__ == "__main__":
    app()
