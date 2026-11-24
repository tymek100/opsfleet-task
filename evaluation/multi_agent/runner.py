"""Run authored conversations through real A2A HTTP endpoints and publish every result."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import subprocess
import time
import uuid
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import httpx

from evaluation.graders.judge import GeminiJudge
from evaluation.reporting.phoenix import client_for
from evaluation.reporting.phoenix_service import ensure_phoenix
from evaluation.settings import EvaluationSettings
from retail_agent.config import Settings
from retail_agent.observability import configure_tracing

from .grading import grade
from .oracle import AS_OF, Snapshot, checksum, reference
from .publication import Publisher, ensure_dataset
from .scenarios import load_suites

HERE = Path(__file__).parent


def provenance():
    paths = [
        p
        for folder in (
            Path("src/retail_agent"),
            Path("src/retail_agents"),
            Path("knowledge/golden"),
            HERE,
        )
        for p in folder.rglob("*")
        if p.is_file() and p.suffix in {".py", ".md", ".json", ".sql"}
    ]
    paths += [
        p
        for p in (
            Path("uv.lock"),
            Path("infra/agents/catalog.json"),
            Path("infra/agents/compose.yaml"),
            Path("infra/agents/compose.evaluation.yaml"),
        )
        if p.is_file()
    ]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    images = {}
    for role in ("analyst", "inventory", "distribution", "coordinator"):
        tag = f"retail-{role}:{os.environ.get('RETAIL_STACK_REVISION', 'local')}"
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            images[tag] = result.stdout.strip() if result.returncode == 0 else "unavailable"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            images[tag] = "unavailable"
    return {"files": hashes, "images": images}


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
        async with self.lock:
            while self.used + self.reserved + amount > self.ceiling + 1e-9:
                if self.used + amount > self.ceiling + 1e-9 or time.monotonic() >= self.deadline:
                    return False
                try:
                    await asyncio.wait_for(
                        self.lock.wait(), min(30, self.deadline - time.monotonic())
                    )
                except TimeoutError:
                    if time.monotonic() >= self.deadline:
                        return False
            self.reserved += amount
            return True

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


def validate_deployment(health, backend, fixture_hashes):
    for role, value in health.items():
        if (
            value.get("role") != role
            or value.get("backend") != backend
            or value.get("status") != "ok"
        ):
            raise ValueError(f"{role} is not healthy on the requested {backend} backend")
        if (
            backend == "fixture"
            and role in fixture_hashes
            and value.get("fixture_sha256") != fixture_hashes[role]
        ):
            raise ValueError(
                f"{role} source differs from the independent evaluation fixture; start the stack with --evaluation-fixtures"
            )


async def preflight(urls, backend, fixture, snapshot):
    from .build_fixture import retail_sql

    expected = {}
    if backend == "fixture":
        expected = {
            "retail": hashlib.sha256(retail_sql(snapshot.raw).encode()).hexdigest(),
            "inventory": hashlib.sha256(Path(fixture).read_bytes()).hexdigest(),
            "distribution": hashlib.sha256(Path(fixture).read_bytes()).hexdigest(),
        }
    async with httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as http:

        async def get(role, url):
            response = await http.get(url.rstrip("/") + "/health")
            response.raise_for_status()
            return role, response.json()

        health = dict(await asyncio.gather(*(get(role, url) for role, url in urls.items())))
    validate_deployment(health, backend, expected)
    return health


async def run(
    *,
    suite="all",
    only=None,
    max_cost_usd=15.0,
    deadline_seconds=7200,
    backend="fixture",
    fixture=HERE / "fixture.json",
    phoenix_url="http://127.0.0.1:6006",
    urls=None,
    token=None,
    concurrency=3,
    as_of=AS_OF,
    publish_only=False,
    agent_budget_usd=2.0,
):
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
        phoenix_url=phoenix_url,
        judge_model=settings.gemini_model,
        input_usd_per_million=settings.input_usd_per_million,
        output_usd_per_million=settings.output_usd_per_million,
    )
    ensure_phoenix(config, deadline=deadline)
    phoenix = client_for(config, deadline=deadline)
    tracing = configure_tracing(
        phoenix_url + "/v1/traces",
        project="retail-multi-agent",
        mode="synthetic",
        service_name="multi-agent-evaluation",
    )
    suites = load_suites()
    if suite not in {*suites, "all", "smoke"}:
        raise ValueError(f"Unknown suite: {suite}")
    chosen = list(suites) if suite in {"all", "smoke"} else [suite]
    if backend == "fixture":
        snapshot = Snapshot.load(Path(fixture), as_of=as_of)
    elif backend == "bigquery":
        from .snapshot import capture

        snapshot = await asyncio.to_thread(capture, settings, as_of)
    else:
        raise ValueError("Backend must be fixture or bigquery")
    run_id = "a2a-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = Path(".artifacts/multi-agent") / run_id
    directory.mkdir(parents=True, exist_ok=False)
    save(directory / "snapshot.json", snapshot.raw)
    deployment = Path(".artifacts/agents/images.json")
    if deployment.is_file():
        save(directory / "deployment.json", json.loads(deployment.read_text()))
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
            data = ensure_dataset(phoenix, role, suites[role], snapshot)
            print(
                f"{role}: {phoenix_url}/datasets/{data.id} — {len(data.examples)} conversations",
                flush=True,
            )
        manifest["status"] = "datasets_published_without_execution"
        save(directory / "manifest.json", manifest)
        tracing.close()
        return directory, 0
    from retail_agents.client import AgentClient

    urls = urls or {
        "retail": "http://127.0.0.1:8001",
        "inventory": "http://127.0.0.1:8002",
        "distribution": "http://127.0.0.1:8003",
        "coordinator": "http://127.0.0.1:8004",
    }
    key_path = Path(".artifacts/agents/secrets/a2a_signing_key")
    signing_key = (
        token
        or os.environ.get("RETAIL_A2A_TOKEN")
        or (key_path.read_text().strip() if key_path.is_file() else "")
    )
    if not signing_key:
        raise ValueError("Start retail-stack first; its local A2A signing key is required")
    client = AgentClient(urls=urls, token=signing_key)
    try:
        deployment_health = await preflight(urls, backend, fixture, snapshot)
    except Exception:
        manifest["status"] = "preflight_failed"
        save(directory / "manifest.json", manifest)
        tracing.close()
        raise
    save(directory / "deployment-health.json", deployment_health)
    publishers = {role: Publisher(phoenix, role, suites[role], snapshot, run_id) for role in chosen}
    for role, publisher in publishers.items():
        print(f"{role} experiment: {publisher.url}", flush=True)
    print(
        f"Traces: {phoenix_url}/projects — retail-multi-agent\nArtifacts: {directory}", flush=True
    )
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
    manifest["planned_conversations"] = len(tasks)
    manifest["planned_turns"] = 2 * len(tasks)
    manifest["experiments"] = {role: p.url for role, p in publishers.items()}
    save(directory / "manifest.json", manifest)
    budget = RunBudget(max_cost_usd, deadline)
    budget.used = snapshot.capture_cost_usd
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
                grant = agent_budget_usd if role == "coordinator" else min(1.0, agent_budget_usd)
                if time.monotonic() < deadline and await budget.reserve(grant):
                    try:
                        raw = await client.ask(
                            role,
                            prompt,
                            identity=case["identity"],
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
                            "error": f"A2A request failed ({type(exc).__name__}); usage unknown, full grant retained.",
                        }
                    finally:
                        await budget.settle(grant, cost_of(raw))
                save(directory / role / case["id"] / f"turn-{number}.json", raw)
                turns.append(raw)
                allowance = min(0.65, max_cost_usd)
                if (
                    raw.get("markdown")
                    and time.monotonic() < deadline
                    and await budget.reserve(allowance)
                ):
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
            if (
                any(t.get("trace") or t.get("observations") for t in turns)
                and time.monotonic() < deadline
                and await budget.reserve(0.65)
            ):
                from .trajectory import evaluate

                judge = GeminiJudge(
                    settings.gemini_api_key.get_secret_value(),
                    config,
                    max_cost_usd=0.65,
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
                    await budget.settle(0.65, judge.accounted_usd)
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
        tracing.close()
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
