"""Model-callable tools; services retain storage, query and authorization logic."""

from retail_agent.tools.registry import build_tools

__all__ = ["build_tools"]
