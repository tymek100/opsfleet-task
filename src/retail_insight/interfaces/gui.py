"""Loopback-only Inspector gateway with automatic Alice demo authentication."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}
INSPECTOR_COOKIE = "__Host-a2a_inspector_session"


def connection_payload(payload: dict, catalog: dict, token: str) -> dict:
    """Attach credentials only to an approved endpoint; never trust a submitted card."""
    interface = payload.get("interface") or {}
    card_url = payload.get("cardUrl")
    target = next(
        (
            item
            for item in catalog.values()
            if (card_url == item["card_url"] if card_url else interface.get("url") == item["url"])
        ),
        None,
    )
    if target is None or (interface and interface.get("url") != target["url"]):
        raise ValueError("Choose an agent from the local Retail Insight catalog.")
    # Refetch the real card. Browser-supplied cards/interfaces must not redirect credentials.
    result = {key: payload[key] for key in ("contextId", "openTask", "replaces") if key in payload}
    result.update({"cardUrl": target["card_url"], "auth": {"bearer": {"value": token}}})
    return result


def create_app(
    catalog: dict,
    token: str,
    upstream: str = "http://inspector:8080",
    port: int = 8080,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Starlette:
    if not token.strip():
        raise ValueError("The local demo credential is missing.")
    allowed_hosts = {
        f"{host}:{p}" for host in ("localhost", "127.0.0.1", "[::1]") for p in (port, 8080)
    }
    local_cookie = f"retail_gui_session_{port}"

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(30, read=None),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            app.state.client = client
            yield

    async def proxy(request: Request) -> Response:
        host = request.headers.get("host", "").lower()
        if host not in allowed_hosts:
            return JSONResponse({"error": "Use the localhost GUI address."}, status_code=421)
        if request.headers.get("sec-fetch-site", "") not in {"", "none", "same-origin"}:
            return JSONResponse(
                {"error": "Cross-origin requests are not allowed."}, status_code=403
            )
        origin = request.headers.get("origin")
        if origin and origin != f"http://{host}":
            return JSONResponse(
                {"error": "Cross-origin requests are not allowed."}, status_code=403
            )

        path = request.url.path
        if path == "/health":
            try:
                response = await request.app.state.client.get(upstream + "/", timeout=3)
                response.raise_for_status()
            except httpx.HTTPError:
                return JSONResponse({"status": "unavailable"}, status_code=503)
            return JSONResponse({"status": "ok", "identity": "alice", "scope": "Calvin Klein"})

        body = await request.body()
        if path == "/api/connections" and request.method == "POST":
            try:
                payload = connection_payload(json.loads(body), catalog, token)
            except (ValueError, TypeError, AttributeError):
                return JSONResponse(
                    {"error": "Choose an agent from the local Retail Insight catalog."},
                    status_code=400,
                )
            body = json.dumps(payload).encode()

        # Keep each browser's cookie separate; do not use the shared client's cookie jar.
        headers = {key: value for key, value in request.headers.items() if key not in HOP_HEADERS}
        cookies = SimpleCookie(request.headers.get("cookie", ""))
        headers.pop("cookie", None)
        if local_cookie in cookies:
            headers["cookie"] = f"{INSPECTOR_COOKIE}={cookies[local_cookie].value}"
        headers["accept-encoding"] = "identity"
        session_headers = []
        if path == "/" and request.method == "GET":
            # Establish or renew the session before React starts concurrent API requests.
            try:
                bootstrap = await request.app.state.client.send(
                    httpx.Request("GET", upstream + "/api/config", headers=headers)
                )
            except httpx.HTTPError:
                return JSONResponse(
                    {"error": "Inspector is starting. Refresh in a moment."}, status_code=502
                )
            session_headers = [
                ("set-cookie", value) for value in bootstrap.headers.get_list("set-cookie")
            ]
        url = upstream + path
        if request.url.query:
            url += "?" + request.url.query
        outgoing = httpx.Request(request.method, url, headers=headers, content=body)
        try:
            response = await request.app.state.client.send(outgoing, stream=True)
        except httpx.HTTPError:
            return JSONResponse(
                {"error": "Inspector is starting. Refresh in a moment."}, status_code=502
            )
        response_headers = session_headers + [
            (key, value)
            for key, value in response.headers.multi_items()
            if key.lower() not in HOP_HEADERS
        ]
        # Local HTTP needs a non-__Host name together with the removal of Secure.
        # Keep HttpOnly and SameSite=Strict; translate back only on the internal hop.
        response_headers = [
            (
                key,
                value.replace(INSPECTOR_COOKIE + "=", local_cookie + "=", 1).replace(
                    "; Secure", ""
                ),
            )
            if key.lower() == "set-cookie"
            else (key, value)
            for key, value in response_headers
        ]
        if path == "/api/config" and request.method == "GET" and response.status_code == 200:
            await response.aread()
            config = response.json()
            config["agentCardUrl"] = catalog["coordinator"]["card_url"]
            result = JSONResponse(config)
            await response.aclose()
        else:
            result = StreamingResponse(
                response.aiter_raw(),
                status_code=response.status_code,
                background=BackgroundTask(response.aclose),
            )
        result.raw_headers = [
            (key.encode("latin-1"), value.encode("latin-1")) for key, value in response_headers
        ]
        return result

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route(
                "/{path:path}",
                proxy,
                methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            )
        ],
    )


def main() -> None:
    import uvicorn

    catalog = json.loads(Path(os.environ["A2A_CATALOG_PATH"]).read_text())
    token = Path(os.environ["A2A_DEMO_TOKEN_FILE"]).read_text().strip()
    app = create_app(catalog, token, port=int(os.environ.get("GUI_PUBLIC_PORT", "8080")))
    uvicorn.run(app, host="0.0.0.0", port=8080, access_log=False)


if __name__ == "__main__":
    main()
