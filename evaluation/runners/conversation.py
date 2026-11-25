"""Bounded, isolated conversations around the real Analyst public boundary."""

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluation.models import Case
from evaluation.results import RunManifest, Trial, TurnRecord
from evaluation.runners.artifacts import digest, prepare_run, write_json
from evaluation.runners.faults import FaultGateway, FaultModel, FaultReports, Schedule
from retail_insight.agents.retail.agent import RetailAnalyst as Analyst
from retail_insight.config import Settings
from retail_insight.contracts import DEMO_USERS
from retail_insight.integrations.phoenix.tracing import span
from retail_insight.runtime.provider import make_gemini


def report_state(store) -> list[dict]:
    """Inspect the isolated database across owners, never a user's real store."""
    rows = store.db.execute(
        "SELECT id, owner, title, markdown, answer_id, version FROM agent_reports ORDER BY id"
    ).fetchall()
    return [dict(row) for row in rows]


def _capture_turn(
    step,
    result,
    events: list[dict],
    before: list[dict],
    after: list[dict],
    *,
    capture_errors=0,
) -> TurnRecord:
    events = [
        {**event, "event_id": f"{step.id}:e{index + 1}"} for index, event in enumerate(events)
    ]
    candidates = []
    visible = []
    for event in events:
        if event["event"] == "tool_observation":
            visible.append(event)
        if event["event"] == "answer_candidate":
            candidates.append({**event, "visible_observations": list(visible)})
        elif event["event"] == "review_result" and candidates:
            candidates[-1]["review"] = event.get("review", {})
    context = next((e.get("context", {}) for e in events if e["event"] == "initial_context"), {})
    available_tools = next(
        (e.get("available_tools") for e in events if e["event"] == "available_tools"), None
    )
    if available_tools is not None:
        context = {**context, "available_tools": available_tools}
    capture_errors = max(
        capture_errors,
        max(
            (e.get("capture_errors", 0) for e in events if e["event"] == "turn_result"),
            default=0,
        ),
    )
    return TurnRecord(
        step_id=step.id,
        prompt=step.message,
        status="ERROR" if capture_errors else result.status,
        markdown=result.answer.markdown if result.answer else None,
        outcome=result.answer.outcome if result.answer else None,
        evidence_ids=result.answer.evidence_ids if result.answer else [],
        evidence=result.evidence,
        observations=[e for e in events if e["event"] == "tool_observation"],
        candidates=candidates,
        context=context,
        timeline=events,
        trace_id=next((e.get("trace_id") for e in events if e.get("trace_id")), None),
        span_id=next((e.get("span_id") for e in events if e.get("span_id")), None),
        trace=result.trace,
        usage=result.usage,
        elapsed_seconds=result.elapsed_seconds,
        reports_before=before,
        reports_after=after,
        receipts=result.answer.receipts if result.answer else [],
        error=f"Incomplete synthetic capture: {capture_errors} errors"
        if capture_errors
        else result.message or None,
    )


async def run_trial(
    case: Case,
    repetition: int,
    settings: Settings,
    fixture: Path,
    *,
    remaining_usd: float,
    deadline: float,
    app_factory: Callable = Analyst,
) -> Trial:
    started = time.monotonic()
    trial = Trial(
        id=f"{case.id}-r{repetition}",
        case_id=case.id,
        repetition=repetition,
        started_at=datetime.now(UTC).isoformat(),
        status="running",
    )
    events: list[dict] = []
    with TemporaryDirectory(prefix="retail-eval-") as temporary:
        directory = Path(temporary)
        isolated = settings.model_copy(
            update={
                "backend": "fixture",
                "fixture_path": fixture,
                "data_dir": directory,
                "golden_bootstrap": case.golden_enabled,
            }
        )
        schedule = Schedule(case.faults)
        reports = FaultReports(
            directory / "reports.sqlite3", clock=lambda: case.clock_utc.timestamp()
        )
        reports.schedule = Schedule([])
        for seed_index, seed in enumerate(case.initial_reports):
            reports.save(seed.owner, seed.title, seed.markdown, [], f"seed-{seed_index}")
        reports.schedule = schedule
        gateway = FaultGateway(
            brands=DEMO_USERS[case.identity].brands,
            backend="fixture",
            fixture_path=fixture,
            clock=lambda: case.clock_utc,
        )
        gateway.schedule = schedule
        kwargs: dict = {
            "gateway": gateway,
            "reports": reports,
            "clock": lambda: case.clock_utc,
            "observer": events.append,
            "observation_mode": "synthetic",
        }
        if any(f.boundary == "provider" for f in case.faults):
            delegate = make_gemini(isolated)
            kwargs["model"] = FaultModel(model=delegate.model, delegate=delegate).bind(schedule)
        app = None
        try:
            app = app_factory(isolated, DEMO_USERS[case.identity], **kwargs)
            preview = None
            previous_outcome = None
            for step in case.steps:
                before = report_state(reports)
                if (
                    step.when_previous_outcome
                    and previous_outcome not in step.when_previous_outcome
                ):
                    trial.turns.append(
                        TurnRecord(
                            step_id=step.id,
                            kind=step.kind,
                            prompt=step.message,
                            status="NOT_APPLICABLE",
                        )
                    )
                    continue
                cost_left = remaining_usd - trial.accounted_usd
                time_left = deadline - time.monotonic()
                if cost_left <= 0 or time_left < 1:
                    trial.turns.append(
                        TurnRecord(
                            step_id=step.id,
                            kind=step.kind,
                            prompt=step.message,
                            status="NOT_EXECUTED",
                            error="Run budget exhausted",
                        )
                    )
                    continue
                events.clear()
                try:
                    async with asyncio.timeout(time_left):
                        if step.kind == "ask":
                            app.settings = isolated.model_copy(
                                update={
                                    "question_budget_usd": min(
                                        isolated.question_budget_usd, cost_left
                                    ),
                                    "turn_timeout_seconds": min(
                                        isolated.turn_timeout_seconds, time_left
                                    ),
                                }
                            )
                            result = await app.ask(step.message)
                            preview = result.deletion_preview
                            previous_outcome = result.answer.outcome if result.answer else None
                            record = _capture_turn(
                                step,
                                result,
                                events,
                                before,
                                report_state(reports),
                                capture_errors=getattr(app, "observer_errors", 0),
                            )
                            trial.accounted_usd += float(result.usage.get("accounted_usd", 0))
                        elif step.kind == "confirm_delete":
                            if not preview or not preview.get("token"):
                                raise ValueError("No confirmation preview was produced")
                            receipt = app.confirm_delete(preview["token"])
                            preview = None
                            record = TurnRecord(
                                step_id=step.id,
                                kind=step.kind,
                                status="completed",
                                receipts=[receipt],
                                reports_before=before,
                                reports_after=report_state(reports),
                            )
                        else:
                            receipt = reports.cancel_delete(case.identity, app.conversation_id)
                            preview = None
                            record = TurnRecord(
                                step_id=step.id,
                                kind=step.kind,
                                status="completed",
                                receipts=[receipt],
                                reports_before=before,
                                reports_after=report_state(reports),
                            )
                    trial.turns.append(record)
                except TimeoutError:
                    # A cancelled request may have completed remotely; retain the full prompt allowance.
                    trial.accounted_usd += min(isolated.question_budget_usd, cost_left)
                    trial.turns.append(
                        TurnRecord(
                            step_id=step.id,
                            kind=step.kind,
                            prompt=step.message,
                            status="deadline",
                            error="Run deadline exhausted",
                        )
                    )
                except Exception as exc:
                    if step.kind == "ask":
                        # Provider work may have completed before an unexpected local failure.
                        trial.accounted_usd += min(isolated.question_budget_usd, cost_left)
                    trial.turns.append(
                        TurnRecord(
                            step_id=step.id,
                            kind=step.kind,
                            prompt=step.message,
                            status="ERROR",
                            error=type(exc).__name__,
                        )
                    )
                trial.trace_id = next(
                    (e.get("trace_id") for e in events if e.get("trace_id")), trial.trace_id
                )
            trial.reports_final = report_state(reports)
            trial.status = (
                "completed"
                if all(t.status not in {"NOT_EXECUTED", "ERROR", "deadline"} for t in trial.turns)
                else "incomplete"
            )
        except Exception as exc:
            trial.status, trial.error = "ERROR", type(exc).__name__
        finally:
            reports.close()
    trial.elapsed_seconds = round(time.monotonic() - started, 3)
    trial.ended_at = datetime.now(UTC).isoformat()
    return trial


async def run_cases(
    cases: list[Case],
    settings: Settings,
    *,
    artifact_root: Path,
    suite: str,
    repetitions: int,
    max_cost_usd: float,
    deadline_seconds: float,
    app_factory: Callable = Analyst,
    progress: Callable[[str], None] = print,
    on_start: Callable[[Path, RunManifest], Awaitable[None]] | None = None,
    on_trial: Callable[[Path, Trial, RunManifest], Awaitable[None]] | None = None,
    external_cost: Callable[[], float] | None = None,
    deadline: float | None = None,
) -> Path:
    if (
        not cases
        or not 1 <= repetitions <= 20
        or not math.isfinite(max_cost_usd)
        or max_cost_usd <= 0
        or not math.isfinite(deadline_seconds)
        or deadline_seconds <= 0
    ):
        raise ValueError("Cases, positive limits, and 1-20 repetitions are required")
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("Case IDs must be unique")
    directory, manifest = prepare_run(
        artifact_root,
        cases,
        settings,
        suite=suite,
        repetitions=repetitions,
        max_cost_usd=max_cost_usd,
        deadline_seconds=deadline_seconds,
    )
    deadline = deadline if deadline is not None else time.monotonic() + deadline_seconds
    if on_start is not None:
        await on_start(directory, manifest)
    progress(
        f"Run {manifest.id}: {len(cases)} cases x {repetitions}; model={manifest.model}; "
        f"synthetic capture; cap=${max_cost_usd:g}; deadline={deadline_seconds:g}s"
    )
    for repetition in range(1, repetitions + 1):
        for case in cases:
            left = max_cost_usd - manifest.accounted_usd - (external_cost() if external_cost else 0)
            if left <= 0 or time.monotonic() >= deadline:
                trial = Trial(
                    id=f"{case.id}-r{repetition}",
                    case_id=case.id,
                    repetition=repetition,
                    status="NOT_EXECUTED",
                    error="Run budget exhausted",
                )
            else:
                from evaluation.data import fixture_path

                progress(f"{case.id}-r{repetition}: running {len(case.steps)} steps")
                fixture = directory / "fixtures" / fixture_path(case).name
                with span(
                    "retail.evaluation_trial",
                    **{
                        "openinference.span.kind": "CHAIN",
                        "retail.case_id": case.id,
                        "retail.repetition": repetition,
                        "retail.run_id": manifest.id,
                    },
                ) as current:
                    trial = await run_trial(
                        case,
                        repetition,
                        settings,
                        fixture,
                        remaining_usd=left,
                        deadline=deadline,
                        app_factory=app_factory,
                    )
                    context = current.get_span_context()
                    if context.is_valid:
                        trial.trace_id = format(context.trace_id, "032x")
                        trial.span_id = format(context.span_id, "016x")
            trial_path = directory / "trials" / f"{trial.id}.json"
            write_json(trial_path, trial)
            manifest.trials_sha256[trial_path.name] = digest(trial_path)
            manifest.accounted_usd += trial.accounted_usd
            manifest.completed_trials += int(trial.status == "completed")
            write_json(directory / "manifest.json", manifest)
            progress(
                f"{trial.id}: {trial.status}; {trial.elapsed_seconds:.1f}s; ${trial.accounted_usd:.4f}"
            )
            if on_trial is not None:
                await on_trial(directory, trial, manifest)
    manifest.status = (
        "completed" if manifest.completed_trials == manifest.planned_trials else "incomplete"
    )
    write_json(directory / "manifest.json", manifest)
    return directory
