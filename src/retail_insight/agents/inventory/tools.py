"""Inventory capabilities: scoped warehouse queries and shared analysis tools."""

from retail_insight.tools.analytics import DataTools
from retail_insight.tools.domain import DomainTools, common_tools


def build_tools(turn):
    data, domain = DataTools(turn), DomainTools(turn)
    return [*common_tools(turn), data.describe_data, domain.query_data]
