"""Authenticated A2A behavior with a deterministic reviewed-runtime boundary."""

import asyncio
import sqlite3
import time
from typing import ClassVar

import httpx
import pytest

from retail_insight.a2a.auth import authenticate, canonical_json, signed_headers
from retail_insight.a2a.client import AgentClient
from retail_insight.a2a.server import create_app
from retail_insight.contracts import Answer, TurnResult
from retail_insight.runtime.service import PersistentBudget

SECRET = "a-local-contract-signing-key-with-48-characters-minimum"
DEMO_TOKEN = "local-alice-demo-token"
AS_OF = "2026-04-01T00:00:00+00:00"


class ReviewedRuntime:
    """Replace only model execution; exercise actual A2A, stores, settings and auth."""

    instances: ClassVar[list] = []
    calls: ClassVar[list] = []
    entered: ClassVar[asyncio.Event]

    def __init__(self, role, settings, identity, **kwargs):
        self.role, self.settings, self.identity = role, settings, identity
        self.as_of, self.snapshot_at = kwargs["as_of"], kwargs["snapshot_at"]
        self.history, self.results, self.answers, self.children = [], {}, {}, {}
        self._result_counter = 0
        self._trace_ids, self.observations = {}, []
        self.observation_mode = "metadata"
        self.ephemeral_content = False
        self.__class__.instances.append(self)

    async def ask(self, question):
        self.calls.append((self.identity.user_id, question, self.settings.question_budget_usd))
        if question == "Wait for cancellation":
            self.entered.set()
            await asyncio.Event().wait()
        if question == "Read ephemeral route":
            self.results["E1"] = {
                "id": "E1",
                "storage_policy": "ephemeral-provider-content",
                "provider": "Google Maps",
                "result": {"distanceMeters": 92837.415},
            }
            answer = Answer(
                "A1", "The road route measures 92837.415 meters.", ["E1"], "answer", True
            )
            trace = [{"event": "review", "finding": "The 92837.415 route figure is supported."}]
        else:
            answer = Answer("A1", f"Reviewed {self.identity.scope} response.", [], "answer", True)
            trace = []
        self.answers[answer.id] = answer
        self.history.append({"question": question, "answer": answer.markdown})
        return TurnResult(
            answer,
            "approved",
            "",
            trace,
            {"accounted_usd": 0.01},
            list(self.results.values()),
            0.01,
        )


@pytest.fixture
def app(settings, monkeypatch):
    ReviewedRuntime.instances, ReviewedRuntime.calls = [], []
    ReviewedRuntime.entered = asyncio.Event()
    monkeypatch.setattr("retail_insight.a2a.server.create_agent", ReviewedRuntime)
    return create_app(
        "inventory",
        settings,
        secret=SECRET,
        demo_token=DEMO_TOKEN,
        public_url="http://inventory:8000",
    )


def request_payload(
    message_id="message-1", question="Count our stock", context_id=None, **metadata
):
    message = {
        "role": "user",
        "messageId": message_id,
        "parts": [{"kind": "text", "text": question}],
    }
    if context_id:
        message["contextId"] = context_id
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "message/send",
        "params": {
            "message": message,
            "metadata": {"as_of": AS_OF, **metadata},
            "configuration": {"blocking": True},
        },
    }


async def call(client, payload, *, identity="alice", audience="inventory", demo=False):
    body = canonical_json(payload)
    headers = {"content-type": "application/json"}
    headers.update(
        {"authorization": f"Bearer {DEMO_TOKEN}"}
        if demo
        else signed_headers(SECRET, body, identity, audience)
    )
    return await client.post("/", content=body, headers=headers)


def task_result(response):
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "error" not in payload, payload
    return payload["result"]


def test_transport_signature_covers_identity_body_audience_and_expiry(monkeypatch):
    body = canonical_json({"message": "hello"})
    headers = signed_headers(SECRET, body, "alice", "inventory")
    assert authenticate(headers, body, SECRET, DEMO_TOKEN, "inventory").identity == "alice"
    for bad_headers, bad_body, audience in [
        ({**headers, "x-retail-identity": "ceo"}, body, "inventory"),
        (headers, body + b" ", "inventory"),
        (headers, body, "distribution"),
        ({**headers, "x-retail-signature": "0" * 64}, body, "inventory"),
    ]:
        with pytest.raises(ValueError):
            authenticate(bad_headers, bad_body, SECRET, DEMO_TOKEN, audience)
    now = time.time()
    monkeypatch.setattr("retail_insight.a2a.auth.time.time", lambda: now + 301)
    with pytest.raises(ValueError):
        authenticate(headers, body, SECRET, DEMO_TOKEN, "inventory")


def test_demo_token_cannot_become_another_user():
    principal = authenticate(
        {"authorization": f"Bearer {DEMO_TOKEN}", "x-retail-identity": "ceo"},
        b"{}",
        SECRET,
        DEMO_TOKEN,
        "inventory",
    )
    assert principal.identity == "alice"
    assert principal.service is False


@pytest.mark.asyncio
async def test_public_card_and_authenticated_message(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        card = await client.get("/.well-known/agent-card.json")
        assert card.status_code == 200
        assert card.json()["url"] == "http://inventory:8000"
        assert "securitySchemes" in card.json()
        denied = await client.post("/", json=request_payload())
        assert denied.status_code == 401
        wrong_service = await call(client, request_payload(), audience="distribution")
        assert wrong_service.status_code == 401
        task = task_result(await call(client, request_payload()))
        assert task["status"]["state"] == "completed"
        assert ReviewedRuntime.calls == [
            ("alice", "Count our stock", ReviewedRuntime.instances[0].settings.question_budget_usd)
        ]


@pytest.mark.asyncio
async def test_duplicate_completed_request_is_replayed_without_model_work(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        first = task_result(await call(client, request_payload()))
        second = task_result(await call(client, request_payload()))
        assert first["contextId"] == second["contextId"]
        assert first["artifacts"][0]["parts"] == second["artifacts"][0]["parts"]
        assert len(ReviewedRuntime.calls) == 1
        conflict = task_result(await call(client, request_payload(question="Different content")))
        assert conflict["status"]["state"] == "failed"
        assert len(ReviewedRuntime.calls) == 1


@pytest.mark.asyncio
async def test_context_and_task_reads_are_owner_scoped(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        alice_task = task_result(await call(client, request_payload()))
        query = {
            "jsonrpc": "2.0",
            "id": "get-task",
            "method": "tasks/get",
            "params": {"id": alice_task["id"]},
        }
        assert task_result(await call(client, query))["id"] == alice_task["id"]
        bob_read = (await call(client, query, identity="bob")).json()
        assert "error" in bob_read
        assert "Reviewed Calvin Klein" not in str(bob_read)
        bob_followup = (
            await call(
                client,
                request_payload("bob-follow", "Continue", alice_task["contextId"]),
                identity="bob",
            )
        ).json()
        assert "error" in bob_followup
        assert "Reviewed Calvin Klein" not in str(bob_followup)
        assert len(ReviewedRuntime.calls) == 1


@pytest.mark.asyncio
async def test_followup_gets_new_budget_and_preserves_approved_history(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        first = task_result(await call(client, request_payload(max_cost_usd=0.2)))
        second = task_result(
            await call(
                client,
                request_payload(
                    "follow", "Explain stock age", first["contextId"], max_cost_usd=0.3
                ),
            )
        )
        assert second["status"]["state"] == "completed"
        assert [row[2] for row in ReviewedRuntime.calls] == [0.2, 0.3]
        assert len(ReviewedRuntime.instances[-1].history) == 2
        invalid_snapshot = task_result(
            await call(
                client,
                request_payload(
                    "changed",
                    "Continue",
                    first["contextId"],
                    snapshot_at="2026-11-01T00:00:00+00:00",
                ),
            )
        )
        assert invalid_snapshot["status"]["state"] == "failed"
        assert len(ReviewedRuntime.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"max_cost_usd": -1},
        {"max_cost_usd": 0},
        {"max_cost_usd": float("nan")},
        {"deadline_seconds": -1},
        {"deadline_seconds": 0},
        {"deadline_seconds": float("nan")},
        {"backend": "bigquery"},
    ],
)
async def test_invalid_budget_parameters_do_not_start_runtime(app, metadata):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        task = task_result(await call(client, request_payload(**metadata)))
        assert task["status"]["state"] == "failed"
        assert not ReviewedRuntime.calls


@pytest.mark.asyncio
async def test_budget_ceiling_and_demo_identity_are_not_model_editable(app, settings):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        task = task_result(
            await call(
                client,
                request_payload(
                    max_cost_usd=1000, deadline_seconds=1000, identity="ceo", brands=["Levi's"]
                ),
                demo=True,
            )
        )
        assert task["status"]["state"] == "completed"
        runtime = ReviewedRuntime.instances[0]
        assert runtime.identity.user_id == "alice"
        assert runtime.settings.question_budget_usd == settings.question_budget_usd
        assert 0 < runtime.settings.turn_timeout_seconds <= settings.turn_timeout_seconds


@pytest.mark.asyncio
async def test_cancellation_requires_task_ownership(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        payload = request_payload(question="Wait for cancellation")
        payload["params"]["configuration"]["blocking"] = False
        task = task_result(await call(client, payload))
        await asyncio.wait_for(ReviewedRuntime.entered.wait(), 2)
        cancel = {
            "jsonrpc": "2.0",
            "id": "cancel",
            "method": "tasks/cancel",
            "params": {"id": task["id"]},
        }
        bob = (await call(client, cancel, identity="bob")).json()
        assert "error" in bob
        canceled = task_result(await call(client, cancel))
        assert canceled["status"]["state"] == "canceled"
        replay = task_result(await call(client, request_payload(question="Wait for cancellation")))
        assert replay["status"]["state"] == "failed"
        assert len(ReviewedRuntime.calls) == 1


def test_persistent_child_settlement_is_once_and_unknown_cost_stays_reserved(settings):
    writes = []
    ledger = PersistentBudget(settings, lambda snapshot: writes.append(dict(snapshot)))
    first = ledger.reserve(0.2)
    unknown = ledger.reserve(0.3)
    assert writes[-1]["reserved_usd"] == 0.5
    assert ledger.settle_external(first, 0.04)
    assert not ledger.settle_external(first, 0.04)
    assert not ledger.settle_external(unknown, float("nan"))
    assert ledger.reserved_usd == pytest.approx(0.3)
    assert ledger.spent_usd == pytest.approx(0.04)
    assert writes[-1]["accounted_usd"] == 0.34


def test_failed_child_dispatch_keeps_reserved_allowance(settings):
    writes = []
    ledger = PersistentBudget(settings, writes.append)
    reservation = ledger.reserve(0.2)
    # No authenticated usage receipt arrived; there is intentionally no refund.
    assert reservation in ledger._reservations
    assert ledger.accounted_usd == pytest.approx(0.2)
    assert writes[-1]["reserved_usd"] == 0.2


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_native_agent_client_decodes_scoped_artifact(app, monkeypatch, stream):
    original = httpx.AsyncClient

    def local_client(**kwargs):
        return original(transport=httpx.ASGITransport(app=app), **kwargs)

    monkeypatch.setattr("retail_insight.a2a.client.httpx.AsyncClient", local_client)
    client = AgentClient({"inventory": "http://inventory:8000"}, SECRET)
    result = await client.ask(
        "inventory", "Count our stock", identity="bob", as_of=AS_OF, stream=stream
    )
    assert result["status"] == "approved"
    assert result["scope"] == "Levi's"
    assert result["context_id"] and result["task_id"]
    assert result["usage"]["accounted_usd"] == 0.01


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "http://evil.example/",
        "file:///tmp/key",
        "http://inventory:8000/?secret=x",
        "http://user:pw@inventory:8000/",
    ],
)
def test_catalog_cannot_redirect_delegation_to_external_endpoints(url):
    with pytest.raises(ValueError):
        AgentClient({"inventory": url}, SECRET)


@pytest.mark.asyncio
async def test_maps_content_is_returned_live_but_never_persisted_in_tasks_or_context(app, settings):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        task = task_result(await call(client, request_payload(question="Read ephemeral route")))
        assert "92837.415" in str(task)
        query = {
            "jsonrpc": "2.0",
            "id": "get-maps",
            "method": "tasks/get",
            "params": {"id": task["id"]},
        }
        stored = task_result(await call(client, query))
        assert "92837.415" not in str(stored)
    with sqlite3.connect(settings.data_dir / "a2a.sqlite3") as db:
        for table in ("contexts", "tasks", "requests"):
            rows = db.execute(f"SELECT * FROM {table}").fetchall()
            assert "92837.415" not in str(rows), table
