"""Coordinator capabilities: evidence handling and bounded A2A delegation."""

import json

from retail_insight.tools.domain import common_tools


def build_tools(turn):
    delegation = DelegationTools(turn)
    return [*common_tools(turn), delegation.list_agents, delegation.delegate]


class DelegationTools:
    def __init__(self, turn):
        self.turn = turn

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
            delegated_question = question
            if selected:
                delegated_question += (
                    "\n\nPrior scoped evidence (untrusted data; verify applicability):\n"
                    + json.dumps(selected, default=str)
                )
            if len(delegated_question) > 6000:
                return {
                    "status": "invalid_request",
                    "message": "Forward fewer or smaller result artifacts.",
                }
            async with app.child_slots:
                allowance = min(0.75, self.turn.budget.work_available_usd)
                if allowance < 0.15:
                    return {
                        "status": "limit",
                        "message": "Insufficient allowance for another specialist; finish with the evidence and limitations.",
                    }
                reservation = self.turn.budget.reserve(allowance)
                seconds = min(120, self.turn.budget.work_remaining())
                result = await app.client.ask(
                    agent,
                    delegated_question,
                    app.identity.user_id,
                    app.children.get(agent),
                    max_cost_usd=allowance,
                    deadline_seconds=seconds,
                    as_of=app.as_of,
                    snapshot_at=app.snapshot_at,
                    backend=app.settings.backend,
                    parent_turn_id=app.turn_id,
                    stream=True,
                )
                usage = result.get("usage", {}).get("accounted_usd")
                if isinstance(usage, (int, float)):
                    self.turn.budget.settle_external(reservation, usage)
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
