"""Bounded LangGraph evaluations with independent grading and Foundry experiments."""

import asyncio
import json
from pathlib import Path

import typer

from evaluation.settings import EvaluationSettings, validate_run_budget
from retail_insight.config import Settings, repository_root

app = typer.Typer(no_args_is_help=True)


def cost_limit(value: float):
    try:
        return validate_run_budget(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


def echo(value):
    typer.echo(json.dumps(value, indent=2, default=str))


def _judge(model, max_cost_usd, deadline_seconds):
    from evaluation.graders.judge import GeminiJudge

    settings = Settings.load()
    return GeminiJudge(
        settings.gemini_api_key.get_secret_value(),
        EvaluationSettings(judge_model=model or settings.gemini_model),
        max_cost_usd=validate_run_budget(max_cost_usd),
        deadline_seconds=deadline_seconds,
    )


@app.command()
def validate():
    """Verify independent fixtures and reference calculations; no API calls."""
    from evaluation.data import validate_dataset

    result = validate_dataset()
    echo(result)
    if result.get("errors"):
        raise typer.Exit(1)


@app.command()
def cases(suite: str = "pilot"):
    from evaluation.data import load_cases

    echo([{"id": c.id, "steps": len(c.steps)} for c in load_cases(suite)])


@app.command()
def run(
    suite: str = "smoke",
    repetitions: int = 1,
    allow_unreviewed: bool = False,
    max_cost_usd: float = typer.Option(5, callback=cost_limit),
    deadline_seconds: float = 600,
):
    """Run diagnostic fixture cases, grade answers/trajectories, publish to Foundry."""
    from evaluation.data import load_cases
    from evaluation.runners.pipeline import run_pipeline

    try:
        selected = load_cases(suite)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    if not allow_unreviewed and any(not c.provenance.human_reviewed for c in selected):
        raise typer.BadParameter(
            "References await human review. Use --allow-unreviewed for diagnostic runs."
        )
    settings = Settings.load()
    result = asyncio.run(
        run_pipeline(
            selected,
            settings,
            EvaluationSettings(),
            suite=suite,
            repetitions=repetitions,
            max_cost_usd=max_cost_usd,
            deadline_seconds=deadline_seconds,
            judge=_judge(None, max_cost_usd, deadline_seconds),
            grade_candidates=True,
            progress=typer.echo,
        )
    )
    raise typer.Exit(result.exit_code)


@app.command()
def run_conversations(
    only: str | None = None,
    max_cost_usd: float = typer.Option(5, callback=cost_limit),
    deadline_seconds: float = 1800,
    reference_directory: Path | None = None,
):
    """Run the 20 authored retail conversations against a pinned BigQuery snapshot."""
    from evaluation.runners.authored import run_authored
    from evaluation.runners.manual import load_scenarios

    scenarios = load_scenarios(repository_root() / "evaluation/scenarios/manual_20.json", only)
    directory, summary = asyncio.run(
        run_authored(
            scenarios,
            Settings.load(),
            EvaluationSettings(),
            max_cost_usd=max_cost_usd,
            deadline_seconds=deadline_seconds,
            reference_directory=reference_directory,
        )
    )
    typer.echo(str(directory))
    echo(summary)
    raise typer.Exit(summary["exit_code"])


@app.command()
def run_multi_agent(
    suite: str = "smoke",
    only: str | None = None,
    max_cost_usd: float = typer.Option(5, callback=cost_limit),
    deadline_seconds: float = 1800,
    backend: str = "fixture",
    concurrency: int = 1,
    publish_only: bool = False,
    agent_budget_usd: float = 1,
):
    """Run the inventory, distribution and coordinator suites as local graphs."""
    from evaluation.multi_agent.runner import run as execute

    directory, code = asyncio.run(
        execute(
            suite=suite,
            only=only,
            max_cost_usd=max_cost_usd,
            deadline_seconds=deadline_seconds,
            backend=backend,
            concurrency=concurrency,
            publish_only=publish_only,
            agent_budget_usd=agent_budget_usd,
        )
    )
    typer.echo(str(directory))
    raise typer.Exit(code)


@app.command()
def export_prompts():
    """Save exact local prompt snapshots and hashes for evaluation provenance."""
    from evaluation.prompt_catalog import judge_prompt
    from retail_insight.observability.prompts import sync_prompts as upload
    from retail_insight.runtime.prompts import agent_prompt, analyst_prompt, reviewer_prompt

    settings = Settings.load()
    root = repository_root() / "src/retail_insight"
    specs = [
        analyst_prompt(settings),
        reviewer_prompt(settings),
        judge_prompt(EvaluationSettings(), "answer"),
        judge_prompt(EvaluationSettings(), "trajectory"),
    ]
    specs += [
        agent_prompt(
            settings,
            name="retail-" + role,
            path=root / f"agents/{role}/prompt.md",
            model=settings.gemini_model,
            common=root / "runtime/prompt.md",
        )
        for role in ("coordinator", "inventory", "distribution")
    ]
    echo(upload(specs))


@app.command()
def grade(
    run_directory: Path = typer.Option(..., "--run"),  # noqa: B008
    max_cost_usd: float = typer.Option(5, callback=cost_limit),
    deadline_seconds: float = 600,
    code_only: bool = False,
    candidates: bool = True,
    trajectory: bool = True,
):
    """Regrade saved diagnostic outputs without rerunning the agent."""
    from evaluation.graders.runner import grade_run

    async def execute():
        judge = None if code_only else _judge(None, max_cost_usd, deadline_seconds)
        try:
            return await grade_run(
                run_directory, judge, grade_candidates=candidates, grade_trajectory=trajectory
            )
        finally:
            if judge:
                await judge.close()

    typer.echo(str(asyncio.run(execute())))


@app.command()
def calibrate(
    max_cost_usd: float = typer.Option(5, callback=cost_limit), deadline_seconds: float = 600
):
    from evaluation.data import load_calibration
    from evaluation.graders.calibration import calibrate as execute

    async def run_controls():
        judge = _judge(None, max_cost_usd, deadline_seconds)
        try:
            return await execute(load_calibration(), judge, Path(".artifacts/calibration"))
        finally:
            await judge.close()

    typer.echo(str(asyncio.run(run_controls())))


@app.command()
def compare(baseline: Path, candidate: Path):
    from evaluation.reporting.compare import compare as compare_saved

    echo(compare_saved(baseline, candidate))


if __name__ == "__main__":
    app()
