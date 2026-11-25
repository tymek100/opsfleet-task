"""Shared service state around the ADK loop; capabilities belong to agent modules."""

import asyncio
from pathlib import Path

from retail_insight.integrations.maps.privacy import contains_maps
from retail_insight.runtime.analyst import Analyst
from retail_insight.runtime.budget import Budget
from retail_insight.runtime.domain_privacy import screen_role_text
from retail_insight.runtime.prompts import agent_prompt
from retail_insight.runtime.skills.catalog import AgentSkills


class PersistentBudget(Budget):
    def __init__(self, settings, persist, *, review_prompt_bytes=0):
        super().__init__(settings, review_prompt_bytes=review_prompt_bytes)
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
        self.current_budget = PersistentBudget(
            self.settings, self.persist_budget, review_prompt_bytes=self.review_prompt_bytes()
        )
        return self.current_budget

    def extra_context(self):
        return {
            "agent_role": self.role,
            "business_as_of": self.as_of,
            "warehouse_snapshot_at": self.snapshot_at,
        }

    def build_skills(self):
        return AgentSkills(self.agent_directory / "skills")

    def prompt_spec(self):
        assert self.model is not None, "Initialize the model before building its prompt"
        return agent_prompt(
            self.settings,
            name=f"retail-{self.role}",
            path=self.agent_directory / "prompt.md",
            model=self.model.model,
            common=Path(__file__).parent / "prompt.md",
        )
