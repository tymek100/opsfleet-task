"""Local Compose lifecycle and an authenticated A2A terminal client."""

from __future__ import annotations

import importlib.util
import subprocess

import typer
from rich.console import Console

from retail_insight.config import repository_root
from retail_insight.interfaces.agent_cli import run_chat

app = typer.Typer(help="Run and inspect the local retail A2A agent stack.")
console = Console()


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
    inspector: bool = typer.Option(False, help="Also start the A2A Inspector on localhost:8081."),
) -> None:
    """Start healthy agents, assistant-ui and Phoenix; optionally include Inspector."""
    if backend not in {"fixture", "bigquery"}:
        raise typer.BadParameter("Backend must be fixture or bigquery.")
    try:
        _infra().up(
            backend,
            build=not no_build,
            evaluation_fixtures=evaluation_fixtures,
            inspector=inspector,
        )
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
    """Print the workspace Bearer token for manual API clients; the GUI configures it itself."""
    path = repository_root() / ".artifacts/agents/secrets/a2a_access_token"
    if not path.is_file():
        raise typer.BadParameter("Start the stack first with retail-stack up.")
    typer.echo(path.read_text().strip())


@app.command()
def chat(
    agent: str = typer.Option("coordinator", help="coordinator, retail, inventory or distribution"),
    max_cost_usd: float = typer.Option(1.0, min=0.01, max=10),
    deadline_seconds: float = typer.Option(180, min=10, max=600),
    context_id: str | None = typer.Option(None, help="Resume an owned conversation context."),
) -> None:
    """Compatibility command; prefer agent-chat coordinator (or another agent)."""
    run_chat(agent, max_cost_usd, deadline_seconds, context_id)


if __name__ == "__main__":
    app()
