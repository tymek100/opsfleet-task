"""Runtime agents expose all brands; analytical filters remain explicit SQL."""

import pytest

from retail_insight.agents.registry import create_agent
from retail_insight.contracts import WORKSPACE_IDENTITY, Identity


@pytest.mark.parametrize("role", ["retail", "inventory", "distribution", "coordinator"])
async def test_agents_have_full_brand_access_without_persona_selection(settings, role):
    app = create_agent(role, settings)
    try:
        assert app.identity == WORKSPACE_IDENTITY
        assert app.identity.scope == "all brands"
        if role == "coordinator":
            # Full data access is provided through delegation, not a new warehouse tool.
            assert not hasattr(app.gateway, "query")
            return
        assert app.gateway.brands is None
        result = await app.gateway.query("SELECT DISTINCT brand FROM products ORDER BY brand")
        assert {row["brand"] for row in result["rows"]} == {"Calvin Klein", "Levi's"}
        filtered = await app.gateway.query(
            "SELECT DISTINCT brand FROM products WHERE brand = @brand", {"brand": "Levi's"}
        )
        assert filtered["rows"] == [{"brand": "Levi's"}]
    finally:
        app.reports.close()


def test_legacy_brand_context_cannot_reinstate_restrictions_or_change_report_owner(settings):
    legacy = Identity("archive-owner", ("Calvin Klein",))
    app = create_agent("retail", settings, legacy)
    try:
        assert app.identity.user_id == "archive-owner"
        assert app.identity.brands is None
        assert app.gateway.brands is None
        assert app.knowledge._brands is None
    finally:
        app.reports.close()
