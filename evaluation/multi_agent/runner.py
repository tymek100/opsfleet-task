"""Run authored conversations through local LangGraph agents and publish every result."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
import uuid
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from evaluation.graders.judge import GeminiJudge
from evaluation.reporting.foundry import client_for, ensure_service
from evaluation.settings import MAX_EVALUATION_COST_USD, EvaluationSettings, validate_run_budget
from retail_insight.config import Settings
from retail_insight.observability.tracing import configure_tracing

from .grading import grade
from .oracle import AS_OF, Snapshot, checksum, reference
from .publication import Publisher, ensure_dataset
from .scenarios import load_suites

HERE = Path(__file__).parent


def provenance():
    paths = [
        p
        for folder in (
            Path("src/retail_insight"),
            HERE,
        )
        for p in folder.rglob("*")
        if p.is_file() and p.suffix in {".py", ".md", ".json", ".sql"}
    ]
    paths += [
        p
        for p in (
            Path("uv.lock"),
            Path("infra/workflow/compose.yaml"),
            Path("langgraph.json"),
        )
        if p.is_file()
    ]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    return {"files": hashes, "execution": "local-langgraph"}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


class RunBudget:
    """Reservations include concurrent requests and remain charged when usage is unknown."""

    def __init__(self, ceiling, deadline=float("inf")):
        self.ceiling = ceiling
        self.deadline = deadline
        self.used = 0.0
        self.reserved = 0.0
        self.lock = asyncio.Condition()

    async def reserve(self, amount):
        return bool(await self._reserve(amount, partial=False))

    async def reserve_up_to(self, maximum):
        """Use a smaller remaining allowance, waiting for other requests to settle first."""
        return await self._reserve(maximum, partial=True)

    async def _reserve(self, maximum, *, partial):
        async with self.lock:
            while time.monotonic() < self.deadline:
                remaining = max(0.0, self.ceiling - self.used)
                amount = min(maximum, remaining) if partial else maximum
                if amount <= 1e-9 or amount > remaining + 1e-9:
                    return 0.0
                if self.used + self.reserved + amount <= self.ceiling + 1e-9:
                    self.reserved += amount
                    return amount
                try:
                    await asyncio.wait_for(
                        self.lock.wait(), min(30, self.deadline - time.monotonic())
                    )
                except TimeoutError:
                    continue
            return 0.0

    async def settle(self, reserved, actual):
        async with self.lock:
            self.reserved -= reserved
            self.used += reserved if actual is None else max(0.0, actual)
            self.lock.notify_all()


def cost_of(raw):
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        return None
    for key in ("accounted_usd", "cost_usd", "estimated_cost_usd", "total_cost_usd"):
        value = usage.get(key)
        if isinstance(value, (float, int)) and math.isfinite(value) and value >= 0:
            return float(value)
    return None


async def run(
    *,
    suite="all",
    only=None,
    max_cost_usd=MAX_EVALUATION_COST_USD,
    deadline_seconds: float = 7200,
    backend="fixture",
    fixture=HERE / "fixture.json",
    concurrency=1,
    as_of=AS_OF,
    publish_only=False,
    agent_budget_usd=2.0,
):
    validate_run_budget(max_cost_usd)
    if not all(
        math.isfinite(value) and value > 0
        for value in (max_cost_usd, deadline_seconds, agent_budget_usd)
    ) or concurrency not in {1, 2, 3}:
        raise ValueError("Positive cost/time bounds and concurrency from 1 to 3 are required")
    started = time.monotonic()
    deadline = started + deadline_seconds
    settings = Settings.load()
    if not publish_only and not settings.gemini_api_key.get_secret_value():
        raise ValueError("GEMINI_API_KEY is required for independent evaluation judges")
    config = EvaluationSettings(
        judge_model=settings.gemini_model,
        input_usd_per_million=settings.input_usd_per_million,
        output_usd_per_million=settings.output_usd_per_million,
    )
    ensure_service(config, deadline=deadline)
    foundry = client_for(config, deadline=deadline)
    tracing = configure_tracing(project="retail-evaluation", mode="synthetic", )
    suites = load_suites()
    if suite not in {*suites, "all", "smoke"}:
        raise ValueError(f"Unknown suite: {suite}")
    chosen = list(suites) if suite in {"all", "smoke"} else [suite]
    selected = set(only.split(",")) if only else None
    valid_selectors = {c["id"] for cases in suites.values() for c in cases} | {
        f"{role}/{c['id']}" for role, cases in suites.items() for c in cases
    }
    if selected and selected - valid_selectors:
        raise ValueError("--only contains an unknown scenario ID")
    tasks = [
        (role, case)
        for role in chosen
        for case in suites[role]
        if (not selected or case["id"] in selected or f"{role}/{case['id']}" in selected)
        and (suite != "smoke" or case["id"] in {"scenario-01", "scenario-02"})
    ]
    if backend == "fixture":
        snapshot = Snapshot.load(Path(fixture), as_of=as_of)
    elif backend == "bigquery":
        from .snapshot import capture

        snapshot = await asyncio.to_thread(
            capture, settings, as_of, max_cost_usd=max_cost_usd, deadline=deadline
        )
    else:
        raise ValueError("Backend must be fixture or bigquery")
    run_id = (
        "langgraph-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    )
    directory = Path(".artifacts/multi-agent") / run_id
    directory.mkdir(parents=True, exist_ok=False)
    save(directory / "snapshot.json", snapshot.raw)
    frozen = {role: suites[role] for role in chosen}
    save(directory / "scenarios.json", frozen)
    references = {
        role: {
            case["id"]: {
                f"turn-{i}": reference(snapshot, case, i).model_dump(mode="json") for i in (1, 2)
            }
            for case in suites[role]
        }
        for role in chosen
    }
    save(directory / "references.json", references)
    manifest = {
        "id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "backend": backend,
        "model": settings.gemini_model,
        "versions": provenance(),
        "as_of": snapshot.as_of.isoformat(),
        "snapshot_at": snapshot.snapshot_at,
        "source_sha256": snapshot.sha256,
        "reference_capture_cost_usd": snapshot.capture_cost_usd,
        "accounted_usd": snapshot.capture_cost_usd,
        "reference_capture_billing": snapshot.capture_billing,
        "scenario_sha256": checksum(frozen),
        "reference_sha256": checksum(references),
        "human_reviewed": False,
        "judge_calibrated": False,
        "sealed_holdout": False,
        "max_cost_usd": max_cost_usd,
        "deadline_seconds": deadline_seconds,
        "status": "running",
        "cases": {},
    }
    save(directory / "manifest.json", manifest)
    if publish_only:
        for role in chosen:
            data = ensure_dataset(foundry, role, suites[role], snapshot)
            print(
                f"{role}: dataset {data.id} — {len(suites[role])} conversations",
                flush=True,
            )
        manifest["status"] = "datasets_published_without_execution"
        save(directory / "manifest.json", manifest)
        tracing.close()
        return directory, 0
    from retail_insight.runtime.team import AgentTeam

    from .build_fixture import retail_sql

    (directory / "retail_fixture.sql").write_text(retail_sql(snapshot.raw))
    local_settings = settings.model_copy(
        update={
            "backend": backend,
            "data_dir": directory / "contexts",
            "fixture_path": directory / "retail_fixture.sql",
            "domain_fixture_path": directory / "snapshot.json",
            "question_budget_usd": agent_budget_usd,
            "turn_timeout_seconds": 180,
        }
    )
    client = AgentTeam(local_settings, observation_mode="synthetic")
    publishers = {role: Publisher(foundry, role, suites[role], snapshot, run_id) for role in chosen}
    for role, publisher in publishers.items():
        print(f"{role} experiment: {publisher.url}", flush=True)
    print(
        f"Traces: https://ai.azure.com — retail-evaluation\nArtifacts: {directory}",
        flush=True,
    )
    manifest["planned_conversations"] = len(tasks)
    manifest["planned_turns"] = 2 * len(tasks)
    manifest["experiments"] = {role: p.url for role, p in publishers.items()}
    save(directory / "manifest.json", manifest)
    budget = RunBudget(max_cost_usd, deadline)
    budget.used = snapshot.capture_cost_usd
    print(
        f"Shared evaluation limit: ${max_cost_usd:g}; {deadline_seconds:g}s; "
        f"{concurrency} concurrent conversation(s). References, agents and judges share this limit.",
        flush=True,
    )
    semaphore = asyncio.Semaphore(concurrency)
    measured = Counter()

    async def conversation(role, case):
        async with semaphore:
            start_time = datetime.now(UTC)
            context = None
            turns, grades = [], []
            prior = []
            for number, prompt in enumerate((case["question"], case["follow_up"]), 1):
                label = f"{role}/{case['id']}/turn-{number}"
                print(f"{label}: running", flush=True)
                raw = {
                    "status": "NOT_EXECUTED",
                    "error": "Shared evaluation time or cost limit exhausted",
                }
                requested = (
                    agent_budget_usd if role == "coordinator" else min(1.0, agent_budget_usd)
                )
                grant = await budget.reserve_up_to(requested)
                if grant:
                    try:
                        raw = await client.ask(
                            role,
                            prompt,
                            owner=case["identity"],
                            context_id=context,
                            max_cost_usd=grant,
                            deadline_seconds=min(180, deadline - time.monotonic()),
                            as_of=snapshot.as_of.isoformat(),
                            snapshot_at=snapshot.snapshot_at,
                            backend=backend,
                        )
                        context = raw.get("context_id", context)
                    except Exception as exc:
                        raw = {
                            "status": "ERROR",
                            "error": f"Graph execution failed ({type(exc).__name__}); usage unknown, full grant retained.",
                        }
                    finally:
                        await budget.settle(grant, cost_of(raw))
                save(directory / role / case["id"] / f"turn-{number}.json", raw)
                turns.append(raw)
                allowance = await budget.reserve_up_to(0.65) if raw.get("markdown") else 0.0
                if allowance:
                    judge = GeminiJudge(
                        settings.gemini_api_key.get_secret_value(),
                        config,
                        max_cost_usd=allowance,
                        deadline_seconds=max(0.1, deadline - time.monotonic()),
                    )
                    try:
                        assessed = await grade(
                            raw, prompt, number, reference(snapshot, case, number), judge, prior
                        )
                    finally:
                        await budget.settle(allowance, judge.accounted_usd)
                        save(directory / role / case["id"] / f"judge-{number}.json", judge.calls)
                        with suppress(Exception):
                            await judge.close()
                else:
                    assessed = {
                        "step_id": f"turn-{number}",
                        "status": "ERROR",
                        "scores": [
                            {
                                "name": "execution_or_grading",
                                "status": "ERROR",
                                "finding": raw.get("error")
                                or "Independent judge could not run within the shared limit.",
                            }
                        ],
                        "judgment": None,
                    }
                grades.append(assessed)
                measured["numeric_correct"] += sum(
                    s["name"] == "numeric_fact" and s["status"] == "PASS"
                    for s in assessed["scores"]
                )
                for score in assessed["scores"]:
                    if score["name"] == "claim_support":
                        measured["supported_claims"] += score.get("numerator") or 0
                        measured["assessed_claims"] += score.get("denominator") or 0
                save(directory / role / case["id"] / f"grade-{number}.json", assessed)
                # Only prior published answer text is unconditionally visible in a conversation.
                prior.append({"question": prompt, "answer": raw.get("markdown")})
                print(f"{label}: {assessed['status']}; accounted ${budget.used:.3f}", flush=True)
            trajectory = {
                "status": "ERROR",
                "scores": [
                    {
                        "name": "trajectory",
                        "status": "ERROR",
                        "finding": "Trajectory judge did not run within the shared limit.",
                    }
                ],
            }
            trajectory_allowance = (
                await budget.reserve_up_to(0.65)
                if any(t.get("trace") or t.get("observations") for t in turns)
                else 0.0
            )
            if trajectory_allowance:
                from .trajectory import evaluate

                judge = GeminiJudge(
                    settings.gemini_api_key.get_secret_value(),
                    config,
                    max_cost_usd=trajectory_allowance,
                    deadline_seconds=max(0.1, deadline - time.monotonic()),
                )
                try:
                    trajectory = await evaluate(role, case, turns, judge)
                except Exception as exc:
                    trajectory = {
                        "status": "ERROR",
                        "scores": [
                            {
                                "name": "trajectory",
                                "status": "ERROR",
                                "finding": f"Trajectory evaluation failed ({type(exc).__name__}); no pass assumed.",
                            }
                        ],
                    }
                finally:
                    await budget.settle(trajectory_allowance, judge.accounted_usd)
                    save(directory / role / case["id"] / "trajectory-judge.json", judge.calls)
                    with suppress(Exception):
                        await judge.close()
            save(directory / role / case["id"] / "trajectory.json", trajectory)
            try:
                publishers[role].record(
                    case, turns, grades, start_time, datetime.now(UTC), trajectory=trajectory
                )
                publication = "published"
            except Exception as exc:
                publication = f"ERROR: {type(exc).__name__}"
            manifest["cases"][f"{role}/{case['id']}"] = {
                "turns": [g["status"] for g in grades],
                "trajectory": trajectory["status"],
                "publication": publication,
            }
            manifest["accounted_usd"] = budget.used
            save(directory / "manifest.json", manifest)

    try:
        await asyncio.gather(*(conversation(role, case) for role, case in tasks))
    finally:
        client.close()
        tracing.close()
    for role, publisher in publishers.items():
        try:
            state = await asyncio.to_thread(publisher.finalize)
            save(directory / role / "foundry.json", state)
            if state.get("status", "published") != "published":
                for key, record in manifest["cases"].items():
                    if key.startswith(role + "/"):
                        record["publication"] = state["status"]
            print(f"{role}: Foundry evaluation results: {state['url']}", flush=True)
        except Exception as exc:
            for key, record in manifest["cases"].items():
                if key.startswith(role + "/"):
                    record["publication"] = f"ERROR: {type(exc).__name__}"
    foundry.close()
    counts = Counter(status for record in manifest["cases"].values() for status in record["turns"])
    manifest.update(
        status="completed",
        ended_at=datetime.now(UTC).isoformat(),
        elapsed_seconds=time.monotonic() - started,
        accounted_usd=budget.used,
        turn_counts=dict(counts),
        metrics={
            "answer_success": {"numerator": counts.get("PASS", 0), "denominator": 2 * len(tasks)},
            "numeric_fact_accuracy": {
                "numerator": measured["numeric_correct"],
                "denominator": sum(
                    len(reference(snapshot, case, i).facts) for _, case in tasks for i in (1, 2)
                ),
            },
            "supported_claim_rate": {
                "numerator": measured["supported_claims"],
                "denominator": measured["assessed_claims"],
                "qualification": "Among extracted factual claims; unavailable/invalid judges remain ERROR in answer_success and are not evidence of hallucination absence.",
            },
        },
    )
    save(directory / "manifest.json", manifest)
    failed = (
        budget.used > max_cost_usd + 1e-9
        or any(k != "PASS" and v for k, v in counts.items())
        or any(
            c["publication"] != "published" or c["trajectory"] not in {"PASS", "NOT_APPLICABLE"}
            for c in manifest["cases"].values()
        )
    )
    print(f"{run_id}: {dict(counts)}; cost ${budget.used:.3f}; results {directory}", flush=True)
    return directory, 2 if failed else 0
