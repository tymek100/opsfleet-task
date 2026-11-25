"""Shared service state around the ADK loop; capabilities belong to agent modules."""

import asyncio
import json
from pathlib import Path

from retail_insight.integrations.maps.privacy import contains_maps
from retail_insight.runtime.analyst import Analyst
from retail_insight.runtime.budget import Budget
from retail_insight.runtime.domain_privacy import screen_role_text
from retail_insight.runtime.prompts import agent_prompt
from retail_insight.runtime.skills.catalog import AgentSkills


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


class MethodStore:
    """Versioned method-only examples; no runtime SQL requirement for delegation."""

    def __init__(self, role, enabled):
        from retail_insight.config import repository_root

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


class ServiceAnalyst(Analyst):
    role: str
    agent_directory: Path
    facility_coordinates_allowed = False

    def observe(self, event, **fields):
        if contains_maps(fields) or contains_maps(self.results):
            self.observation_mode = "metadata"
        super().observe(event, **fields)

    def __init__(
        self,
        *args,
        client=None,
        gateway_clock=None,
        persist_budget=lambda value: None,
        as_of=None,
        snapshot_at=None,
        **kwargs,
    ):
        self.client, self.persist_budget = client, persist_budget
        self.gateway_clock = gateway_clock
        self.as_of, self.snapshot_at = as_of, snapshot_at
        self.children = {}
        self.observations: list[dict] = []
        self.child_slots = asyncio.Semaphore(2)
        if self.facility_coordinates_allowed:
            kwargs.setdefault("screener", lambda text: screen_role_text(text, self))
        super().__init__(*args, **kwargs)

    def new_budget(self):
        self.current_budget = PersistentBudget(self.settings, self.persist_budget)
        return self.current_budget

    def extra_context(self):
        return {
            "agent_role": self.role,
            "business_as_of": self.as_of,
            "warehouse_snapshot_at": self.snapshot_at,
        }

    def build_skills(self):
        return AgentSkills(self.agent_directory / "skills")

    def build_knowledge(self):
        return MethodStore(self.role, self.settings.golden_bootstrap)

    def prompt_spec(self):
        assert self.model is not None, "Initialize the model before building its prompt"
        return agent_prompt(
            self.settings,
            name=f"retail-{self.role}",
            path=self.agent_directory / "prompt.md",
            model=self.model.model,
            common=Path(__file__).parent / "prompt.md",
        )
