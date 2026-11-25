"""Local GUI setup, browser isolation and the credential boundary."""

import json

import httpx
import pytest
from starlette.testclient import TestClient

from retail_insight.interfaces.gui import create_app

CATALOG = {
    role: {
        "url": f"http://{role}:8000",
        "card_url": f"http://{role}:8000/.well-known/agent-card.json",
    }
    for role in ("coordinator", "retail", "inventory", "distribution")
}
TOKEN = "test-local-demo-credential"


@pytest.fixture
def gateway():
    requests = []

    def upstream(request):
        requests.append(request)
        if request.url.path == "/api/config":
            return httpx.Response(
                200,
                stream=httpx.ByteStream(b'{"mode": "hosted", "features": {}}'),
                headers={
                    "set-cookie": "__Host-a2a_inspector_session=browser-session; Path=/; HttpOnly; Secure; SameSite=Strict"
                },
            )
        if request.url.path == "/api/connections":
            return httpx.Response(
                201, stream=httpx.ByteStream(b'{"id":"conn-1","auth":{"type":"bearer"}}')
            )
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"data: first\n\ndata: second\n\n"),
            headers={"content-type": "text/event-stream"},
        )

    app = create_app(CATALOG, TOKEN, transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url="http://localhost:8080") as client:
        yield client, requests


def test_plain_url_bootstraps_coordinator_without_login(gateway):
    client, requests = gateway
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json()["agentCardUrl"] == CATALOG["coordinator"]["card_url"]
    assert TOKEN not in response.text
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Secure" not in cookie
    client.get("/api/catalog")
    assert cookie.startswith("retail_gui_workspace_session_8080=")
    assert requests[-1].headers["cookie"] == "__Host-a2a_inspector_session=browser-session"
    client.cookies.clear()
    client.get("/api/catalog")
    assert "cookie" not in requests[-1].headers  # Never reuse another browser's upstream cookie.


def test_document_initializes_session_before_parallel_browser_requests(gateway):
    client, requests = gateway
    response = client.get("/")
    assert [request.url.path for request in requests] == ["/api/config", "/"]
    assert "retail_gui_workspace_session_8080=" in response.headers["set-cookie"]
    client.get("/api/catalog")
    assert requests[-1].headers["cookie"] == "__Host-a2a_inspector_session=browser-session"


@pytest.mark.parametrize("role", CATALOG)
def test_each_agent_connects_with_server_side_credentials(gateway, role):
    client, requests = gateway
    response = client.post("/api/connections", json={"cardUrl": CATALOG[role]["card_url"]})
    assert response.status_code == 201
    assert json.loads(requests[-1].content)["auth"] == {"bearer": {"value": TOKEN}}
    assert TOKEN not in response.text


def test_reconnect_ignores_untrusted_card_and_restores_workspace_authentication(gateway):
    client, requests = gateway
    response = client.post(
        "/api/connections",
        json={
            "cardUrl": CATALOG["inventory"]["card_url"],
            "card": {"url": "http://attacker.invalid"},
            "headers": [{"name": "x-retail-identity", "value": "ceo"}],
            "serviceParams": {"Authorization": "Bearer overridden"},
            "auth": {"bearer": {"ref": "expired-session-secret"}},
            "contextId": "owned-context",
            "replaces": "conn-old",
        },
    )
    assert response.status_code == 201
    payload = json.loads(requests[-1].content)
    assert payload == {
        "cardUrl": CATALOG["inventory"]["card_url"],
        "auth": {"bearer": {"value": TOKEN}},
        "contextId": "owned-context",
        "replaces": "conn-old",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"cardUrl": "http://attacker.invalid/card"},
        {"cardUrl": CATALOG["retail"]["card_url"], "interface": {"url": "http://attacker.invalid"}},
        {"card": {"url": CATALOG["retail"]["url"]}},
        [],
        None,
    ],
)
def test_credentials_never_go_to_an_unapproved_endpoint(gateway, payload):
    client, requests = gateway
    response = client.post("/api/connections", content=json.dumps(payload))
    assert response.status_code == 400
    assert not requests


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"host": "attacker.invalid:8080"}, 421),
        ({"origin": "http://attacker.invalid"}, 403),
        ({"origin": "http://localhost:9999"}, 403),
        ({"sec-fetch-site": "cross-site"}, 403),
    ],
)
def test_browser_origin_boundary(gateway, headers, status):
    client, requests = gateway
    assert client.post("/api/connections", headers=headers, json={}).status_code == status
    assert not requests


def test_streaming_protocol_responses_are_preserved(gateway):
    client, _ = gateway
    response = client.get("/api/events")
    assert response.headers["content-type"] == "text/event-stream"
    assert response.content == b"data: first\n\ndata: second\n\n"


def test_health_advertises_full_dataset_without_a_persona(gateway):
    client, _ = gateway
    assert client.get("/health").json() == {"status": "ok", "scope": "all brands"}


def test_old_demo_browser_session_is_not_reused(gateway):
    client, requests = gateway
    client.cookies.set("retail_gui_session_8080", "old-demo-session")
    client.get("/api/catalog")
    assert "cookie" not in requests[-1].headers
