import json

import httpx
import pytest

from retail_insight.interfaces.gui import COOKIE, create_app


class Team:
    def __init__(self):
        self.calls = []
        self.deleted = []

    async def ask(self, role, question, owner, context, **kwargs):
        self.calls.append((role, question, owner, context))
        return {
            "status": "approved",
            "markdown": "| Category | Units |\n|---|---:|\n| Jeans | 3 |",
            "usage": {"accounted_usd": 0.01},
            "evidence": [{"id": "E1"}],
        }

    def forget(self, *args):
        self.deleted.append(args)

    def close(self):
        pass


@pytest.fixture
def app(settings, tmp_path):
    team = Team()
    application = create_app(settings, team, data_dir=tmp_path / "gui", session_key="a" * 64)
    return application, team


async def test_signed_session_ownership_stream_and_deletion(app):
    application, team = app
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://127.0.0.1:8080"
        ) as owner,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://127.0.0.1:8080"
        ) as stranger,
    ):
        response = await owner.post("/api/conversations", json={"role": "coordinator"})
        assert response.status_code == 201
        assert (
            "HttpOnly" in response.headers["set-cookie"]
            and "SameSite=strict" in response.headers["set-cookie"]
        )
        identifier = response.json()["id"]
        assert (await stranger.get("/api/conversations/" + identifier)).status_code == 404
        assert (
            await stranger.post(
                "/api/agents/coordinator/chat",
                headers={"x-retail-conversation": identifier},
                json={"question": "Hello"},
            )
        ).status_code == 403
        result = await owner.post(
            "/api/agents/coordinator/chat",
            headers={"x-retail-conversation": identifier},
            json={"question": "Hello"},
        )
        events = [json.loads(line) for line in result.text.splitlines()]
        assert events[-1]["type"] == "result" and events[-1]["result"]["status"] == "approved"
        assert "evidence" not in events[-1]["result"]
        assert len(team.calls) == 1
        assert (await owner.delete("/api/conversations/" + identifier)).status_code == 204
        assert team.deleted
        assert (await owner.get("/api/conversations/" + identifier)).status_code == 404


async def test_forged_cookie_and_cross_origin_cannot_access_conversation(app):
    application, team = app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://127.0.0.1:8080"
    ) as client:
        identifier = (await client.post("/api/conversations", json={"role": "retail"})).json()["id"]
        cookie = client.cookies.get(COOKIE)
        assert cookie is not None
        client.cookies.clear()
        client.cookies.set(COOKIE, cookie.split(".")[0] + "." + "0" * 64)
        assert (await client.get("/api/conversations/" + identifier)).status_code == 404
        assert (
            await client.post(
                "/api/conversations",
                json={"role": "retail"},
                headers={"origin": "https://evil.example"},
            )
        ).status_code == 403
        assert (await client.get("/health", headers={"host": "evil.example"})).status_code == 421
        assert not team.calls


async def test_cards_describe_actual_protocol_not_a2a(app):
    application, _ = app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://127.0.0.1:8080"
    ) as client:
        card = (await client.get("/agent-card.json")).json()
        assert card["framework"] == "LangGraph"
        assert card["interfaces"][0]["protocol"] == "HTTP+NDJSON"
        assert not card["hosting"]["deployed"]
