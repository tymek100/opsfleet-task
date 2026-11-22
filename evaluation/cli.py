"""Explicit, bounded execution and independent regrading commands."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from evaluation.settings import EvaluationSettings

app = typer.Typer(
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
    help="Independent retail-agent evaluation with local Phoenix.",
)


def echo(value) -> None:
    typer.echo(json.dumps(value, indent=2, default=str))


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

    dataset = sync_cases(load_cases(suite), EvaluationSettings(phoenix_url=phoenix_url))
    echo({"dataset_id": dataset.id, "version_id": dataset.version_id, "name": dataset.name})


@app.command()
def run(
    suite: str = "smoke",
    repetitions: int = typer.Option(3, min=1, max=20),
    max_cost_usd: float = typer.Option(..., min=0.01),
    deadline_seconds: float = typer.Option(..., min=1),
    allow_unreviewed: bool = False,
    phoenix: bool = False,
    phoenix_url: str = "http://127.0.0.1:6006",
    model: str | None = None,
    artifact_root: Path = Path(".artifacts/evaluation"),
) -> None:
    """Run real models on isolated frozen fixtures. Each prompt has a fresh budget."""
    from evaluation.data import load_cases
    from evaluation.runners.conversation import run_cases
    from retail_agent.config import Settings
    from retail_agent.observability import configure_tracing

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
    config = EvaluationSettings(artifact_root=artifact_root, phoenix_url=phoenix_url)
    tracing = (
        configure_tracing(
            config.phoenix_url + "/v1/traces", project="retail-evaluation", mode="synthetic"
        )
        if phoenix
        else None
    )
    try:
        directory = asyncio.run(
            run_cases(
                selected,
                settings,
                artifact_root=artifact_root,
                suite=suite,
                repetitions=repetitions,
                max_cost_usd=max_cost_usd,
                deadline_seconds=deadline_seconds,
            )
        )
    finally:
        if tracing and not tracing.close():
            typer.echo("Phoenix trace flush was incomplete; local artifacts remain available.")
    typer.echo(str(directory))
    if phoenix:
        from evaluation.reporting.phoenix import publish

        echo(publish(directory, config))


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
    judge_model: str | None = None,
    phoenix: bool = False,
    phoenix_url: str = "http://127.0.0.1:6006",
) -> None:
    """Grade saved outputs into a new version; the agent is never rerun."""
    from evaluation.graders.runner import grade_run

    async def execute():
        judge = None if code_only else _judge(judge_model, max_cost_usd, deadline_seconds)
        try:
            return await grade_run(run_directory, judge, grade_candidates=candidates)
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

    result = upload(
        run_directory, EvaluationSettings(phoenix_url=phoenix_url), grade=grade_directory
    )
    echo(result)
    if result["status"] != "published":
        raise typer.Exit(1)


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
