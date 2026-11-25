"""Explicitly select a running agent for an authenticated A2A conversation."""

from __future__ import annotations

import asyncio
import sys
from enum import StrEnum
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown

from retail_insight.a2a.client import AgentClient
from retail_insight.config import repository_root
from retail_insight.interfaces.terminal import COMMANDS, command_help, create_prompt_session

app = typer.Typer(help="Chat with a running coordinator or specialist agent.", no_args_is_help=True)
console = Console()
CHAT_COMMANDS = tuple(c for c in COMMANDS if c.name in {"/help", "/new", "/exit", "/quit"})
HOST_PORTS = {"retail": 8001, "inventory": 8002, "distribution": 8003, "coordinator": 8004}
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
    """Use the selected service, retaining its conversation across follow-ups."""
    if agent not in HOST_PORTS:
        raise typer.BadParameter("Unknown agent.")
    key_path = repository_root() / ".artifacts/agents/secrets/a2a_signing_key"
    if not key_path.is_file():
        raise typer.BadParameter("Start the stack first with retail-stack up.")
    urls = {role: f"http://127.0.0.1:{port}" for role, port in HOST_PORTS.items()}
    client = AgentClient(urls, key_path.read_text().strip(), signed=True)
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
            with console.status(f"Waiting for {label.lower()}…"):
                result = asyncio.run(
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
            console.print("Request interrupted; inspect task status before retrying.")
        except Exception as exc:
            console.print(f"[red]Request failed:[/red] {type(exc).__name__}: {exc}")
        console.print()


@app.command()
def chat(
    agent: Annotated[
        AgentName, typer.Argument(help="Agent to talk to. Use coordinator for cross-domain tasks.")
    ],
    max_cost_usd: float = typer.Option(1.0, min=0.01, max=10),
    deadline_seconds: float = typer.Option(180, min=10, max=600),
    context_id: str | None = typer.Option(None, help="Resume a conversation with this agent."),
) -> None:
    """Connect to a running agent. Start services with retail-stack up."""
    run_chat(agent.value, max_cost_usd, deadline_seconds, context_id)


if __name__ == "__main__":
    app()
