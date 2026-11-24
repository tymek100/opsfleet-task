"""A2A adapter around complete reviewed runtimes, not raw LLM agents."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from a2a.server.agent_execution import AgentExecutor
from a2a.server.apps import A2AStarletteApplication
from a2a.server.apps.jsonrpc.jsonrpc_app import CallContextBuilder
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    DataPart,
    HTTPAuthSecurityScheme,
    Part,
    SecurityScheme,
    TaskState,
    TextPart,
)
from a2a.utils import new_agent_text_message
from opentelemetry import context as otel_context
from opentelemetry.propagate import extract
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from retail_agent.config import Settings
from retail_agent.contracts import DEMO_USERS, Answer
from retail_agent.observability import configure_tracing
from retail_agent.services.warehouse import QueryGateway
from retail_agents.auth import authenticate
from retail_agents.client import AgentClient
from retail_agents.ephemeral import contains_maps, persistent_result
from retail_agents.runtime import RoleAnalyst
from retail_agents.store import Store

ROLES = {
    "retail": "Scoped sales, products, customers, revenue and order analysis",
    "inventory": "Modeled unsold inventory, aging and inventory cost analysis",
    "distribution": "Distribution centers, scoped stock attribution and Google Maps context",
    "coordinator": "Cross-domain retail analysis through autonomous specialist delegation",
}


def profile_directory(base: Path, backend: str, profile: str) -> Path:
    """Keep fixture, live warehouse and changed source corpora out of each other's memory."""
    if backend not in {"fixture", "bigquery"} or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", profile):
        raise ValueError("Invalid data profile")
    return base / backend / profile


def timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps require an explicit time zone")
    return parsed.astimezone(UTC)


class ContextBuilder(CallContextBuilder):
    def build(self, request: Request) -> ServerCallContext:
        return ServerCallContext(
            state={
                "principal": request.scope["principal"],
                "received_at": request.scope["received_at"],
            }
        )


class Authentication:
    def __init__(self, app, secret: str, demo_token: str, role: str):
        self.app, self.secret, self.demo_token, self.role = app, secret, demo_token, role

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in {
            "/health",
            "/.well-known/agent-card.json",
            "/.well-known/agent.json",
        }:
            return await self.app(scope, receive, send)
        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > 100_000:
                return await JSONResponse({"error": "Request too large"}, status_code=413)(
                    scope, receive, send
                )
            if not message.get("more_body"):
                break
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        try:
            principal = authenticate(headers, body, self.secret, self.demo_token, self.role)
        except ValueError:
            return await JSONResponse({"error": "Authentication required"}, status_code=401)(
                scope, receive, send
            )
        scope["principal"] = principal
        scope["received_at"] = time.monotonic()
        # Stable initial context makes a repeated messageId replay-safe even when
        # the caller has not yet received the generated conversation identifier.
        try:
            envelope = json.loads(body)
            if envelope.get("method") in {"message/send", "message/stream"}:
                incoming = envelope.get("params", {}).get("message", {})
                if incoming.get("messageId") and not incoming.get("contextId"):
                    incoming["contextId"] = uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"retail:{self.role}:{principal.identity}:{incoming['messageId']}",
                    ).hex
                    body = json.dumps(envelope).encode()
        except (ValueError, TypeError, AttributeError):
            pass  # The SDK returns the protocol validation error.
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        token = otel_context.attach(extract(headers))
        try:
            await self.app(scope, replay, send)
        finally:
            otel_context.detach(token)


class Executor(AgentExecutor):
    def __init__(self, role, settings, store, client):
        self.role, self.settings, self.store, self.client = role, settings, store, client
        self.locks = {}
        self.running = {}
        self.slots = asyncio.Semaphore(4)

    def create_runtime(self, identity, context_id, request_id, metadata, state):
        if metadata.get("backend") not in {None, self.settings.backend}:
            raise ValueError("Requested backend does not match the running service")
        as_of = timestamp(metadata.get("as_of") or state.get("as_of")) or datetime.now(UTC)
        snapshot = timestamp(metadata.get("snapshot_at") or state.get("snapshot_at"))
        if state and (
            state.get("as_of") != as_of.isoformat()
            or state.get("snapshot_at") != (snapshot.isoformat() if snapshot else None)
        ):
            raise ValueError(
                "Start a new conversation to change its business cutoff or warehouse snapshot"
            )
        seconds = min(
            float(metadata.get("deadline_seconds", self.settings.turn_timeout_seconds)),
            self.settings.turn_timeout_seconds,
        )
        allowance = min(
            float(metadata.get("max_cost_usd", self.settings.question_budget_usd)),
            self.settings.question_budget_usd,
        )
        settings = Settings.model_validate(
            {
                **self.settings.model_dump(),
                "turn_timeout_seconds": seconds,
                "question_budget_usd": allowance,
                "review_reserve_seconds": min(30, seconds / 4),
            }
        )

        def clock():
            return as_of

        gateway = None
        if self.role in {"inventory", "distribution"}:
            from retail_agents.domains.warehouse import DomainGateway

            gateway = DomainGateway(
                role=self.role,
                brands=identity.brands,
                project=settings.google_cloud_project,
                backend=settings.backend,
                fixture_path=Path(os.environ["DOMAIN_FIXTURE_PATH"])
                if os.getenv("DOMAIN_FIXTURE_PATH")
                else None,
                max_bytes=settings.max_query_bytes,
                source_dataset=settings.warehouse_source_dataset,
                clock=clock,
                snapshot_at=snapshot,
            )
        elif self.role == "retail":
            gateway = QueryGateway(
                brands=identity.brands,
                project=settings.google_cloud_project,
                backend=settings.backend,
                fixture_path=settings.fixture_path,
                max_bytes=settings.max_query_bytes,
                source_dataset=settings.warehouse_source_dataset,
                clock=clock,
                snapshot_at=snapshot,
            )
        else:
            # Coordinator tools do not expose this placeholder gateway or warehouse credentials.
            gateway = object()
        app = RoleAnalyst(
            self.role,
            settings,
            identity,
            gateway=gateway,
            client=self.client,
            as_of=as_of.isoformat(),
            snapshot_at=snapshot.isoformat() if snapshot else None,
            persist_budget=lambda value: self.store.budget(request_id, value),
            observation_mode=os.getenv("TRACE_CONTENT_MODE", "metadata"),
        )
        app.conversation_id = context_id
        app.observations = []
        app.observer = app.observations.append
        app.history = state.get("history", [])
        app.results = state.get("results", {})
        app.answers = {key: Answer(**value) for key, value in state.get("answers", {}).items()}
        app.children = state.get("children", {})
        app._result_counter = state.get("result_counter", 0)
        if self.role == "distribution":
            from retail_agents.domains.maps import MapsClient

            app.maps = MapsClient()
        return app

    async def execute(self, context, event_queue):
        call_context, message = context.call_context, context.message
        context_id, task_id = context.context_id, context.task_id
        if call_context is None or message is None or context_id is None or task_id is None:
            raise ValueError("An authenticated message, task and conversation are required")
        owner = call_context.state["principal"].identity
        updater = TaskUpdater(event_queue, task_id, context_id)
        request_id = message.message_id
        question = context.get_user_input()
        digest = hashlib.sha256(
            json.dumps([question, context.metadata, message.context_id], sort_keys=True).encode()
        ).hexdigest()
        self.running[task_id] = asyncio.current_task()
        try:
            async with self.slots, self.locks.setdefault(context_id, asyncio.Lock()):
                state = self.store.context(context_id, owner)
                cached = self.store.claim(request_id, owner, digest)
                if cached is not None:
                    await self.publish(updater, cached)
                    return
                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message(f"{self.role.title()} is investigating."),
                )
                metadata = dict(context.metadata)
                requested_seconds = float(
                    metadata.get("deadline_seconds", self.settings.turn_timeout_seconds)
                )
                metadata["deadline_seconds"] = min(
                    requested_seconds, self.settings.turn_timeout_seconds
                ) - (time.monotonic() - call_context.state["received_at"])
                app = self.create_runtime(
                    DEMO_USERS[owner], context_id, request_id, metadata, state
                )
                try:
                    result = await app.ask(question)
                finally:
                    reports = getattr(app, "reports", None)
                    if reports is not None:
                        reports.close()
                    if self.role == "distribution":
                        close = getattr(app.maps, "close", None)
                        if close:
                            await close()
                candidate_ids: list[str] = list(result.answer.evidence_ids) if result.answer else []
                candidate_ids.extend(item["id"] for item in result.evidence)
                evidence_ids = list(dict.fromkeys(candidate_ids))
                output = {
                    "schema_version": "retail-agent-result-v1",
                    "role": self.role,
                    "status": result.status,
                    "markdown": result.answer.markdown if result.answer else result.message,
                    "outcome": result.answer.outcome if result.answer else "incomplete",
                    "evidence": [app.results[key] for key in evidence_ids],
                    "usage": result.usage,
                    "trace": result.trace,
                    "observations": app.observations if app.observation_mode == "synthetic" else [],
                    "trace_id": app._trace_ids.get("trace_id"),
                    "scope": app.identity.scope,
                    "as_of": app.as_of,
                    "snapshot_at": app.snapshot_at,
                    "elapsed_seconds": result.elapsed_seconds,
                    "receipts": result.answer.receipts if result.answer else [],
                    "contains_ephemeral_evidence": contains_maps(app.results),
                }
                self.store.save_context(
                    context_id,
                    owner,
                    state
                    if contains_maps(output)
                    else {
                        "history": app.history,
                        "results": app.results,
                        "answers": {key: asdict(value) for key, value in app.answers.items()},
                        "children": app.children,
                        "result_counter": app._result_counter,
                        "as_of": app.as_of,
                        "snapshot_at": app.snapshot_at,
                    },
                )
                self.store.finish(request_id, persistent_result(output))
                await self.publish(updater, output)
        except asyncio.CancelledError:
            await updater.update_status(
                TaskState.canceled,
                new_agent_text_message("Task canceled; incomplete work was not published."),
                final=True,
            )
        except Exception as exc:
            # Never expose provider errors, credentials or unreviewed model text.
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Task could not complete ({type(exc).__name__})."),
                final=True,
            )
        finally:
            self.running.pop(task_id, None)

    @staticmethod
    async def publish(updater, result):
        await updater.add_artifact(
            [Part(root=DataPart(data=result))], name="Scoped evidence and usage"
        )
        await updater.add_artifact(
            [Part(root=TextPart(text=result["markdown"]))], name="Reviewed answer"
        )
        if result["status"] == "approved":
            await updater.complete()
        else:
            await updater.update_status(
                TaskState.failed, new_agent_text_message(result["markdown"]), final=True
            )

    async def cancel(self, context, event_queue):
        task_id, context_id = context.task_id, context.context_id
        if task_id is None or context_id is None:
            raise ValueError("Cancellation requires an existing task and conversation")
        running = self.running.get(task_id)
        if running:
            running.cancel()
            return
        updater = TaskUpdater(event_queue, task_id, context_id)
        await updater.update_status(TaskState.canceled, final=True)


def create_app(
    role: str,
    settings: Settings,
    *,
    secret: str,
    demo_token: str,
    public_url: str,
    urls: dict | None = None,
):
    if role not in ROLES or len(secret) < 32:
        raise ValueError("A known role and a strong signing key are required")
    card = AgentCard(
        name=f"Retail Insight — {role.title()}",
        description=ROLES[role],
        url=public_url,
        version="0.1.0",
        protocol_version="0.3.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/markdown", "application/json"],
        skills=[
            AgentSkill(id=role, name=role.title(), description=ROLES[role], tags=["retail", role])
        ],
        security_schemes={
            "demoBearer": SecurityScheme(
                root=HTTPAuthSecurityScheme(scheme="bearer", bearer_format="local-demo-token")
            )
        },
        security=[{"demoBearer": []}],
    )
    store = Store(settings.data_dir / "a2a.sqlite3")
    client = AgentClient(urls or {r: f"http://{r}:8000" for r in ROLES}, secret)
    executor = Executor(role, settings, store, client)
    handler = DefaultRequestHandler(executor, store)
    app = A2AStarletteApplication(
        card, handler, context_builder=ContextBuilder(), max_content_length=100_000
    ).build()

    async def health(request):
        fixture_hash = None
        if settings.backend == "fixture" and role != "coordinator":
            from retail_agents.domains.warehouse import DEFAULT_FIXTURE

            fixture = (
                settings.fixture_path
                if role == "retail"
                else Path(os.getenv("DOMAIN_FIXTURE_PATH", str(DEFAULT_FIXTURE)))
            )
            fixture_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
        return JSONResponse(
            {
                "status": "ok",
                "role": role,
                "backend": settings.backend,
                "fixture_sha256": fixture_hash,
                "maps_configured": bool(os.getenv("GOOGLE_MAPS_API_KEY"))
                if role == "distribution"
                else False,
            }
        )

    app.routes.append(Route("/health", health))
    return Authentication(app, secret, demo_token, role)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = Settings.load()
    settings = Settings.model_validate(
        {
            **settings.model_dump(),
            "data_dir": profile_directory(
                Path(os.getenv("DATA_DIR", "/data")),
                settings.backend,
                os.getenv("RETAIL_DATA_PROFILE", "default"),
            ),
            "turn_timeout_seconds": float(os.getenv("TURN_TIMEOUT_SECONDS", "240")),
            "question_budget_usd": float(os.getenv("QUESTION_BUDGET_USD", "2")),
            "golden_bootstrap": os.getenv("GOLDEN_BOOTSTRAP", "true").lower() == "true",
        }
    )
    secret = Path(os.environ["A2A_SIGNING_KEY_FILE"]).read_text().strip()
    demo = Path(os.environ["A2A_DEMO_TOKEN_FILE"]).read_text().strip()
    catalog = json.loads(Path(os.environ["A2A_CATALOG_PATH"]).read_text())
    urls = {role: item["url"] for role, item in catalog.items()}
    tracing = None
    if endpoint := os.getenv("PHOENIX_COLLECTOR_ENDPOINT"):
        capture_mode = os.getenv("TRACE_CONTENT_MODE", "metadata")
        if capture_mode not in ("metadata", "synthetic"):
            raise ValueError("Capture mode must be metadata or synthetic")
        tracing = configure_tracing(
            endpoint,
            project="retail-multi-agent",
            mode=capture_mode,
            allowed_hosts=frozenset({"phoenix"}),
            service_name=f"retail-{args.role}",
        )
    try:
        uvicorn.run(
            create_app(
                args.role,
                settings,
                secret=secret,
                demo_token=demo,
                public_url=os.getenv("A2A_PUBLIC_URL", f"http://{args.role}:8000"),
                urls=urls,
            ),
            host="0.0.0.0",
            port=args.port,
            access_log=False,
        )
    finally:
        if tracing:
            tracing.close()


if __name__ == "__main__":
    main()
