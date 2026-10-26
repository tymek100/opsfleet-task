"""Fresh population selection and post-query transformations are distinct operations."""

import pytest

from retail_agent.agent import Analyst
from retail_agent.bigquery import QueryResult
from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, AppError, Scalar
from retail_agent.observability import Trace
from retail_agent.queries import CompiledQuery
from retail_agent.reports import ReportStore
from tests.test_planning import Provider, analytical_plan


class CustomerPopulation:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, query: CompiledQuery, budget: Budget, trace: Trace) -> QueryResult:
        del trace
        self.calls += 1
        budget.query()
        assert "LIMIT 5" in query.sql
        rows: list[dict[str, Scalar]] = [
            {"user_id": i, "revenue": revenue, "orders": orders, "units": orders, "customers": 1}
            for i, revenue, orders in [
                (1, 1000, 100),
                (2, 900, 1),
                (3, 800, 4),
                (4, 700, 2),
                (5, 600, 6),
            ]
        ]
        return QueryResult(rows, "fixture", 0)


def compound_plan() -> dict[str, object]:
    plan = analytical_plan(
        requirements=[
            {
                "dimension": "customer",
                "metric": "revenue",
                "minimum_rows": 5,
                "measures": ["orders", "revenue_per_order"],
            }
        ]
    )
    plan["post_view"] = {
        "sources": ["E1"],
        "operation": "select",
        "columns": ["user_id", "E1.revenue", "E1.orders", "E1.revenue_per_order"],
        "sort_by": "E1.revenue_per_order",
        "descending": True,
        "limit": 3,
    }
    return plan


@pytest.mark.asyncio
async def test_compound_reranks_only_the_queried_population(
    settings: Settings,
    store: ReportStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = Provider(monkeypatch, [compound_plan()])
    executor = CustomerPopulation()
    analyst = Analyst(settings, DEMO_USERS["alice"], executor, store, "compound")
    answer = await analyst.ask(
        "Find the top five customers by revenue, add average order value, and keep the highest three within those five."
    )
    assert executor.calls == 1 and len(provider.requests) == 1
    assert answer.view and [row["user_id"] for row in answer.view.rows] == [2, 4, 3]
    assert len(answer.evidence[0].rows) == 5
    assert answer.evidence[0].request.rank_by == "revenue"
    assert "900.00" in answer.text and "350.00" in answer.text
    assert analyst.last_answer is answer and not store.list("alice")


@pytest.mark.asyncio
async def test_invalid_post_query_columns_fail_before_querying(
    settings: Settings,
    store: ReportStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = compound_plan()
    plan["post_view"] = {"sources": ["E1"], "operation": "select", "columns": ["email"]}
    Provider(monkeypatch, [plan, plan])
    executor = CustomerPopulation()
    with pytest.raises(AppError, match="valid plan"):
        await Analyst(settings, DEMO_USERS["alice"], executor, store, "invalid").ask(
            "Rank customers"
        )
    assert executor.calls == 0
