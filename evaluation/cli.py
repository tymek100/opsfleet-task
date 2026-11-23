"""Explicit, bounded execution and independent regrading commands."""

import asyncio
import json
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import typer

from evaluation.settings import EvaluationSettings

app = typer.Typer(
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
    help="Independent retail-agent evaluation with local Phoenix.",
)


def echo(value) -> None:
    typer.echo(json.dumps(value, indent=2, default=str))


def fixture_endpoint(url: str) -> None:
    """Reserve the primary Phoenix workspace for the authored conversation suite."""
    if urlparse(url).port in {None, 6006}:
        raise typer.BadParameter(
            "The main Phoenix workspace is reserved for the 20 conversations. "
            "Use run-conversations, or supply --phoenix-url http://127.0.0.1:6007 "
            "for a separate fixture-test instance."
        )


@app.command()
def validate() -> None:
    """Validate all case references and fixture hashes without model calls."""
    from evaluation.data import validate_dataset

    result = validate_dataset()
    echo(result)
    if not result["valid"]:
        raise typer.Exit(1)


@app.command()
def cases(suite: str = "pilot") -> None:
    """List the exact cases selected by a suite or comma-separated IDs."""
    from evaluation.data import load_cases

    for case in load_cases(suite):
        typer.echo(f"{case.id}\t{case.family}\t{len(case.steps)} steps\t{case.split}")


@app.command()
def sync(suite: str = "pilot", phoenix_url: str = "http://127.0.0.1:6006") -> None:
    """Mirror canonical cases into a content-versioned local Phoenix dataset."""
    from evaluation.data import load_cases
    from evaluation.reporting.phoenix import sync_cases

    fixture_endpoint(phoenix_url)
    dataset = sync_cases(load_cases(suite), EvaluationSettings(phoenix_url=phoenix_url))
    echo({"dataset_id": dataset.id, "version_id": dataset.version_id, "name": dataset.name})


@app.command()
def sync_prompts(
    phoenix_url: str = "http://127.0.0.1:6006",
    model: str | None = None,
    judge_model: str | None = None,
) -> None:
    """Publish four repository prompt definitions to Phoenix without model calls."""
    from evaluation.prompt_catalog import judge_prompt
    from evaluation.reporting.phoenix_service import ensure_phoenix
    from retail_agent.config import Settings
    from retail_agent.phoenix_prompts import sync_prompts as publish_prompts
    from retail_agent.prompt_catalog import analyst_prompt, reviewer_prompt

    settings = Settings.load()
    if model:
        settings.gemini_model = model
    config = EvaluationSettings(
        phoenix_url=phoenix_url, judge_model=judge_model or settings.gemini_model
    )
    deadline = time.monotonic() + 60
    try:
        ensure_phoenix(config, deadline=deadline, progress=typer.echo)
        references = publish_prompts(
            [
                analyst_prompt(settings),
                reviewer_prompt(settings),
                judge_prompt(config, "answer"),
                judge_prompt(config, "trajectory"),
            ],
            config.phoenix_url,
            deadline=deadline,
        )
    except Exception as exc:
        typer.echo(f"Prompt synchronization failed ({type(exc).__name__}). Check local Phoenix.")
        raise typer.Exit(2) from None
    typer.echo(f"Phoenix prompts: {config.phoenix_url}/prompts")
    echo(references)


@app.command()
def run(
    suite: str = "smoke",
    repetitions: int = typer.Option(1, min=1, max=20),
    max_cost_usd: float = typer.Option(..., min=0.01),
    deadline_seconds: float = typer.Option(..., min=1),
    allow_unreviewed: bool = False,
    phoenix: bool = typer.Option(True, hidden=True),
    phoenix_url: str = "http://127.0.0.1:6006",
    model: str | None = None,
    judge_model: str | None = None,
    candidates: bool = True,
    artifact_root: Path = Path(".artifacts/evaluation"),
) -> None:
    """Run, grade, and publish an experiment in Phoenix under one shared limit."""
    from pydantic import ValidationError

    from evaluation.data import load_cases
    from evaluation.graders.judge import GeminiJudge
    from evaluation.reporting.phoenix_service import PhoenixUnavailable
    from evaluation.runners.pipeline import run_pipeline
    from retail_agent.config import Settings

    if not phoenix:
        raise typer.BadParameter(
            "run now includes Phoenix and grading. Use pytest for offline checks; "
            "grade can reassess saved runs without Phoenix."
        )
    try:
        selected = load_cases(suite)
        if any(not c.provenance.human_reviewed for c in selected) and not allow_unreviewed:
            raise typer.BadParameter(
                "Pilot references await human review; use --allow-unreviewed for diagnostic runs."
            )
        settings = Settings.load()
        if model:
            settings = settings.model_copy(update={"gemini_model": model})
        if not settings.gemini_api_key.get_secret_value():
            raise typer.BadParameter("GEMINI_API_KEY is required for a live agent run.")
        config = EvaluationSettings(
            artifact_root=artifact_root,
            phoenix_url=phoenix_url,
            judge_model=judge_model or settings.gemini_model,
        )
        fixture_endpoint(config.phoenix_url)
        judge = GeminiJudge(
            settings.gemini_api_key.get_secret_value(),
            config,
            max_cost_usd=max_cost_usd,
            deadline_seconds=deadline_seconds,
        )
        result = asyncio.run(
            run_pipeline(
                selected,
                settings,
                config,
                suite=suite,
                repetitions=repetitions,
                max_cost_usd=max_cost_usd,
                deadline_seconds=deadline_seconds,
                judge=judge,
                grade_candidates=candidates,
                progress=typer.echo,
            )
        )
    except ValidationError:
        typer.echo(
            "Invalid evaluation configuration; check the settings and Phoenix URL.", err=True
        )
        raise typer.Exit(2) from None
    except OSError:
        typer.echo("Evaluation could not access a required file or local service.", err=True)
        raise typer.Exit(2) from None
    except (PhoenixUnavailable, ValueError) as exc:
        typer.echo(f"Evaluation could not complete: {exc}", err=True)
        raise typer.Exit(2) from None
    if result.exit_code:
        raise typer.Exit(result.exit_code)


def _judge(model: str | None, max_cost_usd: float, deadline_seconds: float):
    from evaluation.graders.judge import GeminiJudge
    from retail_agent.config import Settings

    settings = Settings.load()
    if not settings.gemini_api_key.get_secret_value():
        raise typer.BadParameter("GEMINI_API_KEY is required for LLM grading.")
    config = EvaluationSettings(judge_model=model or settings.gemini_model)
    return GeminiJudge(
        settings.gemini_api_key.get_secret_value(),
        config,
        max_cost_usd=max_cost_usd,
        deadline_seconds=deadline_seconds,
    )


@app.command()
def grade(
    run_directory: Annotated[Path, typer.Option("--run", exists=True, file_okay=False)],
    max_cost_usd: float = typer.Option(..., min=0.01),
    deadline_seconds: float = typer.Option(..., min=1),
    code_only: bool = False,
    candidates: bool = True,
    trajectory: bool = True,
    judge_model: str | None = None,
    phoenix: bool = False,
    phoenix_url: str = "http://127.0.0.1:6006",
) -> None:
    """Grade saved outputs into a new version; the agent is never rerun."""
    from evaluation.graders.runner import grade_run

    if phoenix:
        fixture_endpoint(phoenix_url)

    async def execute():
        judge = None if code_only else _judge(judge_model, max_cost_usd, deadline_seconds)
        try:
            return await grade_run(
                run_directory,
                judge,
                grade_candidates=candidates,
                grade_trajectory=trajectory,
                progress=typer.echo,
            )
        finally:
            if judge:
                await judge.close()

    result = asyncio.run(execute())
    typer.echo(str(result / "summary.md"))
    if phoenix:
        from evaluation.reporting.phoenix import publish

        echo(publish(run_directory, EvaluationSettings(phoenix_url=phoenix_url), grade=result))


@app.command()
def publish(
    run_directory: Annotated[Path, typer.Option("--run", exists=True, file_okay=False)],
    grade_directory: Annotated[
        Path | None, typer.Option("--grade", exists=True, file_okay=False)
    ] = None,
    phoenix_url: str = "http://127.0.0.1:6006",
) -> None:
    """Publish saved trials and optional scores, retaining files on outage."""
    from evaluation.reporting.phoenix import publish as upload

    fixture_endpoint(phoenix_url)
    result = upload(
        run_directory, EvaluationSettings(phoenix_url=phoenix_url), grade=grade_directory
    )
    echo(result)
    if result["status"] != "published":
        raise typer.Exit(1)


@app.command()
def publish_conversations(
    history: Path = Path("evaluation/scenarios/manual_history.json"),
    artifact_root: Path = Path(".artifacts/manual"),
    phoenix_url: str = "http://127.0.0.1:6006",
) -> None:
    """Publish verified saved conversations and reviews; never rerun model calls."""
    from evaluation.reporting.conversations import publish_history
    from evaluation.reporting.phoenix_service import ensure_phoenix

    config = EvaluationSettings(phoenix_url=phoenix_url)
    ensure_phoenix(config, deadline=time.monotonic() + 60, progress=typer.echo)
    result = publish_history(history, artifact_root, config, progress=typer.echo)
    typer.echo(
        f"Published {len(result['phases'])} experiments with {len(result['trace_ids'])} captured turns."
    )


@app.command()
def run_conversations(
    max_cost_usd: float = typer.Option(..., min=0.01),
    deadline_seconds: float = typer.Option(..., min=1),
    phase: str = "recheck",
    only: str | None = None,
    phoenix_url: str = "http://127.0.0.1:6006",
    reference: Path | None = None,
    judge_model: str | None = None,
) -> None:
    """Run and independently grade the 20 conversations against the same warehouse snapshot."""
    from evaluation.runners.authored import run_authored
    from evaluation.runners.manual import load_scenarios
    from retail_agent.config import Settings, repository_root

    settings = Settings.load()
    scenarios = load_scenarios(repository_root() / "evaluation/scenarios/manual_20.json", only)
    if not settings.gemini_api_key.get_secret_value():
        raise typer.BadParameter("GEMINI_API_KEY is required for real-model conversations.")
    _, summary = asyncio.run(
        run_authored(
            scenarios,
            settings,
            EvaluationSettings(
                phoenix_url=phoenix_url, judge_model=judge_model or settings.gemini_model
            ),
            max_cost_usd=max_cost_usd,
            deadline_seconds=deadline_seconds,
            phase=phase,
            reference_directory=reference,
            progress=typer.echo,
        )
    )
    echo(summary)
    if summary["exit_code"]:
        raise typer.Exit(summary["exit_code"])


@app.command()
def sync_conversations(
    reference: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    phoenix_url: str = "http://127.0.0.1:6006",
) -> None:
    """Attach verified independent references to the 20 examples as a new dataset version."""
    from evaluation.conversation_references import Snapshot, bundle
    from evaluation.reporting.conversations import ensure_dataset
    from evaluation.reporting.phoenix import client_for
    from evaluation.reporting.phoenix_service import ensure_phoenix
    from evaluation.runners.manual import load_scenarios
    from retail_agent.config import repository_root

    snapshot = Snapshot.load(reference)
    scenarios = load_scenarios(repository_root() / "evaluation/scenarios/manual_20.json")
    config = EvaluationSettings(phoenix_url=phoenix_url)
    ensure_phoenix(config, deadline=time.monotonic() + 60, progress=typer.echo)
    dataset = ensure_dataset(client_for(config), scenarios, bundle(scenarios, snapshot))
    echo(
        {
            "dataset_id": dataset.id,
            "version_id": dataset.version_id,
            "examples": len(dataset.examples),
            "url": f"{config.phoenix_url}/datasets/{dataset.id}",
            "reference": snapshot.provenance(),
        }
    )


@app.command()
def calibrate(
    max_cost_usd: float = typer.Option(..., min=0.01),
    deadline_seconds: float = typer.Option(..., min=1),
    split: str = "validation",
    judge_model: str | None = None,
    limit: int | None = typer.Option(None, min=1),
    artifact_root: Path = Path(".artifacts/evaluation"),
) -> None:
    """Blind-grade synthetic controls; human calibration remains a separate approval."""
    from evaluation.data import load_calibration
    from evaluation.graders.calibration import calibrate as evaluate

    controls = load_calibration(split)
    if limit:
        controls = controls[:limit]

    async def execute():
        judge = _judge(judge_model, max_cost_usd, deadline_seconds)
        try:
            return await evaluate(controls, judge, artifact_root)
        finally:
            await judge.close()

    typer.echo(str(asyncio.run(execute())))


@app.command()
def compare(
    baseline: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    candidate: Annotated[Path, typer.Option(exists=True, file_okay=False)],
) -> None:
    """Compare compatible grading directories, preserving unresolved outcomes."""
    from evaluation.reporting.compare import compare as compare_grades

    echo(compare_grades(baseline, candidate))


if __name__ == "__main__":
    app()
