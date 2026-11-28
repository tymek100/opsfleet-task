"""Local LangGraph API with signed browser sessions and owned conversation history."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from retail_insight.config import Settings
from retail_insight.interfaces.gui_store import ConversationStore
from retail_insight.observability.tracing import configure_from_env
from retail_insight.runtime.card import agent_card
from retail_insight.runtime.team import AgentTeam

AGENTS = {
    "coordinator": ("Coordinator", "Connect sales, stock and distribution in one investigation."),
    "retail": ("Retail agent", "Explore revenue, products, customers and orders."),
    "inventory": ("Inventory agent", "Understand unsold stock, inventory age and cost."),
    "distribution": ("Distribution agent", "Compare distribution centers and stock allocation."),
}
COOKIE = "retail_assistant_session"
TASK_PATH = re.compile(r"tasks/([A-Za-z0-9_-]{1,128})(:cancel)?")


class TeamAPI(Protocol):
    async def ask(
        self,
        role,
        question,
        owner,
        context_id,
        /,
        *,
        max_cost_usd=None,
        deadline_seconds=None,
        progress=None,
    ) -> dict: ...
    def forget(self, role, owner, context_id, /) -> None: ...
    def close(self) -> None: ...


def create_app(
    settings: Settings | None = None,
    team: TeamAPI | None = None,
    *,
    data_dir: Path = Path(".artifacts/gui"),
    static_dir: Path = Path("web/dist"),
    profile: str = "default",
    backend: str = "fixture",
    port: int = 8080,
    session_key: str | None = None,
) -> Starlette:
    settings = settings or Settings.load()
    team = team or AgentTeam(settings)
    backend = settings.backend
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = data_dir / "session.key"
    if session_key is None:
        if not key_path.exists():
            fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as file:
                file.write(secrets.token_hex(32))
        session_key = key_path.read_text().strip()
    if len(session_key) < 32:
        raise ValueError("A strong workspace session key is required")

    def sign(owner):
        return hmac.new(session_key.encode(), owner.encode(), hashlib.sha256).hexdigest()

    active = set()
    store = ConversationStore(data_dir / "conversations.sqlite3")
    profile = f"{backend}:{profile}"
    allowed_hosts = {f"{host}:{port}" for host in ("localhost", "127.0.0.1", "[::1]")}

    @asynccontextmanager
    async def lifespan(app):
        tracing = configure_from_env()
        try:
            yield
        finally:
            team.close()
            store.db.close()
            if tracing:
                tracing.close()

    async def handle(request: Request) -> Response:
        host = request.headers.get("host", "").lower()
        if host not in allowed_hosts:
            return JSONResponse({"error": "Open the localhost GUI address."}, status_code=421)
        if request.headers.get("sec-fetch-site", "") not in {"", "none", "same-origin"} or (
            request.headers.get("origin") not in {None, f"http://{host}"}
        ):
            return JSONResponse(
                {"error": "Cross-origin requests are not allowed."}, status_code=403
            )
        cookie = request.cookies.get(COOKIE, "")
        owner, _, signature = cookie.partition(".")
        fresh = not re.fullmatch(r"[a-f0-9]{32}", owner) or not hmac.compare_digest(
            signature, sign(owner)
        )
        if fresh:
            owner = uuid.uuid4().hex
        try:
            response = await dispatch(request, owner)
        except (ValueError, KeyError, TypeError, AttributeError):
            response = JSONResponse({"error": "Invalid request."}, status_code=400)
        except httpx.HTTPError:
            response = JSONResponse(
                {"error": "The agent is unavailable. Check the stack and try again."},
                status_code=502,
            )
        if fresh:
            response.set_cookie(
                COOKIE,
                owner + "." + sign(owner),
                httponly=True,
                samesite="strict",
                max_age=31536000,
            )
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "same-origin"
        response.headers["cache-control"] = "no-store"
        response.headers["content-security-policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    async def body_json(request: Request, limit: int = 1_000_000) -> dict:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > limit:
                raise ValueError("Request too large")
        value = json.loads(body or b"{}")
        if not isinstance(value, dict):
            raise ValueError("Expected object")
        return value

    async def dispatch(request: Request, owner: str) -> Response:
        path, method = request.url.path, request.method
        if path == "/agent-card.json" and method == "GET":
            return JSONResponse(agent_card())
        if path == "/health" and method == "GET":
            return JSONResponse({"status": "ok", "ui": "assistant-ui", "profile": profile})
        if path == "/api/catalog" and method == "GET":
            return JSONResponse(
                {
                    "profile": profile,
                    "backend": backend,
                    "agents": [
                        {
                            "id": role,
                            "name": name,
                            "description": description,
                            "url": f"/api/agents/{role}",
                        }
                        for role, (name, description) in AGENTS.items()
                    ],
                }
            )
        if path == "/api/conversations":
            if method == "GET":
                return JSONResponse(store.list(owner, profile))
            if method == "POST":
                payload = await body_json(request)
                if payload.get("role") not in AGENTS:
                    raise ValueError("Unknown agent")
                return JSONResponse(store.create(owner, payload["role"], profile), status_code=201)
        if path.startswith("/api/conversations/"):
            identifier = path.removeprefix("/api/conversations/")
            if not store.owned(identifier, owner, profile):
                return JSONResponse({"error": "Conversation not found."}, status_code=404)
            if method == "GET":
                return JSONResponse(store.load(identifier))
            if method == "POST":
                store.append(identifier, await body_json(request))
                return JSONResponse({"saved": True})
            if method == "DELETE":
                if identifier in active:
                    return JSONResponse(
                        {"error": "Stop the running investigation before deleting it."},
                        status_code=409,
                    )
                role = next(c["role"] for c in store.list(owner, profile) if c["id"] == identifier)
                team.forget(role, owner, identifier)
                store.delete(identifier)
                return Response(status_code=204)
        if path.startswith("/api/agents/"):
            pieces = path.removeprefix("/api/agents/").split("/", 1)
            if len(pieces) != 2 or pieces[0] not in AGENTS:
                return Response(status_code=404)
            role, endpoint = pieces
            if endpoint == "agent-card.json" and method == "GET":
                return JSONResponse(agent_card(role))
            identifier = request.headers.get("x-retail-conversation", "")
            if not store.owned(identifier, owner, profile, role):
                return JSONResponse(
                    {"error": "Choose a conversation for this agent."}, status_code=403
                )
            if endpoint != "chat" or method != "POST":
                return Response(status_code=404)
            payload = await body_json(request, 100_000)
            question = payload.get("question")
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 6000:
                raise ValueError("Invalid question")
            if identifier in active:
                return JSONResponse(
                    {"error": "An investigation is already running in this conversation."},
                    status_code=409,
                )
            active.add(identifier)

            async def events():
                queue = asyncio.Queue(maxsize=256)

                def progress(event):
                    if not queue.full():
                        queue.put_nowait(
                            {"type": "progress", "event": event.get("event", "working")}
                        )

                task = asyncio.create_task(
                    team.ask(
                        role,
                        question,
                        owner,
                        identifier,
                        max_cost_usd=1.0,
                        deadline_seconds=180,
                        progress=progress,
                    )
                )
                try:
                    yield json.dumps({"type": "started", "context_id": identifier}) + "\n"
                    while not task.done():
                        try:
                            event = await asyncio.wait_for(queue.get(), timeout=1)
                        except TimeoutError:
                            event = {"type": "heartbeat"}
                        yield json.dumps(event) + "\n"
                    result = await task
                    public = {
                        k: result.get(k)
                        for k in (
                            "markdown",
                            "status",
                            "usage",
                            "context_id",
                            "trace_id",
                            "contains_ephemeral_evidence",
                        )
                    }
                    yield json.dumps({"type": "result", "result": public}) + "\n"
                except asyncio.CancelledError:
                    raise
                except Exception:
                    yield (
                        json.dumps(
                            {
                                "type": "error",
                                "message": "The investigation could not complete. No unreviewed answer was published.",
                            }
                        )
                        + "\n"
                    )
                finally:
                    if not task.done():
                        task.cancel()
                    active.discard(identifier)
                    await asyncio.gather(task, return_exceptions=True)

            return StreamingResponse(
                events(), media_type="application/x-ndjson", headers={"x-accel-buffering": "no"}
            )
        if method in {"GET", "HEAD"} and not path.startswith("/api/"):
            target = (static_dir / path.lstrip("/")).resolve()
            if not target.is_relative_to(static_dir.resolve()):
                return Response(status_code=404)
            if path == "/":
                target = static_dir / "index.html"
            if target.is_file():
                return FileResponse(target)
            return JSONResponse(
                {"error": "GUI assets not found. Build web/ or rebuild the stack."},
                status_code=503 if path == "/" else 404,
            )
        return Response(status_code=404)

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route(
                "/{path:path}", handle, methods=["GET", "HEAD", "POST", "DELETE", "PUT", "OPTIONS"]
            )
        ],
    )


def main() -> None:
    import uvicorn

    settings = Settings.load()
    app = create_app(
        settings,
        data_dir=settings.data_dir / "gui",
        static_dir=Path(os.getenv("GUI_STATIC_DIR", "web/dist")),
        profile=os.getenv("RETAIL_DATA_PROFILE", "default"),
        port=int(os.getenv("PORT", "8080")),
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")), access_log=False)


if __name__ == "__main__":
    main()
