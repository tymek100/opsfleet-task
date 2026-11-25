"""Browser gateway contracts without model calls or credentials in browser responses."""

import json
import sqlite3

import httpx
from starlette.testclient import TestClient

from retail_insight.interfaces.gui import AGENTS, create_app

CATALOG = {role: {"url": f"http://{role}:8000"} for role in AGENTS}
TOKEN = "server-only-workspace-token"


def make_app(tmp_path, handler=None, **kwargs):
    return create_app(
        CATALOG,
        TOKEN,
        data_dir=tmp_path,
        transport=httpx.MockTransport(handler or (lambda request: httpx.Response(200, json={}))),
        **kwargs,
    )


def test_catalog_history_and_browser_agent_isolation(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://localhost:8080") as browser:
        catalog = browser.get("/api/catalog")
        assert len(catalog.json()["agents"]) == 4
        assert TOKEN not in catalog.text
        cookie = browser.cookies.get("retail_assistant_session")
        conversation = browser.post("/api/conversations", json={"role": "inventory"}).json()
        path = "/api/conversations/" + conversation["id"]
        entry = {
            "parentId": None,
            "message": {
                "id": "u1",
                "role": "user",
                "content": [{"type": "text", "text": "Count stock"}],
            },
        }
        assert browser.post(path, json=entry).status_code == 200
        assert browser.get(path).json()["messages"][0] == entry
        assert browser.get("/api/conversations").json()[0]["title"] == "Count stock"
        assert (
            browser.post(
                "/api/agents/retail/message:stream",
                json={},
                headers={"x-retail-conversation": conversation["id"]},
            ).status_code
            == 403
        )
        browser.cookies.clear()
        assert browser.get(path).status_code == 404
        assert browser.get("/api/conversations").json() == []
        browser.cookies.set("retail_assistant_session", cookie)
        assert browser.get(path).status_code == 200
    # The same browser must not load history against a different warehouse profile.
    with TestClient(
        make_app(tmp_path, profile="different"), base_url="http://localhost:8080"
    ) as browser:
        browser.cookies.set("retail_assistant_session", cookie)
        assert browser.get(path).status_code == 404
        assert browser.delete(path).status_code == 404


def test_delete_history_checks_ownership_and_removes_only_selected_chat(tmp_path):
    with TestClient(make_app(tmp_path), base_url="http://localhost:8080") as browser:
        deleted = browser.post("/api/conversations", json={"role": "coordinator"}).json()["id"]
        kept = browser.post("/api/conversations", json={"role": "inventory"}).json()["id"]
        cookie = browser.cookies.get("retail_assistant_session")
        for identifier in (deleted, kept):
            assert browser.post(
                "/api/conversations/" + identifier,
                json={
                    "parentId": None,
                    "message": {
                        "id": "u1",
                        "role": "user",
                        "content": [{"type": "text", "text": "Saved question"}],
                    },
                },
            ).status_code == 200
        path = "/api/conversations/" + deleted
        browser.cookies.clear()
        assert browser.delete(path).status_code == 404
        browser.cookies.set("retail_assistant_session", cookie)
        assert browser.get(path).status_code == 200
        assert browser.delete(path).status_code == 204
        assert browser.get(path).status_code == 404
        assert browser.post(path, json={}).status_code == 404
        assert browser.delete(path).status_code == 404
        assert (
            browser.post(
                "/api/agents/coordinator/message:stream",
                json={},
                headers={"x-retail-conversation": deleted},
            ).status_code == 403
        )
        assert [item["id"] for item in browser.get("/api/conversations").json()] == [kept]
        assert len(browser.get("/api/conversations/" + kept).json()["messages"]) == 1
    with sqlite3.connect(tmp_path / "conversations.sqlite3") as db:
        assert db.execute("SELECT conversation FROM messages").fetchall() == [(kept,)]
    with TestClient(make_app(tmp_path), base_url="http://localhost:8080") as browser:
        browser.cookies.set("retail_assistant_session", cookie)
        assert browser.get(path).status_code == 404
        assert [item["id"] for item in browser.get("/api/conversations").json()] == [kept]


def test_maps_derived_history_is_redacted_before_disk_write(tmp_path):
    with TestClient(make_app(tmp_path), base_url="http://localhost:8080") as browser:
        identifier = browser.post("/api/conversations", json={"role": "distribution"}).json()["id"]
        path = "/api/conversations/" + identifier
        entry = {
            "parentId": None,
            "message": {
                "id": "a1",
                "role": "assistant",
                "content": [{"type": "text", "text": "Route 92837.415"}],
                "metadata": {
                    "custom": {"a2a": {"contains_ephemeral_evidence": True, "route": "92837.415"}}
                },
            },
        }
        assert browser.post(path, json=entry).status_code == 200
        assert "92837.415" not in browser.get(path).text
    assert b"92837.415" not in (tmp_path / "conversations.sqlite3").read_bytes()


def test_native_card_routes_streams_and_server_side_credentials(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(
                200,
                json={
                    "name": "Inventory",
                    "supportedInterfaces": [{"url": "http://inventory:8000"}],
                    "securitySchemes": {"token": {}},
                },
            )
        if request.url.path == "/message:stream":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b'data: {"task":{"id":"t1"}}\n\n',
            )
        return httpx.Response(200, json={"id": "foreign-task", "contextId": "other-browser"})

    with TestClient(make_app(tmp_path, handler), base_url="http://localhost:8080") as browser:
        identifier = browser.post("/api/conversations", json={"role": "inventory"}).json()["id"]
        card = browser.get("/api/agents/inventory/.well-known/agent-card.json").json()
        assert card["supportedInterfaces"][0]["url"] == "http://localhost:8080/api/agents/inventory"
        assert "securitySchemes" not in card
        headers = {"x-retail-conversation": identifier, "authorization": "Bearer attacker"}
        payload = {
            "message": {"role": "ROLE_USER", "messageId": "u1", "parts": [{"text": "Count"}]},
            "metadata": {"delegation": {"forged": True}, "max_cost_usd": 1000},
        }
        response = browser.post(
            "/api/agents/inventory/message:stream", json=payload, headers=headers
        )
        assert response.status_code == 200
        assert response.text.startswith("data: ")
        assert TOKEN not in response.text
        forwarded = json.loads(seen[-1].content)
        assert forwarded["message"]["contextId"] == identifier
        assert forwarded["metadata"] == {"max_cost_usd": 1.0, "deadline_seconds": 180}
        assert seen[-1].headers["authorization"] == f"Bearer {TOKEN}"
        assert seen[-1].headers["a2a-version"] == "1.0"
        assert (
            browser.post(
                "/api/agents/inventory/tasks/foreign-task:cancel", headers=headers
            ).status_code
            == 404
        )
        assert (
            browser.post(
                "/api/agents/evil/message:stream", json=payload, headers=headers
            ).status_code
            == 404
        )
        assert browser.get("/api/agents/inventory/arbitrary", headers=headers).status_code == 404


def test_local_browser_boundary_and_safe_errors(tmp_path):
    def unavailable(request):
        raise httpx.ConnectError("private upstream information")

    with TestClient(make_app(tmp_path, unavailable), base_url="http://localhost:8080") as browser:
        assert browser.get("/api/catalog", headers={"host": "evil.example"}).status_code == 421
        assert (
            browser.get("/api/catalog", headers={"origin": "https://evil.example"}).status_code
            == 403
        )
        assert (
            browser.get("/api/catalog", headers={"sec-fetch-site": "cross-site"}).status_code == 403
        )
        failed = browser.get("/api/agents/inventory/.well-known/agent-card.json")
        assert failed.status_code == 502
        assert "private upstream" not in failed.text
        assert browser.post("/api/conversations", content=b"x" * 1_000_001).status_code == 400
        assert browser.get("/health").json()["ui"] == "assistant-ui"


def test_history_resumes_at_answer_even_if_user_write_arrives_later(tmp_path):
    from retail_insight.interfaces.gui_store import ConversationStore

    store = ConversationStore(tmp_path / "out-of-order.sqlite3")
    conversation = store.create("browser", "retail", "fixture")
    store.append(
        conversation["id"],
        {"parentId": "u1", "message": {"id": "a1", "role": "assistant", "content": []}},
    )
    store.append(
        conversation["id"],
        {"parentId": None, "message": {"id": "u1", "role": "user", "content": []}},
    )
    assert store.load(conversation["id"])["headId"] == "a1"
    store.db.close()
