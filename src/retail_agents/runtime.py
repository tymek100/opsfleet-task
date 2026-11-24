"""Role-specific capabilities on the existing reviewed ADK agent loop."""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from google.adk.tools import ToolContext

from retail_agent.budget import Budget
from retail_agent.runtime import Analyst
from retail_agent.skills import SkillCatalog
from retail_agent.skills.catalog import Role
from retail_agent.tools.analytics import DataTools
from retail_agent.tools.completion import CompletionTools
from retail_agent.tools.knowledge import KnowledgeTools
from retail_agent.tools.reports import ReportTools
from retail_agent.tools.skills import SkillTools
from retail_agents.domains.maps import MapsClient
from retail_agents.ephemeral import contains_maps
from retail_agents.privacy import screen_role_text

ROOT = Path(__file__).parent


class PersistentBudget(Budget):
    def __init__(self, settings, persist):
        super().__init__(settings)
        self.persist = persist

    def reserve(self, amount, *, keep_review=True):
        token = super().reserve(amount, keep_review=keep_review)
        self.persist(self.snapshot())
        return token

    def settle_model(self, reservation, **usage):
        try:
            return super().settle_model(reservation, **usage)
        finally:
            self.persist(self.snapshot())

    def settle_external(self, reservation, accounted_usd):
        try:
            return super().settle_external(reservation, accounted_usd)
        finally:
            self.persist(self.snapshot())


class RoleSkills:
    def __init__(self, role):
        self.common = SkillCatalog()
        self.role = SkillCatalog(ROOT / "skills" / role)

    def list(self, role: Role = "analyst"):
        return self.role.list(role) + self.common.list(role)

    def load(self, name, role: Role = "analyst"):
        catalog = self.role if name in {s["name"] for s in self.role.list(role)} else self.common
        return catalog.load(name, role)

    def read_resource(self, name, path, role: Role = "analyst"):
        catalog = self.role if name in {s["name"] for s in self.role.list(role)} else self.common
        return catalog.read_resource(name, path, role)

    def review_skill(self):
        guidance = self.common.review_skill()
        guidance["instructions"] += "\n\n" + "\n\n".join(
            self.role.load(s["name"])["instructions"] for s in self.role.list()
        )
        guidance["sha256"] = hashlib.sha256(guidance["instructions"].encode()).hexdigest()
        return guidance


class MethodStore:
    """Versioned method-only examples; no runtime SQL requirement for delegation."""

    def __init__(self, role, enabled):
        from retail_agent.config import repository_root

        self.path = repository_root() / "knowledge/golden" / role / "methods.json"
        self.examples = (
            json.loads(self.path.read_text()).get("examples", [])
            if enabled and self.path.exists()
            else []
        )
        for example in self.examples:
            example.setdefault("revision", 1)

    def list_examples(self, offset=0, limit=20):
        if offset < 0 or not 1 <= limit <= 20:
            raise ValueError("Invalid page")
        page = self.examples[offset : offset + limit]
        return {
            "status": "ok",
            "examples": [{"id": x["id"], "description": x["description"]} for x in page],
            "next_offset": offset + limit if offset + limit < len(self.examples) else None,
            "warning": "Synthetic method examples, not evidence of current facts.",
        }

    def read(self, example_id):
        for entry in self.examples:
            if entry["id"] == example_id:
                return {"status": "ok", "example": entry}
        return {"status": "not_found"}


class RoleAnalyst(Analyst):
    maps: MapsClient

    def observe(self, event, **fields):
        if contains_maps(fields) or contains_maps(self.results):
            self.observation_mode = "metadata"
        super().observe(event, **fields)

    def __init__(
        self,
        role,
        *args,
        client=None,
        persist_budget=lambda value: None,
        as_of=None,
        snapshot_at=None,
        **kwargs,
    ):
        self.role = role
        self.prompt_span_name = f"{role}.prompt"
        self.agent_name = f"{role}_analyst" if role != "coordinator" else "retail_coordinator"
        self.client, self.persist_budget = client, persist_budget
        self.as_of, self.snapshot_at = as_of, snapshot_at
        self.children = {}
        self.observations: list[dict] = []
        self.child_slots = asyncio.Semaphore(2)
        if role in {"distribution", "coordinator"}:
            kwargs.setdefault("screener", lambda text: screen_role_text(text, self))
        super().__init__(*args, **kwargs)
        if role != "retail":
            self.skills = RoleSkills(role)
            self.knowledge = MethodStore(role, self.settings.golden_bootstrap)

    def new_budget(self):
        self.current_budget = PersistentBudget(self.settings, self.persist_budget)
        return self.current_budget

    def extra_context(self):
        return {
            "agent_role": self.role,
            "business_as_of": self.as_of,
            "warehouse_snapshot_at": self.snapshot_at,
        }

    def prompt_spec(self):
        spec = super().prompt_spec()
        if self.role == "retail":
            return spec
        path = ROOT / "prompts" / f"{self.role}.md"
        return replace(
            spec,
            name=f"retail-{self.role}",
            instruction=(ROOT / "prompts/common.md").read_text() + "\n\n" + path.read_text(),
            sources=(str(path),),
        )

    def build_tools(self, turn):
        if self.role == "retail":
            return super().build_tools(turn)
        data, knowledge, reports = DataTools(turn), KnowledgeTools(turn), ReportTools(turn)
        skills, completion = SkillTools(turn), RoleCompletionTools(turn)
        tools = [
            skills.load_skill,
            skills.load_skill_resource,
            knowledge.list_golden,
            knowledge.read_golden,
            data.read_result,
            data.analyze_results,
            reports.read_answer,
            reports.search_reports,
            reports.read_report,
            reports.stage_report_save,
            completion.finish_answer,
        ]
        adapter = DomainTools(turn)
        if self.role == "coordinator":
            delegation = DelegationTools(turn)
            tools.extend([delegation.list_agents, delegation.delegate])
        else:
            tools.extend([data.describe_data, adapter.query_data])
        if self.role == "distribution":
            tools.extend([adapter.describe_maps, adapter.call_maps])
        return tools


class DomainTools:
    def __init__(self, turn):
        self.turn = turn

    async def query_data(self, sql: str, purpose: str, parameters_json: str = "{}") -> dict:
        """Execute read-only BigQuery SQL over authorized relations from describe_data."""
        return await DataTools(self.turn).query_data(sql, purpose, parameters_json)

    async def describe_maps(self) -> dict:
        """Discover available Google Maps MCP tool schemas and capability limits."""

        async def describe():
            return await self.turn.app.maps.describe()

        return await self.turn.run_tool("describe_maps", describe)

    async def call_maps(self, tool_name: str, arguments_json: str, purpose: str) -> dict:
        """Call an allowed Maps MCP tool using its discovered schema; never confirms delivery."""

        async def call():
            arguments = json.loads(arguments_json)
            if self.turn.app.maps.available:
                # Configured conservative allowance, not a promise about vendor billing.
                self.turn.budget.reserve(0.01)
            result = await self.turn.app.maps.call(
                tool_name, arguments, timeout=min(20, self.turn.budget.work_remaining())
            )
            if result.get("status") not in ("ok", "empty"):
                return result
            return self.turn.artifact(result, purpose)

        return await self.turn.run_tool("call_maps", call, tool_name + arguments_json)


class RoleCompletionTools(CompletionTools):
    async def finish_answer(
        self, markdown: str, evidence_ids: list[str], outcome: str, tool_context: ToolContext
    ) -> dict:
        """Submit complete Markdown for review; Maps-derived content remains ephemeral."""
        if self.turn.pending_save and contains_maps(self.turn.app.results):
            self.turn.pending_save = None
            return {
                "status": "revise",
                "message": "Maps-derived content cannot be stored in reports with this integration. The save was cancelled; explain that limitation and submit the answer without claiming a saved report.",
            }
        return await super().finish_answer(markdown, evidence_ids, outcome, tool_context)


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
