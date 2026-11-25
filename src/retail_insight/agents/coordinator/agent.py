"""Explicit coordinator agent capabilities and instructions."""

from pathlib import Path

from retail_insight.agents.coordinator.tools import build_tools
from retail_insight.runtime.service import ServiceAnalyst


class CoordinatorAnalyst(ServiceAnalyst):
    role = "coordinator"
    agent_name = "retail_coordinator"
    prompt_span_name = "coordinator.prompt"
    agent_directory = Path(__file__).parent
    facility_coordinates_allowed = True

    def build_tools(self, turn):
        return build_tools(turn)

    def build_gateway(self, clock):
        # Coordinator capabilities provide no direct warehouse access.
        return object()
