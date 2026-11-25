"""Explicit inventory agent capabilities and instructions."""

import os
from datetime import datetime
from pathlib import Path

from retail_insight.agents.inventory.tools import build_tools
from retail_insight.integrations.bigquery.domains import DomainGateway
from retail_insight.runtime.service import ServiceAnalyst


class InventoryAnalyst(ServiceAnalyst):
    role = "inventory"
    agent_name = "inventory_analyst"
    prompt_span_name = "inventory.prompt"
    agent_directory = Path(__file__).parent
    facility_coordinates_allowed = False

    def build_tools(self, turn):
        return build_tools(turn)

    def build_gateway(self, clock):
        return DomainGateway(
            role=self.role,
            brands=self.identity.brands,
            project=self.settings.google_cloud_project,
            backend=self.settings.backend,
            fixture_path=Path(os.environ["DOMAIN_FIXTURE_PATH"])
            if os.getenv("DOMAIN_FIXTURE_PATH")
            else None,
            max_bytes=self.settings.max_query_bytes,
            source_dataset=self.settings.warehouse_source_dataset,
            clock=self.gateway_clock or clock,
            snapshot_at=datetime.fromisoformat(self.snapshot_at) if self.snapshot_at else None,
        )
