"""Explicit catalog of deployable agent implementations."""

from retail_insight.agents.coordinator.agent import CoordinatorAnalyst
from retail_insight.agents.distribution.agent import DistributionAnalyst
from retail_insight.agents.inventory.agent import InventoryAnalyst
from retail_insight.agents.retail.agent import RetailAnalyst

AGENTS = {
    "retail": RetailAnalyst,
    "inventory": InventoryAnalyst,
    "distribution": DistributionAnalyst,
    "coordinator": CoordinatorAnalyst,
}


def create_agent(role: str, *args, **kwargs):
    try:
        implementation = AGENTS[role]
    except KeyError:
        raise ValueError(f"Unknown agent role: {role}") from None
    return implementation(*args, **kwargs)
