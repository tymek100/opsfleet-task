"""Local single-process LangGraph application lifecycle."""

import importlib.util
import subprocess

import typer

from retail_insight.config import repository_root
from retail_insight.interfaces.agent_cli import run_chat

app = typer.Typer(help="Run the LangGraph application and assistant-ui.")


def _infra():
    path = repository_root() / "infra/workflow/start.py"
    spec = importlib.util.spec_from_file_location("workflow_start", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Workflow launcher is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@app.command()
def up(backend: str = "bigquery", no_build: bool = False):
    """Build and start the single application on localhost:8080."""
    _infra().up(backend, build=not no_build)


@app.command()
def down():
    """Stop the application; keep conversation storage."""
    infra = _infra()
    subprocess.run(infra.compose_args("down"), cwd=infra.ROOT, check=True)


@app.command()
def status():
    infra = _infra()
    subprocess.run(infra.compose_args("ps"), cwd=infra.ROOT, check=True)


@app.command()
def chat(
    agent: str = "coordinator",
    max_cost_usd: float = typer.Option(1, min=0.01, max=10),
    deadline_seconds: float = typer.Option(180, min=10, max=600),
    context_id: str | None = None,
):
    """Run a local graph in the terminal. Prefer agent-chat coordinator."""
    run_chat(agent, max_cost_usd, deadline_seconds, context_id)


@app.command("connect-foundry")
def connect_foundry():
    """Verify project access and configure local/Docker telemetry; no model calls."""
    from dotenv import set_key

    from retail_insight.config import Settings
    from retail_insight.integrations.azure.connector import AzureConnector

    Settings.load()
    connector = AzureConnector()
    try:
        next(iter(connector.project().datasets.list()), None)
        connection = connector.monitoring_connection()
        path = repository_root() / ".env"
        set_key(path, "APPLICATIONINSIGHTS_CONNECTION_STRING", connection)
        set_key(path, "FOUNDRY_TRACING", "true")
        path.chmod(0o600)
        typer.echo(
            "Foundry connected. Google model settings are unchanged. Restart the app to enable tracing."
        )
        typer.echo(connector.settings.foundry_portal_url)
    except Exception as exc:
        typer.echo(
            f"Foundry connection failed ({type(exc).__name__}). Check az login for the project's tenant and its Application Insights connection.",
            err=True,
        )
        raise typer.Exit(1) from None
    finally:
        connector.close()
