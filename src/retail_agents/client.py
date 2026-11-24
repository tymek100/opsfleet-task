"""A2A JSON-RPC client for the approved local catalog."""

import asyncio
import json
import uuid
from urllib.parse import urlparse

import httpx
from opentelemetry.propagate import inject

from retail_agents.auth import canonical_json, signed_headers


class AgentClient:
    def __init__(self, urls: dict[str, str], token: str, *, signed: bool = True):
        self.urls, self.token, self.signed = urls, token, signed
        for role, url in urls.items():
            parsed = urlparse(url)
            if (
                role not in {"retail", "inventory", "distribution", "coordinator"}
                or parsed.scheme != "http"
                or parsed.hostname not in {role, "localhost", "127.0.0.1"}
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("The catalog must contain approved local agent endpoints")

    def headers(self, body, identity, role):
        headers = {"content-type": "application/json"}
        headers.update(
            signed_headers(self.token, body, identity, role)
            if self.signed
            else {"authorization": f"Bearer {self.token}"}
        )
        inject(headers)
        return headers

    async def cancel(self, role: str, task_id: str, identity: str):
        body = canonical_json(
            {
                "jsonrpc": "2.0",
                "id": uuid.uuid4().hex,
                "method": "tasks/cancel",
                "params": {"id": task_id},
            }
        )
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
            await client.post(
                self.urls[role], content=body, headers=self.headers(body, identity, role)
            )

    async def ask(
        self,
        role: str,
        question: str,
        identity: str = "alice",
        context_id: str | None = None,
        *,
        max_cost_usd: float = 1,
        deadline_seconds: float = 180,
        as_of: str | None = None,
        snapshot_at: str | None = None,
        backend: str | None = None,
        request_id: str | None = None,
        parent_turn_id: str | None = None,
        stream: bool = False,
    ) -> dict:
        message_id = request_id or uuid.uuid4().hex
        message = {
            "role": "user",
            "messageId": message_id,
            "parts": [{"kind": "text", "text": question}],
        }
        if context_id:
            message["contextId"] = context_id
        metadata = {
            "max_cost_usd": max_cost_usd,
            "deadline_seconds": deadline_seconds,
            "as_of": as_of,
            "snapshot_at": snapshot_at,
            "backend": backend,
            "parent_turn_id": parent_turn_id,
        }
        payload = {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "message/stream" if stream else "message/send",
            "params": {
                "message": message,
                "metadata": metadata,
                "configuration": {"blocking": True},
            },
        }
        body = canonical_json(payload)
        headers = self.headers(body, identity, role)
        task = {}
        try:
            async with (
                asyncio.timeout(deadline_seconds + 10),
                httpx.AsyncClient(
                    timeout=deadline_seconds + 15, follow_redirects=False, trust_env=False
                ) as client,
            ):
                if stream:
                    async with client.stream(
                        "POST", self.urls[role], content=body, headers=headers
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            event = json.loads(line[5:].strip())
                            if "error" in event:
                                raise RuntimeError(
                                    f"A2A request failed: {event['error'].get('code', 'unknown')}"
                                )
                            value = event["result"]
                            if value.get("kind") == "task":
                                task.update(value)
                            elif value.get("taskId"):
                                task.update(id=value["taskId"], contextId=value["contextId"])
                                if "artifact" in value:
                                    task.setdefault("artifacts", []).append(value["artifact"])
                                if "status" in value:
                                    task["status"] = value["status"]
                            if value.get("final"):
                                break
                    document = {"result": task}
                else:
                    response = await client.post(self.urls[role], content=body, headers=headers)
                    response.raise_for_status()
                    document = response.json()
        except (asyncio.CancelledError, TimeoutError, httpx.TimeoutException):
            if task.get("id"):
                cancellation = asyncio.create_task(self.cancel(role, task["id"], identity))
                try:
                    await asyncio.wait_for(asyncio.shield(cancellation), timeout=5)
                except (Exception, asyncio.CancelledError):
                    cancellation.cancel()
            raise
        if "error" in document:
            raise RuntimeError(f"A2A request failed: {document['error'].get('code', 'unknown')}")
        task = document["result"]
        for artifact in task.get("artifacts", []):
            for part in artifact.get("parts", []):
                if (
                    part.get("kind") == "data"
                    and part.get("data", {}).get("schema_version") == "retail-agent-result-v1"
                ):
                    return {**part["data"], "task_id": task["id"], "context_id": task["contextId"]}
        return {
            "status": task.get("status", {}).get("state", "failed"),
            "markdown": "No reviewed answer was returned.",
            "evidence": [],
            "usage": {},
            "context_id": task.get("contextId"),
            "task_id": task.get("id"),
        }
