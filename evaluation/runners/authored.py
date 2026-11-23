"""One bounded run of authored conversations, independent grading and Phoenix reporting."""

from __future__ import annotations

import asyncio
import math
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from evaluation.conversation_references import Snapshot, bundle
from evaluation.graders.conversations import grade_conversation
from evaluation.graders.judge import GeminiJudge
from evaluation.manual_reference import capture
from evaluation.prompt_catalog import judge_prompt
from evaluation.reporting.conversation_experiment import ConversationExperiment
from evaluation.reporting.conversations import PROJECT_NAME
from evaluation.reporting.phoenix import client_for
from evaluation.reporting.phoenix_service import ensure_phoenix
from evaluation.results import TurnRecord
from evaluation.runners.artifacts import digest, identifier, read_json, write_json
from evaluation.runners.manual import load_scenarios, run_manual
from retail_agent.config import repository_root
from retail_agent.observability import configure_tracing, trace_context
from retail_agent.phoenix_prompts import sync_prompts
from retail_agent.prompt_catalog import analyst_prompt, reviewer_prompt
from retail_agent.runtime import Analyst
from retail_agent.services.warehouse import QueryGateway


def final_summary(grades, planned):
    statuses = Counter(g["status"] for g in grades)
    turn_statuses = Counter(t["status"] for g in grades for t in g["turns"])
    all_scores = [s for g in grades for s in g["scores"]] + [
        s for g in grades for t in g["turns"] for s in t["scores"]
    ]
    unresolved = sum(s["status"] in {"ERROR", "UNJUDGEABLE"} for s in all_scores)
    missing = planned - len(grades)
    exit_code = (
        2
        if unresolved or missing
        else 1
        if statuses["FAIL"]
        or any(s["status"] == "FAIL" and s["name"].startswith("trajectory") for s in all_scores)
        else 0
    )
    return {
        "planned_conversations": planned,
        "graded_conversations": len(grades),
        "conversation_statuses": dict(statuses),
        "answer_statuses": dict(turn_statuses),
        "unresolved_checks": unresolved,
        "missing_conversations": missing,
        "exit_code": exit_code,
        "human_calibrated": False,
    }


async def run_authored(
    scenarios,
    settings,
    config,
    *,
    max_cost_usd,
    deadline_seconds,
    phase="recheck",
    reference_directory: Path | None = None,
    output_root=Path(".artifacts/manual"),
    reference_root=Path(".artifacts/manual-reference"),
    progress=print,
    app_factory: Callable = Analyst,
    judge=None,
):
    deadline = time.monotonic() + deadline_seconds
    if not all(math.isfinite(value) and value > 0 for value in (max_cost_usd, deadline_seconds)):
        raise ValueError("Finite positive cost and time limits are required")
    canonical = load_scenarios(repository_root() / "evaluation/scenarios/manual_20.json")
    known = {s.id: s for s in canonical}
    if (
        phase not in {"baseline", "recheck"}
        or not scenarios
        or any(known.get(s.id) != s for s in scenarios)
    ):
        raise ValueError("Select unchanged canonical conversations and a baseline/recheck phase")
    await asyncio.to_thread(ensure_phoenix, config, deadline=deadline, progress=progress)
    reference_cost = 0.0
    if reference_directory is None:
        reference_directory = reference_root / identifier("reference")
        snapshot_at = datetime.now(UTC) - timedelta(seconds=5)
        progress(f"Capturing independent references at warehouse version {snapshot_at.isoformat()}")
        byte_allowance = min(
            settings.max_query_bytes, int(max_cost_usd * 2**40 / settings.bigquery_usd_per_tib / 3)
        )
        manifest = await asyncio.to_thread(
            capture,
            settings,
            reference_directory,
            snapshot_at=snapshot_at,
            max_query_bytes=byte_allowance,
            deadline=deadline,
        )
        reference_cost = (
            sum(j["billed_bytes"] for j in manifest["jobs"].values())
            / 2**40
            * settings.bigquery_usd_per_tib
        )
    snapshot = Snapshot.load(reference_directory)
    if not snapshot.manifest.get("point_in_time_consistent") or not snapshot.manifest.get(
        "snapshot_at"
    ):
        raise ValueError(
            "New evaluations require a timestamp-pinned reference capture; historical unpinned references are for inspection/regrading only"
        )
    if snapshot.manifest["source_dataset"] != settings.warehouse_source_dataset:
        raise ValueError("Reference and agent source datasets differ")
    snapshot_at = datetime.fromisoformat(snapshot.manifest["snapshot_at"])
    references = bundle(canonical, snapshot)
    judge = judge or GeminiJudge(
        settings.gemini_api_key.get_secret_value(),
        config,
        max_cost_usd=max_cost_usd,
        deadline_seconds=max(0.01, deadline - time.monotonic()),
    )
    judge.deadline = deadline
    publisher = None
    tracing = None
    grades = []
    directory = None
    client = client_for(config, deadline=deadline)

    async def started(run):
        nonlocal publisher, tracing, directory
        directory = run
        frozen = run / "reference"
        frozen.mkdir()
        for path in snapshot.directory.glob("*.json"):
            (frozen / path.name).write_bytes(path.read_bytes())
        write_json(run / "references.json", references)
        write_json(run / "reference-scenarios.json", [s.model_dump(mode="json") for s in canonical])
        manifest = read_json(run / "manifest.json")
        manifest.update(
            independent_review="automatic",
            reference_sha256=digest(run / "references.json"),
            reference_source=snapshot.provenance(),
            reference_cost_usd=reference_cost,
        )
        manifest["data_source"]["snapshot_at"] = snapshot_at.isoformat()
        write_json(run / "manifest.json", manifest)
        prompts = await asyncio.to_thread(
            sync_prompts,
            [
                analyst_prompt(settings),
                reviewer_prompt(settings),
                judge_prompt(config, "answer"),
                judge_prompt(config, "trajectory"),
            ],
            config.phoenix_url,
            deadline=deadline,
        )
        write_json(run / "prompts.json", prompts)
        publisher = await asyncio.to_thread(
            ConversationExperiment.start,
            client,
            config,
            run,
            canonical,
            f"Automatic {phase} - {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC ({len(scenarios)} of 20)",
            references,
        )
        tracing = configure_tracing(
            config.phoenix_url + "/v1/traces", project=PROJECT_NAME, mode="synthetic"
        )
        tracing.register_prompts(prompts)
        progress(f"Phoenix experiment: {publisher.state['url']}")
        progress(f"Phoenix traces: {publisher.state['traces_url']}")
        progress(
            "Each conversation is independently graded and published; runtime approval is not a quality score."
        )

    async def completed(run, scenario, state):
        judge.ceiling = max_cost_usd - reference_cost - state["accounted_usd"]
        paths = [run / f"cases/{scenario.id}/turn-{n}.json" for n in (1, 2)]
        for path in paths:
            if digest(path) != state["turn_hashes"].get(str(path.relative_to(run))):
                raise ValueError("Captured answer changed before evaluation")
        turns = [TurnRecord.model_validate(read_json(path)) for path in paths]
        progress(
            f"{scenario.id}: checking independent numbers, evidence, operations and trajectory"
        )
        with trace_context(run_id=run.name, case_id=scenario.id, phase=phase):
            grade = await grade_conversation(scenario, turns, snapshot, judge)
        grade["capture_sha256"] = {str(p.relative_to(run)): digest(p) for p in paths}
        write_json(run / "automatic" / f"{scenario.id}.json", grade)
        transcript = run / "cases" / scenario.id / "transcript.md"
        if transcript.exists():
            transcript.write_text(
                transcript.read_text().replace(
                    "Independent review: pending.",
                    f"Independent automatic evaluation: {grade['status']}. See automatic/{scenario.id}.json for findings.",
                )
            )
        write_json(run / "judge_calls.json", judge.calls)
        grades.append(grade)
        summary = final_summary(grades, len(scenarios))
        summary["accounted_total_usd"] = (
            state["accounted_usd"] + judge.accounted_usd + reference_cost
        )
        write_json(run / "summary.json", summary)
        if tracing is not None:
            await asyncio.to_thread(tracing.provider.force_flush, timeout_millis=1000)
        if publisher is not None:
            try:
                await asyncio.to_thread(publisher.record, scenario, turns, grade)
            except Exception as exc:
                write_json(
                    run / "publication-error.json",
                    {"case": scenario.id, "error_type": type(exc).__name__},
                )
                progress(
                    f"Phoenix publication failed for {scenario.id}; complete results remain in {run}."
                )
        progress(
            f"{scenario.id}: {grade['status']}; answers {[t['status'] for t in grade['turns']]}"
        )

    def factory(configured, identity, **kwargs):
        gateway = QueryGateway(
            identity.brands,
            project=configured.google_cloud_project,
            source_dataset=configured.warehouse_source_dataset,
            max_bytes=configured.max_query_bytes,
            clock=kwargs.get("clock"),
            snapshot_at=snapshot_at,
        )
        return app_factory(configured, identity, gateway=gateway, **kwargs)

    try:
        run = await run_manual(
            scenarios,
            settings,
            output_root=output_root,
            backend="bigquery",
            max_cost_usd=max_cost_usd,
            deadline_seconds=deadline_seconds,
            phase=phase,
            app_factory=factory,
            clock_utc=snapshot_at,
            progress=progress,
            on_started=started,
            on_case=completed,
            external_cost=lambda: judge.accounted_usd + reference_cost,
            absolute_deadline=deadline,
        )
    finally:
        if directory is not None:
            write_json(directory / "judge_calls.json", judge.calls)
        try:
            await judge.close()
        finally:
            if tracing is not None and not tracing.close() and directory is not None:
                write_json(
                    directory / "publication-error.json", {"error_type": "TraceExportFailed"}
                )
    summary = final_summary(grades, len(scenarios))
    summary["accounted_total_usd"] = (
        read_json(run / "progress.json")["accounted_usd"] + judge.accounted_usd + reference_cost
    )
    if (run / "publication-error.json").exists():
        summary["exit_code"] = 2
        summary["publication_status"] = "incomplete"
    else:
        summary["publication_status"] = "published"
    write_json(run / "summary.json", summary)
    lines = [
        "# Automatic conversation evaluation",
        "",
        f"Reference timestamp: {snapshot_at.isoformat()}",
        "",
        "| Scenario | Initial | Follow-up | Conversation |",
        "|---|---|---|---|",
    ]
    for grade in grades:
        values = [t["status"] for t in grade["turns"]]
        lines.append(f"| {grade['case_id']} | {values[0]} | {values[1]} | {grade['status']} |")
    lines += [
        "",
        f"Unresolved checks: {summary['unresolved_checks']}. Accounted total: ${summary['accounted_total_usd']:.4f}.",
        "",
        "Numerical comparisons are independent; extraction, grounding and trajectory judgments still require human calibration.",
    ]
    (run / "summary.md").write_text("\n".join(lines) + "\n")
    progress(f"Evaluation summary: {run / 'summary.md'}")
    return run, summary
