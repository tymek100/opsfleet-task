"""Local specialist subgraphs and durable approved conversation context."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sqlite3
import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from retail_insight.agents.coordinator.agent import CoordinatorAnalyst
from retail_insight.agents.distribution.agent import DistributionAnalyst
from retail_insight.agents.inventory.agent import InventoryAnalyst
from retail_insight.agents.retail.agent import RetailAnalyst
from retail_insight.contracts import Answer, Identity
from retail_insight.integrations.maps.privacy import contains_maps

AGENT_TYPES = {
    "coordinator": CoordinatorAnalyst,
    "retail": RetailAnalyst,
    "inventory": InventoryAnalyst,
    "distribution": DistributionAnalyst,
}


class AgentTeam:
    """One process, independent local LangGraph instances, no inter-agent transport.

    Each prompt has a fresh budget. Delegations reserve from the parent's budget
    and refund only confirmed usage. Context is isolated by owner, role and data
    source. No raw model messages or unapproved candidates are persisted.
    """

    def __init__(self, settings, *, model_factory=None, observer=None, observation_mode="metadata"):
        self.settings, self.model_factory = settings, model_factory
        self.observer, self.observation_mode = observer, observation_mode
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(settings.data_dir / "workflow.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS contexts (id TEXT PRIMARY KEY, state TEXT NOT NULL)"
        )
        self.locks = {}

    def key(self, role, owner, context):
        return hashlib.sha256(
            json.dumps(
                [
                    self.settings.backend,
                    self.settings.warehouse_source_dataset,
                    str(self.settings.fixture_path),
                    str(self.settings.domain_fixture_path),
                    role,
                    owner,
                    context,
                ]
            ).encode()
        ).hexdigest()

    def forget(self, role, owner, context):
        key = self.key(role, owner, context)
        with self.db:
            self.db.execute("DELETE FROM contexts WHERE id=?", (key,))
        # Descendant contexts are deterministically derived, so deletion removes them too.
        for child in ("retail", "inventory", "distribution"):
            child_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{owner}/{context}/{child}").hex
            with self.db:
                self.db.execute(
                    "DELETE FROM contexts WHERE id=?", (self.key(child, owner, child_id),)
                )

    def context_keys(self, owner, identifier):
        keys = [self.key(role, owner, identifier) for role in AGENT_TYPES]
        for role in ("retail", "inventory", "distribution"):
            child = uuid.uuid5(uuid.NAMESPACE_URL, f"{owner}/{identifier}/{role}").hex
            keys.append(self.key(role, owner, child))
        return keys

    def export_contexts(self, owner, identifier):
        result = {}
        for key in self.context_keys(owner, identifier):
            row = self.db.execute("SELECT state FROM contexts WHERE id=?", (key,)).fetchone()
            if row:
                result[key] = json.loads(row[0])
        return result

    def restore_contexts(self, owner, identifier, states):
        allowed = set(self.context_keys(owner, identifier))
        if set(states) - allowed:
            raise ValueError("Checkpoint context does not belong to this conversation")
        with self.db:
            for key, state in states.items():
                self.db.execute(
                    "INSERT INTO contexts VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                    (key, json.dumps(state)),
                )

    async def ask(
        self,
        role,
        question,
        owner="workspace",
        context_id=None,
        *,
        max_cost_usd=None,
        deadline_seconds=None,
        as_of=None,
        snapshot_at=None,
        backend=None,
        parent_turn_id=None,
        delegation=None,
        stream=False,
        progress=None,
    ):
        for value in (max_cost_usd, deadline_seconds):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError("Budget and deadline must be finite and positive")
        if role not in AGENT_TYPES:
            raise ValueError("Unknown agent")
        if backend is not None and backend != self.settings.backend:
            raise ValueError("The data backend cannot change during a conversation")
        context_id = context_id or uuid.uuid4().hex
        key = self.key(role, owner, context_id)
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            settings = self.settings.model_copy(
                update={
                    "question_budget_usd": min(
                        self.settings.question_budget_usd,
                        max_cost_usd or self.settings.question_budget_usd,
                    ),
                    "turn_timeout_seconds": min(
                        self.settings.turn_timeout_seconds,
                        deadline_seconds or self.settings.turn_timeout_seconds,
                    ),
                    "data_dir": self.settings.data_dir / key,
                }
            )
            now = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
            as_of = now.isoformat()
            if settings.backend == "bigquery" and snapshot_at is None:
                snapshot_at = as_of
            events = []

            def capture(event):
                events.append(event)
                if self.observer:
                    self.observer(event)

            kwargs = {
                "client": self,
                "as_of": as_of,
                "snapshot_at": snapshot_at,
                "clock": lambda: datetime.now(UTC),
                "gateway_clock": lambda: now,
                "observer": capture,
                "observation_mode": self.observation_mode,
                "progress": progress,
            }
            if self.model_factory:
                kwargs.update(
                    model=self.model_factory(role, False),
                    reviewer_model=self.model_factory(role, True),
                )
            app = AGENT_TYPES[role](settings, Identity(owner, None), **kwargs)
            app.conversation_id = context_id
            row = self.db.execute("SELECT state FROM contexts WHERE id=?", (key,)).fetchone()
            if row:
                state = json.loads(row[0])
                app.results, app.history = state["results"], state["history"]
                app.answers = {k: Answer(**v) for k, v in state["answers"].items()}
                app._result_counter = state["counter"]
            app.children = {
                child: uuid.uuid5(uuid.NAMESPACE_URL, f"{owner}/{context_id}/{child}").hex
                for child in ("retail", "inventory", "distribution")
            }
            try:
                result = await app.ask(question, delegation=delegation)
                ephemeral = contains_maps(app.results)
                if not ephemeral:
                    state = {
                        "results": app.results,
                        "history": app.history,
                        "answers": {k: asdict(v) for k, v in app.answers.items()},
                        "counter": app._result_counter,
                    }
                    with self.db:
                        self.db.execute(
                            "INSERT INTO contexts VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                            (key, json.dumps(state, default=str)),
                        )
                return {
                    **asdict(result),
                    "schema_version": "langgraph-v1",
                    "context_id": context_id,
                    "task_id": app.turn_id,
                    "trace_id": app._trace_ids.get("trace_id"),
                    "markdown": result.answer.markdown if result.answer else result.message,
                    "scope": app.identity.scope,
                    "as_of": as_of,
                    "snapshot_at": snapshot_at,
                    "contains_ephemeral_evidence": ephemeral,
                    "observations": events,
                    "outcome": result.answer.outcome if result.answer else None,
                }
            finally:
                app.reports.close()
                close = getattr(app.gateway, "close", None)
                if close:
                    close()
                if not self.model_factory and app.model is not None:
                    close = getattr(getattr(app.model, "client", None), "close", None)
                    if close:
                        close()

    def close(self):
        self.db.close()
