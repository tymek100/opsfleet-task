"""Local assistant-ui gateway: static assets, owned history and allowlisted A2A REST."""

from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from retail_insight.a2a.client import AgentClient
from retail_insight.interfaces.gui_store import ConversationStore

AGENTS = {
    "coordinator": ("Coordinator", "Connect sales, stock and distribution in one investigation."),
    "retail": ("Retail agent", "Explore revenue, products, customers and orders."),
    "inventory": ("Inventory agent", "Understand unsold stock, inventory age and cost."),
    "distribution": ("Distribution agent", "Compare distribution centers and stock allocation."),
}
COOKIE = "retail_assistant_session"
TASK_PATH = re.compile(r"tasks/([A-Za-z0-9_-]{1,128})(:cancel)?")


def create_app(
    catalog: dict,
    token: str,
    *,
    data_dir: Path = Path(".artifacts/gui"),
    static_dir: Path = Path("web/dist"),
    profile: str = "default",
    backend: str = "fixture",
    port: int = 8080,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Starlette:
    if not token.strip() or set(catalog) != set(AGENTS):
        raise ValueError("A workspace credential and the four-agent catalog are required")
    urls = {role: item["url"].rstrip("/") for role, item in catalog.items()}
    AgentClient(urls, token, signed=False)  # Apply the same fixed-target validation as CLI callers.
    store = ConversationStore(data_dir / "conversations.sqlite3")
    profile = f"{backend}:{profile}"
    allowed_hosts = {f"{host}:{port}" for host in ("localhost", "127.0.0.1", "[::1]")}

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(10, read=300),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            app.state.client = client
            yield
        store.db.close()

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
        owner = request.cookies.get(COOKIE, "")
        fresh = not re.fullmatch(r"[a-f0-9]{32}", owner)
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
            response.set_cookie(COOKIE, owner, httponly=True, samesite="strict", max_age=31536000)
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
                store.delete(identifier)
                return Response(status_code=204)
        if path.startswith("/api/agents/"):
            pieces = path.removeprefix("/api/agents/").split("/", 1)
            if len(pieces) != 2 or pieces[0] not in AGENTS:
                return Response(status_code=404)
            role, endpoint = pieces
            client = request.app.state.client
            headers = {
                "authorization": f"Bearer {token}",
                "a2a-version": "1.0",
                "accept-encoding": "identity",
            }
            if endpoint == ".well-known/agent-card.json" and method == "GET":
                result = await client.get(urls[role] + "/" + endpoint, headers=headers)
                result.raise_for_status()
                card = result.json()
                card["supportedInterfaces"] = [
                    {
                        "url": f"http://{request.headers['host']}/api/agents/{role}",
                        "protocolBinding": "HTTP+JSON",
                        "protocolVersion": "1.0",
                    }
                ]
                # This is a local gateway view; upstream signatures would no longer describe it.
                for field in ("securitySchemes", "securityRequirements", "signatures"):
                    card.pop(field, None)
                return JSONResponse(card)
            identifier = request.headers.get("x-retail-conversation", "")
            if not store.owned(identifier, owner, profile, role):
                return JSONResponse(
                    {"error": "Choose a conversation for this agent."}, status_code=403
                )
            payload = None
            if endpoint in {"message:send", "message:stream"} and method == "POST":
                payload = await body_json(request, 100_000)
                message = payload.get("message", {})
                if message.get("contextId") not in {None, identifier} or message.get("taskId"):
                    raise ValueError("Conversation mismatch")
                message["contextId"] = identifier
                # Browser requests cannot create service handoffs or expand runtime limits.
                payload = {
                    "message": message,
                    "configuration": payload.get("configuration", {}),
                    "metadata": {"max_cost_usd": 1.0, "deadline_seconds": 180},
                }
            else:
                match = TASK_PATH.fullmatch(endpoint)
                if not match or method != ("POST" if match[2] else "GET"):
                    return Response(status_code=404)
                task = await client.get(urls[role] + "/tasks/" + match[1], headers=headers)
                if task.status_code != 200 or task.json().get("contextId") != identifier:
                    return JSONResponse(
                        {"error": "Task not found in this conversation."}, status_code=404
                    )
                if method == "GET":
                    return JSONResponse(task.json())
                payload = {}
            upstream = await client.send(
                client.build_request(
                    method, urls[role] + "/" + endpoint, json=payload, headers=headers
                ),
                stream=True,
            )
            if upstream.status_code >= 400:
                await upstream.aclose()
                return JSONResponse(
                    {"error": "The agent could not accept this request."}, status_code=502
                )
            return StreamingResponse(
                upstream.aiter_bytes(),
                status_code=upstream.status_code,
                headers={
                    "content-type": upstream.headers.get("content-type", "application/json"),
                    "x-accel-buffering": "no",
                },
                background=BackgroundTask(upstream.aclose),
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

    catalog = json.loads(Path(os.environ["A2A_CATALOG_PATH"]).read_text())
    token = Path(os.environ["A2A_ACCESS_TOKEN_FILE"]).read_text().strip()
    app = create_app(
        catalog,
        token,
        data_dir=Path(os.getenv("GUI_DATA_DIR", "/data/gui")),
        static_dir=Path(os.getenv("GUI_STATIC_DIR", "/app/web/dist")),
        backend=os.getenv("BACKEND", "fixture"),
        profile=os.getenv("RETAIL_DATA_PROFILE", "default"),
        port=int(os.getenv("GUI_PUBLIC_PORT", "8080")),
    )
    uvicorn.run(app, host="0.0.0.0", port=8080, access_log=False)


if __name__ == "__main__":
    main()
