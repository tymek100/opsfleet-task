"""Capture bounded, authored conversations for independent transcript review.

This runner uses the real agent and the explicitly selected backend. It does not
invent reference values, score its own answers, or treat authored prompts as
production traffic. Each case owns an isolated report library.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from evaluation.results import TurnRecord
from evaluation.runners.artifacts import digest, identifier, read_json, write_json
from evaluation.runners.conversation import _capture_turn, report_state
from retail_agent.config import Settings, repository_root
from retail_agent.contracts import DEMO_USERS
from retail_agent.observability import sanitize_capture
from retail_agent.runtime import Analyst


class InitialReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: str
    title: str
    markdown: str


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    identity: str = "alice"
    prompt: str = Field(min_length=1, max_length=6000)
    follow_up: str = Field(min_length=1, max_length=6000)
    intent: str
    checks: list[str]
    oracle_topics: list[str] = Field(default_factory=list)
    golden_enabled: bool = False
    initial_reports: list[InitialReport] = Field(default_factory=list)


def load_scenarios(path: Path, only: str | None = None) -> list[Scenario]:
    cases = [Scenario.model_validate(item) for item in read_json(path)]
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("Scenario IDs must be unique and the selection must be nonempty")
    if any(
        case.identity not in DEMO_USERS
        or any(report.owner not in DEMO_USERS for report in case.initial_reports)
        for case in cases
    ):
        raise ValueError("Unknown demo identity in scenario")
    if only:
        selected = set(only.split(","))
        if not selected <= {case.id for case in cases}:
            raise ValueError("Unknown selected scenario ID")
        cases = [case for case in cases if case.id in selected]
    return cases


def _source_paths() -> list[Path]:
    root = repository_root()
    return sorted(
        [
            *root.glob("src/retail_agent/**/*.py"),
            *root.glob("src/retail_agent/**/*.md"),
            *root.glob("knowledge/golden/*.json"),
            root / "evaluation/runners/manual.py",
            root / "evaluation/runners/conversation.py",
            root / "evaluation/results.py",
            root / "uv.lock",
        ]
    )


def _save_turn(directory: Path, record: TurnRecord, manifest: dict, *, secrets: tuple[str, ...]):
    payload = sanitize_capture(record.model_dump(mode="json"), secrets)
    path = directory / f"{record.step_id}.json"
    if path.exists():
        raise ValueError("Captured turns cannot be overwritten")
    write_json(path, payload)
    manifest["turn_hashes"][str(path.relative_to(directory.parents[1]))] = digest(path)
    # Each answer is readable while later conversations are still running.
    turns = [read_json(path) for path in sorted(directory.glob("turn-*.json"))]
    lines = [f"# {directory.name}", "", "Independent review: pending.", ""]
    for turn in turns:
        lines.extend(
            [
                f"## {turn['step_id']}",
                "",
                f"**User:** {turn['prompt']}",
                "",
                turn["markdown"] or f"No published answer. {turn.get('error') or ''}",
                "",
                f"Status: `{turn['status']}`; elapsed: {turn['elapsed_seconds']:.1f}s; "
                f"accounted cost: {turn['usage'].get('accounted_usd', 0):.6f} USD.",
                "",
            ]
        )
    (directory / "transcript.md").write_text("\n".join(lines))


async def run_manual(
    scenarios: list[Scenario],
    settings: Settings,
    *,
    output_root: Path,
    backend: str,
    max_cost_usd: float,
    deadline_seconds: float,
    phase: str = "baseline",
    fixture_path: Path | None = None,
    clock_utc: datetime | None = None,
    data_note: str = "",
    phoenix: bool = False,
    phoenix_url: str = "http://127.0.0.1:6006",
    app_factory: Callable = Analyst,
    progress: Callable[[str], None] = lambda message: print(message, flush=True),
) -> Path:
    if (
        not scenarios
        or backend not in {"bigquery", "fixture"}
        or not all(math.isfinite(v) and v > 0 for v in (max_cost_usd, deadline_seconds))
        or len({case.id for case in scenarios}) != len(scenarios)
    ):
        raise ValueError("Unique scenarios, an explicit backend, and positive limits are required")
    if backend == "bigquery" and fixture_path is not None:
        raise ValueError("A fixture path cannot be used with the BigQuery backend")
    if phase not in {"baseline", "recheck"}:
        raise ValueError("Phase must be baseline or recheck")
    now = clock_utc or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("The reporting clock must include its timezone")
    now = now.astimezone(UTC)
    deadline = time.monotonic() + deadline_seconds
    directory = output_root / identifier(f"manual-{phase}")
    directory.mkdir(parents=True, exist_ok=False)
    root = repository_root()
    sources = _source_paths()
    hashes = {str(path.relative_to(root)): digest(path) for path in sources}
    for path in sources:
        target = directory / "sources" / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    scenario_path = directory / "scenarios.json"
    write_json(scenario_path, [case.model_dump(mode="json") for case in scenarios])
    updates: dict[str, Any] = {"backend": backend}
    data_source = {"backend": backend, "note": data_note}
    if backend == "fixture":
        source = fixture_path or settings.fixture_path
        frozen = directory / "data" / "warehouse.sql"
        frozen.parent.mkdir()
        frozen.write_bytes(source.read_bytes())
        data_source.update(fixture_sha256=digest(frozen), fixture_file="data/warehouse.sql")
        updates["fixture_path"] = frozen
    else:
        data_source["dataset"] = settings.warehouse_source_dataset
    config = settings.model_copy(update=updates)
    manifest = {
        "id": directory.name,
        "created_at": datetime.now(UTC).isoformat(),
        "phase": phase,
        "scenario_provenance": "assistant-authored; not captured production conversations",
        "capture": "full sanitized application observations; hidden model thoughts excluded",
        "independent_review": "pending",
        "data_source": data_source,
        "clock_utc": now.isoformat(),
        "scenario_sha256": digest(scenario_path),
        "source_sha256": hashes,
        "model": settings.gemini_model,
        "settings": config.model_dump(
            mode="json",
            exclude={
                "gemini_api_key",
                "google_cloud_project",
                "data_dir",
                "golden_path",
                "fixture_path",
            },
        ),
        "max_cost_usd": max_cost_usd,
        "deadline_seconds": deadline_seconds,
        "planned_cases": len(scenarios),
        "planned_turns": 2 * len(scenarios),
    }
    write_json(directory / "manifest.json", manifest)
    state = {
        "status": "running",
        "accounted_usd": 0.0,
        "captured_turns": 0,
        "executed_turns": 0,
        "turn_hashes": {},
    }
    progress(f"Manual run: {directory}")
    progress(f"Backend: {backend}; {len(scenarios)} conversations; {2 * len(scenarios)} turns")
    progress(f"Shared limit: ${max_cost_usd:g}; {deadline_seconds:g}s. Independent review pending.")
    secrets = (settings.gemini_api_key.get_secret_value(),)
    write_json(directory / "progress.json", state)
    tracing = None
    try:
        if phoenix:
            from evaluation.reporting.phoenix import client_for
            from evaluation.reporting.phoenix_service import ensure_phoenix
            from evaluation.settings import EvaluationSettings
            from retail_agent.observability import configure_tracing

            phoenix_settings = EvaluationSettings(phoenix_url=phoenix_url)
            await asyncio.to_thread(
                ensure_phoenix, phoenix_settings, deadline=deadline, progress=progress
            )
            client = client_for(phoenix_settings, deadline=deadline)
            project = await asyncio.to_thread(
                client.projects.create,
                name=directory.name,
                description="Authored manual scenarios against the explicitly selected data source.",
            )
            url = phoenix_url + "/projects/" + quote(project["id"], safe="")
            state["phoenix"] = {"project_id": project["id"], "url": url}
            tracing = configure_tracing(
                phoenix_url + "/v1/traces", project=directory.name, mode="synthetic"
            )
            progress(f"Phoenix traces: {url}")
            write_json(directory / "progress.json", state)
        for scenario in scenarios:
            case_dir = directory / "cases" / scenario.id
            case_dir.mkdir(parents=True)
            with TemporaryDirectory(prefix="retail-manual-") as temporary:
                isolated = config.model_copy(
                    update={
                        "data_dir": Path(temporary),
                        "golden_bootstrap": scenario.golden_enabled,
                    }
                )
                app = None
                events: list[dict] = []
                try:
                    for index, question in enumerate((scenario.prompt, scenario.follow_up), 1):
                        step_id = f"turn-{index}"
                        remaining = max_cost_usd - state["accounted_usd"]
                        time_left = deadline - time.monotonic()
                        if remaining <= 0 or time_left < 1:
                            record = TurnRecord(
                                step_id=step_id,
                                prompt=question,
                                status="NOT_EXECUTED",
                                error="Shared cost or time limit exhausted",
                            )
                        else:
                            if any(digest(root / name) != value for name, value in hashes.items()):
                                raise ValueError(
                                    "Runtime sources changed during capture; start a new run"
                                )
                            if app is None:
                                app = app_factory(
                                    isolated,
                                    DEMO_USERS[scenario.identity],
                                    clock=lambda: now,
                                    observer=events.append,
                                    observation_mode="synthetic",
                                )
                                for seed_index, report in enumerate(scenario.initial_reports):
                                    app.reports.save(
                                        report.owner,
                                        report.title,
                                        report.markdown,
                                        [],
                                        f"manual-seed-{seed_index}",
                                    )
                            allowance = min(isolated.question_budget_usd, remaining)
                            app.settings = isolated.model_copy(
                                update={
                                    "question_budget_usd": allowance,
                                    "turn_timeout_seconds": min(
                                        isolated.turn_timeout_seconds, time_left
                                    ),
                                }
                            )
                            before = report_state(app.reports)
                            events.clear()
                            progress(f"{scenario.id}/{step_id}: running ({scenario.identity})")
                            started = time.monotonic()
                            try:
                                async with asyncio.timeout(time_left):
                                    result = await app.ask(question)
                                record = _capture_turn(
                                    SimpleNamespace(id=step_id, message=question),
                                    result,
                                    events,
                                    before,
                                    report_state(app.reports),
                                    capture_errors=app.observer_errors,
                                )
                                cost = float(result.usage.get("accounted_usd", allowance))
                            except BaseException as exc:
                                # Unknown in-flight usage retains the whole prompt reservation.
                                cost = allowance
                                record = TurnRecord(
                                    step_id=step_id,
                                    prompt=question,
                                    status="ERROR",
                                    timeline=events,
                                    reports_before=before,
                                    reports_after=report_state(app.reports),
                                    usage={"accounted_usd": cost, "usage_unknown": True},
                                    elapsed_seconds=time.monotonic() - started,
                                    error=f"Interrupted execution: {type(exc).__name__}",
                                )
                                state["accounted_usd"] += cost
                                state["executed_turns"] += 1
                                _save_turn(case_dir, record, state, secrets=secrets)
                                state["captured_turns"] += 1
                                write_json(directory / "progress.json", state)
                                raise
                            state["accounted_usd"] += cost
                            state["executed_turns"] += 1
                        _save_turn(case_dir, record, state, secrets=secrets)
                        state["captured_turns"] += 1
                        write_json(directory / "progress.json", state)
                        progress(
                            f"{scenario.id}/{step_id}: {record.status}; {record.elapsed_seconds:.1f}s; "
                            f"total accounted ${state['accounted_usd']:.4f}"
                        )
                finally:
                    if app is not None:
                        app.reports.close()
        state["status"] = (
            "captured" if state["executed_turns"] == manifest["planned_turns"] else "incomplete"
        )
    except BaseException:
        state["status"] = "interrupted"
        raise
    finally:
        if tracing is not None:
            flushed = tracing.close()
            state["trace_status"] = (
                "complete" if flushed and not tracing.failed_exports else "incomplete"
            )
            if state["trace_status"] == "incomplete" and state["status"] == "captured":
                state["status"] = "incomplete"
        state["finished_at"] = datetime.now(UTC).isoformat()
        write_json(directory / "progress.json", state)
        progress(f"Captured results: {directory}; status: {state['status']}")
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenarios", type=Path, default=Path("evaluation/scenarios/manual_20.json")
    )
    parser.add_argument("--output-root", type=Path, default=Path(".artifacts/manual"))
    parser.add_argument("--only")
    parser.add_argument("--phase", choices=("baseline", "recheck"), default="baseline")
    parser.add_argument("--backend", choices=("bigquery", "fixture"), required=True)
    parser.add_argument("--fixture-path", type=Path)
    parser.add_argument("--clock-utc", type=datetime.fromisoformat)
    parser.add_argument("--data-note", default="")
    parser.add_argument("--phoenix", action="store_true")
    parser.add_argument("--phoenix-url", default="http://127.0.0.1:6006")
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--deadline-seconds", type=float, required=True)
    args = parser.parse_args()
    scenarios = load_scenarios(args.scenarios, args.only)
    settings = Settings.load()
    if not settings.gemini_api_key.get_secret_value():
        parser.error("GEMINI_API_KEY is required for real-model conversation capture")
    directory = asyncio.run(
        run_manual(
            scenarios,
            settings,
            output_root=args.output_root,
            backend=args.backend,
            max_cost_usd=args.max_cost_usd,
            deadline_seconds=args.deadline_seconds,
            phase=args.phase,
            fixture_path=args.fixture_path,
            clock_utc=args.clock_utc,
            data_note=args.data_note,
            phoenix=args.phoenix,
            phoenix_url=args.phoenix_url,
        )
    )
    if read_json(directory / "progress.json")["status"] != "captured":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
