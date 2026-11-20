"""A fresh ranked population can be narrowed within the same agent loop."""

import pytest

from retail_agent.agent import Analyst
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS
from retail_agent.reports import ReportStore
from tests.agent_script import Script, query, submit, tool
from tests.fixture_data import FixtureExecutor


@pytest.mark.asyncio
async def test_compound_request_keeps_top_customer_population(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    Script(
        monkeypatch,
        [
            query("""SELECT user_id, SUM(sale_price) AS revenue,
                MAX(purchased_at) AS last_purchase
                FROM sales WHERE purchased_at >= '2026-01-01' AND purchased_at < '2026-04-01'
                GROUP BY user_id ORDER BY revenue DESC, user_id ASC LIMIT 3"""),
            tool(
                "select_result",
                evidence_id="E1",
                columns=[],
                sort_by="last_purchase",
                descending=True,
                limit=1,
            ),
            submit("The latest purchaser among those customers is {{E2.r0.user_id}}. [E2]", "E2"),
        ],
    )
    runtime = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "compound")
    result = await runtime.ask(
        "Among our top three customers by Q1 2026 revenue (ties by lowest ID), show the latest purchaser."
    )
    assert result.evaluation_status == "approved"
    assert [r["user_id"] for r in runtime.sources["E1"].rows] == [1, 2, 4]
    assert result.query_evidence[0].rows[0]["user_id"] == 4
    assert result.query_evidence[0].parent_ids == ["E1"]
    assert (settings.data_dir / "events.log").read_text().count('"event": "fixture_query"') == 1
