"""Retail agent composition, shared by the CLI and its A2A service."""

from datetime import datetime
from pathlib import Path

from retail_insight.agents.retail.tools import build_tools
from retail_insight.integrations.bigquery.retail import QueryGateway
from retail_insight.integrations.knowledge import GoldenStore
from retail_insight.runtime.prompts import analyst_prompt
from retail_insight.runtime.service import ServiceAnalyst
from retail_insight.runtime.skills import SkillCatalog


class RetailAnalyst(ServiceAnalyst):
    role = "retail"
    agent_name = "retail_analyst"
    prompt_span_name = "retail.prompt"
    agent_directory = Path(__file__).parent

    def prompt_spec(self):
        assert self.model is not None, "Initialize the model before building its prompt"
        return analyst_prompt(self.settings, model=self.model.model)

    def build_tools(self, turn):
        return build_tools(turn)

    def build_skills(self):
        return SkillCatalog()

    def build_knowledge(self):
        return GoldenStore(
            self.settings.golden_path,
            None,
            bootstrap=self.settings.golden_bootstrap,
        )

    def build_gateway(self, clock):
        return QueryGateway(
            brands=None,
            project=self.settings.google_cloud_project,
            backend=self.settings.backend,
            fixture_path=self.settings.fixture_path,
            max_bytes=self.settings.max_query_bytes,
            source_dataset=self.settings.warehouse_source_dataset,
            clock=self.gateway_clock or clock,
            snapshot_at=datetime.fromisoformat(self.snapshot_at) if self.snapshot_at else None,
        )
