"""Coordinator capabilities: evidence handling and bounded A2A delegation."""

import asyncio
import json

from retail_insight.runtime.budget import LimitReached
from retail_insight.runtime.context import DelegationContext
from retail_insight.tools.domain import common_tools


def build_tools(turn):
    delegation = DelegationTools(turn)
    return [*common_tools(turn), delegation.list_agents, delegation.delegate]


class DelegationTools:
    def __init__(self, turn):
        self.turn = turn
        self._budget_changed = asyncio.Condition()
        self._inflight = 0

    async def _reserve_allowance(self, agent: str) -> tuple[int, float, float] | dict:
        """Wait for unsettled child usage instead of treating a temporary hold as exhaustion."""
        budget = self.turn.budget
        waiting = False
        async with self._budget_changed:
            while True:
                try:
                    seconds = min(120, budget.work_remaining())
                except LimitReached:
                    return self._limit(agent, "deadline")
                allowance = min(0.75, budget.work_available_usd)
                # A child needs its own review reserve as well as room to investigate.
                if allowance >= budget.review_reserve + 0.15:
                    reservation = budget.reserve(allowance)
                    self._inflight += 1
                    self.turn.emit(
                        "delegation_start",
                        agent=agent,
                        allowance_usd=allowance,
                        deadline_seconds=seconds,
                    )
                    return reservation, allowance, seconds
                if not self._inflight:
                    return self._limit(agent, "cost_budget")
                if not waiting:
                    self.turn.emit("delegation_wait", agent=agent, reason="pending_usage")
                    waiting = True
                try:
                    await asyncio.wait_for(self._budget_changed.wait(), timeout=seconds)
                except TimeoutError:
                    # Recheck the parent deadline; the 120-second child cap is not a wait cap.
                    continue

    def _limit(self, agent: str, reason: str) -> dict:
        self.turn.emit("delegation_limit", agent=agent, reason=reason)
        return {
            "status": "limit",
            "agent": agent,
            "reason": reason,
            "message": "No specialist allowance remains within this prompt's cost or time limit. Return a concise partial answer identifying the missing comparison; do not infer findings from unavailable data.",
        }

    async def list_agents(self) -> dict:
        """Inspect the approved specialist catalog and choose useful capabilities."""
        return await self.turn.run_tool(
            "list_agents",
            lambda: {
                "agents": [
                    {
                        "name": "retail",
                        "capabilities": "Qualifying revenue, units, customers, orders, category/product trends; read-only scoped sales SQL.",
                    },
                    {
                        "name": "inventory",
                        "capabilities": "Modeled unsold inventory, inventory cost, aging, product counts at a business cutoff; no independent sales history.",
                    },
                    {
                        "name": "distribution",
                        "capabilities": "Distribution centers, scoped inventory attribution, facility locations; Google Maps route/weather if configured; no capacity, truck or delivery guarantees.",
                    },
                ]
            },
        )

    async def delegate(self, agent: str, question: str, evidence_ids: list[str]) -> dict:
        """Ask one approved specialist a focused question. Forward selected evidence if needed."""

        async def invoke():
            app = self.turn.app
            if agent not in {"retail", "inventory", "distribution"}:
                return {"status": "denied", "message": "Select a specialist from list_agents."}
            selected = [app.results[item] for item in evidence_ids]
            # Identifiers, scope, cost and time are injected by the runtime, never the model.
            if not question.strip() or len(question) > 6000:
                return {
                    "status": "invalid_request",
                    "message": "Provide a task containing 1-6,000 characters.",
                }
            try:
                delegation = DelegationContext(
                    original_user_request=self.turn.original_user_request,
                    evidence=selected,
                )
            except ValueError:
                return {"status": "invalid_request", "message": "Forward fewer or smaller results."}
            async with app.child_slots:
                grant = await self._reserve_allowance(agent)
                if isinstance(grant, dict):
                    return grant
                reservation, allowance, seconds = grant
                result = {}
                settled = False
                try:
                    result = await app.client.ask(
                        agent,
                        question,
                        app.identity.user_id,
                        app.children.get(agent),
                        max_cost_usd=allowance,
                        deadline_seconds=seconds,
                        as_of=app.as_of,
                        snapshot_at=app.snapshot_at,
                        backend=app.settings.backend,
                        parent_turn_id=app.turn_id,
                        delegation=delegation,
                        stream=True,
                    )
                    usage = result.get("usage", {}).get("accounted_usd")
                    if type(usage) in (int, float):
                        settled = self.turn.budget.settle_external(reservation, usage)
                finally:
                    async with self._budget_changed:
                        self._inflight -= 1
                        self._budget_changed.notify_all()
                    self.turn.emit(
                        "delegation_end",
                        agent=agent,
                        status=result.get("status", "interrupted"),
                        usage_settled=settled,
                    )
                if result.get("context_id"):
                    app.children[agent] = result["context_id"]
                if (
                    result.get("scope") != app.identity.scope
                    or result.get("as_of") != app.as_of
                    or result.get("snapshot_at") != app.snapshot_at
                ):
                    return {
                        "status": "invalid_evidence",
                        "message": "Specialist evidence scope or time does not match this request.",
                    }
                if result.get("status") != "approved":
                    return {
                        "status": "incomplete",
                        "agent": agent,
                        "message": result.get(
                            "markdown", "Specialist did not produce a reviewed answer."
                        ),
                    }
                imported = []
                mapping = {}
                for source in result.get("evidence", []):
                    artifact = self.turn.artifact(
                        {
                            **source,
                            "source_agent": agent,
                            "source_task_id": result["task_id"],
                            "source_evidence_id": source.get("id"),
                            "parents": [],
                        },
                        f"{agent}: {source.get('purpose', 'specialist evidence')}",
                    )
                    mapping[source.get("id")] = artifact["id"]
                    imported.append(artifact)
                summary = self.turn.artifact(
                    {
                        "columns": ["agent", "reviewed_summary"],
                        "rows": [{"agent": agent, "reviewed_summary": result["markdown"]}],
                        "source_agent": agent,
                        "source_task_id": result["task_id"],
                        "source_evidence_mapping": mapping,
                        "definitions": "Specialist narrative is context, not independent proof. Verify claims against imported evidence and matching scope/time.",
                        "truncated": False,
                    },
                    f"{agent} response",
                    [entry["id"] for entry in imported],
                )
                return {
                    "status": "ok",
                    "summary": summary,
                    "evidence": imported,
                    "source_evidence_mapping": mapping,
                }

        return await self.turn.run_tool(
            "delegate", invoke, agent + question + json.dumps(evidence_ids)
        )
