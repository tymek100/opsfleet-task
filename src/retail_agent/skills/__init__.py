"""Versioned runtime guidance, separate from developer-only .agents/skills."""

from retail_agent.skills.catalog import SkillCatalog, SkillError

__all__ = ["SkillCatalog", "SkillError"]
