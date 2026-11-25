"""Local Compose lifecycle and an authenticated A2A terminal client."""

from __future__ import annotations

import asyncio
import importlib.util
import subprocess

import typer
from rich.console import Console
from rich.markdown import Markdown

from retail_insight.a2a.client import AgentClient
from retail_insight.config import repository_root

app = typer.Typer(help="Run and inspect the local retail A2A agent stack.")
console = Console()
HOST_PORTS = {"retail": 8001, "inventory": 8002, "distribution": 8003, "coordinator": 8004}


def _infra():
    filename = repository_root() / "infra/agents/start.py"
    if not filename.is_file():
        raise typer.BadParameter("Run retail-stack from the source repository.")
    spec = importlib.util.spec_from_file_location("retail_stack_start", filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@app.command()
def up(
    backend: str = typer.Option("fixture", help="fixture or bigquery"),
    no_build: bool = typer.Option(False, help="Reuse existing agent images."),
    evaluation_fixtures: bool = typer.Option(
        False, help="Mount independent evaluation warehouse rows."
    ),
) -> None:
    """Prepare local configuration and start healthy agents, Inspector and Phoenix."""
    if backend not in {"fixture", "bigquery"}:
        raise typer.BadParameter("Backend must be fixture or bigquery.")
    try:
        _infra().up(backend, build=not no_build, evaluation_fixtures=evaluation_fixtures)
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        console.print(f"[red]Stack startup failed:[/red] {exc}")
        raise typer.Exit(1) from exc


@app.command()
def down() -> None:
    """Stop the agents and Inspector, retaining all volumes and Phoenix."""
    infra = _infra()
    subprocess.run(infra.compose_args("down"), cwd=infra.ROOT, check=True)


@app.command()
def status() -> None:
    """Show service health and published local endpoints."""
    infra = _infra()
    subprocess.run(infra.compose_args("ps"), cwd=infra.ROOT, check=True)


@app.command()
def token() -> None:
    """Print the Alice-only Bearer token for manual API clients; the GUI configures it itself."""
    path = repository_root() / ".artifacts/agents/secrets/a2a_demo_token"
    if not path.is_file():
        raise typer.BadParameter("Start the stack first with retail-stack up.")
    typer.echo(path.read_text().strip())


@app.command()
def chat(
    user: str = typer.Option("alice", help="Demo identity: alice, bob or ceo."),
    agent: str = typer.Option("coordinator", help="coordinator, retail, inventory or distribution"),
    max_cost_usd: float = typer.Option(1.0, min=0.01, max=10),
    deadline_seconds: float = typer.Option(180, min=10, max=600),
    context_id: str | None = typer.Option(None, help="Resume an owned conversation context."),
) -> None:
    """Chat through the same A2A endpoint used by Inspector and evaluations."""
    if user not in {"alice", "bob", "ceo"} or agent not in HOST_PORTS:
        raise typer.BadParameter("Unknown demo identity or agent.")
    key_path = repository_root() / ".artifacts/agents/secrets/a2a_signing_key"
    if not key_path.is_file():
        raise typer.BadParameter("Start the stack first with retail-stack up.")
    urls = {role: f"http://127.0.0.1:{port}" for role, port in HOST_PORTS.items()}
    client = AgentClient(urls, key_path.read_text().strip(), signed=True)
    console.print(f"Retail A2A — DEMO identity: {user}; agent: {agent}. /exit to leave.")
    conversation = context_id
    while True:
        try:
            question = console.input("[bold]You> [/bold]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if question.lower() in {"/exit", "/quit"}:
            break
        if not question:
            continue
        if question == "/new":
            conversation = None
            console.print("Started a new conversation.")
            continue
        console.print()
        try:
            with console.status(f"Waiting for {agent}…"):
                result = asyncio.run(
                    client.ask(
                        agent,
                        question,
                        user,
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


if __name__ == "__main__":
    app()
