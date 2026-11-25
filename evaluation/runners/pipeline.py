"""One bounded experiment: capture, grade, and publish each completed trial."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from evaluation.data import validate_case
from evaluation.graders.runner import grade_trial, prepare_grade, record_grade
from evaluation.prompt_catalog import judge_prompt
from evaluation.reporting.phoenix import PhoenixPublisher
from evaluation.reporting.phoenix_service import PhoenixUnavailable, ensure_phoenix
from evaluation.reporting.summary import write_summary
from evaluation.results import RunManifest, Trial
from evaluation.runners.artifacts import read_json, write_json
from evaluation.runners.conversation import run_cases
from evaluation.settings import validate_run_budget
from retail_insight.agents.retail.agent import RetailAnalyst as Analyst
from retail_insight.integrations.phoenix.prompts import sync_prompts
from retail_insight.integrations.phoenix.tracing import configure_tracing
from retail_insight.runtime.prompts import analyst_prompt, reviewer_prompt


@dataclass(frozen=True)
class PipelineResult:
    run: Path
    grade: Path
    summary: dict
    publication: dict
    exit_code: int


def outcome_code(summary: dict, publication: dict) -> int:
    """Distinguish unresolved execution from observed diagnostic failures."""
    trajectories = summary.get("trajectory", {})
    trajectory_statuses = trajectories.get("statuses", {})
    if (
        publication.get("status") != "published"
        or summary["unresolved_or_missing"]
        or summary.get("unresolved_required_checks", 0)
        or summary.get("candidate_grading", {}).get("missing", 0)
        or summary.get("candidate_grading", {}).get("unresolved", 0)
        or any(trajectory_statuses.get(status) for status in ("ERROR", "UNJUDGEABLE"))
        or trajectories.get("missing", 0)
        or trajectories.get("unresolved", 0)
    ):
        return 2
    if summary["statuses"].get("FAIL") or trajectory_statuses.get("FAIL"):
        return 1
    return 0


async def run_pipeline(
    cases,
    settings,
    config,
    *,
    suite: str,
    repetitions: int,
    max_cost_usd: float,
    deadline_seconds: float,
    judge,
    grade_candidates: bool = True,
    app_factory: Callable = Analyst,
    publisher_factory=PhoenixPublisher,
    service=ensure_phoenix,
    tracing_factory=configure_tracing,
    prompts_sync=sync_prompts,
    progress=print,
) -> PipelineResult:
    """All agent and judge calls share one cost ceiling and absolute deadline.

    Trials are sequential: the next agent allowance excludes all prior grading
    costs, and the judge ceiling excludes all agent costs. Provider admission
    retains unknown usage reservations inside both existing accounting ledgers.
    """
    validate_run_budget(max_cost_usd)
    deadline = time.monotonic() + deadline_seconds
    judge.deadline = deadline
    tracing = None
    publisher = None
    directory = None
    grade_directory = None

    async def started(run: Path, manifest: RunManifest) -> None:
        nonlocal publisher, tracing, directory, grade_directory
        directory = run
        try:
            prompts = await asyncio.to_thread(
                prompts_sync,
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
            raise PhoenixUnavailable(
                f"Prompt synchronization failed ({type(exc).__name__}); no model calls were made."
            ) from None
        write_json(run / "prompts.json", prompts)
        progress(f"Prompt library: {config.phoenix_url}/prompts")
        publisher = publisher_factory(run, config, deadline=deadline, project=manifest.id)
        state = await asyncio.to_thread(publisher.start)
        progress(f"Phoenix experiment: {state['url']}")
        progress(f"Phoenix traces: {state['traces_url']}")
        progress(f"Local results: {run}")
        progress(
            f"Shared agent + evaluation limit: ${max_cost_usd:g}; {deadline_seconds:g}s. "
            "Results and scores are published after each completed trial."
        )
        tracing = tracing_factory(
            config.phoenix_url + "/v1/traces", project=manifest.id, mode="synthetic"
        )
        tracing.register_prompts(prompts)
        grade_directory = prepare_grade(
            run, judge, grade_candidates=grade_candidates, grade_trajectory=True
        )
        manifest.pipeline = {
            "mode": "end-to-end",
            "status": "running",
            "grade_id": grade_directory.name,
            "accounted_total_usd": 0,
            "prompt_versions": prompts,
        }
        write_json(run / "manifest.json", manifest)

    async def completed(run: Path, trial: Trial, manifest: RunManifest) -> None:
        assert publisher is not None and grade_directory is not None
        if trial.status != "NOT_EXECUTED":
            if tracing is not None:
                await asyncio.to_thread(tracing.provider.force_flush, timeout_millis=1000)
            state = await asyncio.to_thread(publisher.publish_trial, trial)
            if state["status"] == "publication_failed":
                progress("Phoenix upload failed; continuing with preserved local results.")
        judge.ceiling = max(0, max_cost_usd - manifest.accounted_usd)
        case = next(case for case in cases if case.id == trial.case_id)
        progress(f"{trial.id}: evaluating answers and trajectory")
        grade = await grade_trial(
            case, trial, judge, grade_candidates=grade_candidates, grade_trajectory=True
        )
        record_grade(run, grade_directory, grade, judge)
        manifest.pipeline["accounted_total_usd"] = manifest.accounted_usd + judge.accounted_usd
        write_json(run / "manifest.json", manifest)
        write_summary(run, grade_directory)
        if trial.status != "NOT_EXECUTED":
            state = await asyncio.to_thread(publisher.publish_grade, grade_directory, grade)
            if state["status"] == "publication_failed":
                progress("Phoenix score upload is incomplete; saved grades can be published later.")
        progress(
            f"{trial.id}: answer checks {grade.status}; "
            f"total accounted ${manifest.pipeline['accounted_total_usd']:.4f}"
        )

    try:
        if (
            not cases
            or not 1 <= repetitions <= 20
            or not all(math.isfinite(v) and v > 0 for v in (max_cost_usd, deadline_seconds))
        ):
            raise ValueError("Cases, positive limits, and 1-20 repetitions are required")
        if len({case.id for case in cases}) != len(cases):
            raise ValueError("Case IDs must be unique")
        for case in cases:
            validate_case(case)
        await asyncio.to_thread(service, config, deadline=deadline, progress=progress)
        directory = await run_cases(
            cases,
            settings,
            artifact_root=config.artifact_root,
            suite=suite,
            repetitions=repetitions,
            max_cost_usd=max_cost_usd,
            deadline_seconds=deadline_seconds,
            deadline=deadline,
            app_factory=app_factory,
            progress=progress,
            on_start=started,
            on_trial=completed,
            external_cost=lambda: judge.accounted_usd,
        )
        assert grade_directory is not None and publisher is not None
        record_grade(directory, grade_directory, None, judge, complete=True)
        summary = write_summary(directory, grade_directory)
        publication = read_json(directory / "phoenix.json")
        if tracing is not None:
            flushed = tracing.close()
            if not flushed or tracing.failed_exports:
                publication.update(status="publication_failed", trace_status="incomplete")
                write_json(directory / "phoenix.json", publication)
                progress("Phoenix trace export was incomplete; local captures are preserved.")
            tracing = None
        exit_code = outcome_code(summary, publication)
        manifest = read_json(directory / "manifest.json")
        manifest["pipeline"].update(
            status="completed" if exit_code != 2 else "incomplete",
            exit_code=exit_code,
            accounted_total_usd=manifest["accounted_usd"] + judge.accounted_usd,
        )
        write_json(directory / "manifest.json", manifest)
        progress(f"Summary: {grade_directory / 'summary.md'}")
        progress(
            f"Results: {summary['statuses']}; "
            f"unresolved or missing: {summary['unresolved_or_missing']}; "
            f"total accounted ${manifest['pipeline']['accounted_total_usd']:.4f}"
        )
        progress(
            f"Trajectory: {summary['trajectory']['statuses']}; "
            f"unresolved required checks: {summary['unresolved_required_checks']}; "
            f"missing or unresolved draft grades: "
            f"{summary['candidate_grading']['missing'] + summary['candidate_grading']['unresolved']}"
        )
        progress(f"Publication: {publication['status']}; exit code: {exit_code}")
        return PipelineResult(directory, grade_directory, summary, publication, exit_code)
    except BaseException:
        if directory is not None:
            manifest = read_json(directory / "manifest.json")
            manifest.setdefault("pipeline", {}).update(
                status="interrupted",
                accounted_total_usd=manifest["accounted_usd"] + judge.accounted_usd,
            )
            write_json(directory / "manifest.json", manifest)
            if grade_directory is not None:
                write_json(grade_directory / "judge_calls.json", judge.calls)
            progress(f"Evaluation stopped; captured results are preserved in {directory}")
        raise
    finally:
        if tracing and not tracing.close():
            progress("Phoenix trace flush was incomplete; local captures remain available.")
        try:
            await judge.close()
        except Exception:
            progress("Judge client cleanup was incomplete.")
