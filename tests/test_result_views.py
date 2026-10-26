"""Distinguishing evidence fixtures for relational follow-ups and their runtime boundary."""

import json

import pytest
from pydantic import ValidationError

from retail_agent.agent import Analyst
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, Analysis, Answer, AppError, Dimension, Evidence
from retail_agent.planning import TurnPlan
from retail_agent.reports import ReportStore
from retail_agent.result_views import ViewPlan, evaluate_view, render_view, result_sources
from tests.fixture_data import FixtureExecutor
from tests.test_planning import Provider


@pytest.fixture
def rankings() -> Answer:
    evidence: list[Evidence] = []
    for eid, metric, values in [
        ("E1", "revenue", [(1, 300, 1), (2, 200, 2), (3, 100, 4)]),
        ("E2", "customers", [(3, 100, 4), (4, 90, 3), (2, 200, 2)]),
    ]:
        evidence.append(
            Evidence(
                id=eid,
                request=Analysis.model_validate(
                    {
                        "start": "2025-04-01",
                        "end": "2025-07-01",
                        "dimension": "product",
                        "rank_by": metric,
                        "limit": 3,
                    }
                ),
                scope="Calvin Klein",
                definitions="fixture",
                job_id="fixture",
                sql_hash="fixture",
                bytes_processed=0,
                queried_at="2025-07-01T00:00:00Z",
                rows=[
                    {
                        "product_id": i,
                        "product_name": f"Product {i}",
                        "revenue": revenue,
                        "customers": customers,
                        "orders": 2,
                        "units": 3,
                    }
                    for i, revenue, customers in values
                ],
            )
        )
    return Answer(text="rankings", evidence=evidence, trace_id="fixture")


def plan(operation: str = "intersection", **changes: object) -> ViewPlan:
    return ViewPlan.model_validate(
        {
            "sources": ["E1", "E2"],
            "operation": operation,
            "columns": ["product_id", "product_name"],
            **changes,
        }
    )


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("intersection", [2, 3]),
        ("difference", [1]),
        ("union", [1, 2, 3, 4]),
    ],
)
def test_set_operations_use_entity_keys_not_rank_or_names(
    rankings: Answer, operation: str, expected: list[int]
) -> None:
    sources = result_sources(rankings, DEMO_USERS["alice"])
    view = evaluate_view(plan(operation), sources)
    assert [r["product_id"] for r in view.rows] == expected
    if operation == "union":
        assert view.rows[-1]["E1.revenue"] is None
        assert view.rows[-1]["E2.revenue"] == 90


def test_followup_preserves_subset_and_source_metrics(rankings: Answer) -> None:
    rankings.view = evaluate_view(plan(), result_sources(rankings, DEMO_USERS["alice"]))
    followup = plan(
        "select",
        sources=["result"],
        columns=["product_id", "E1.rank", "E2.rank", "E1.revenue_per_order"],
        sort_by="E1.revenue",
        descending=False,
    )
    view = evaluate_view(followup, result_sources(rankings, DEMO_USERS["alice"]))
    assert [r["product_id"] for r in view.rows] == [3, 2]
    assert view.rows[0]["E1.rank"] == 3 and view.rows[0]["E2.rank"] == 1
    assert view.rows[0]["E1.revenue_per_order"] == 50
    assert "Top 3" not in render_view(followup, view, rankings)
    assert "50.00" in render_view(followup, view, rankings)


def test_filters_count_empty_and_no_invented_zero(rankings: Answer) -> None:
    p = plan(
        "select",
        sources=["E1"],
        filters=[{"column": "E1.revenue", "operator": "gt", "value": 300}],
        output="count",
    )
    view = evaluate_view(p, result_sources(rankings, DEMO_USERS["alice"]))
    assert not view.rows
    assert "**0 products match" in render_view(p, view, rankings)
    p.output = "table"
    assert "No matching products" in render_view(p, view, rankings)
    p.filters = []
    p.columns = ["product_id", "E1.orders"]
    p.sort_by = "E1.revenue"
    p.descending = False
    p.limit = 2
    assert [
        r["product_id"]
        for r in evaluate_view(p, result_sources(rankings, DEMO_USERS["alice"])).rows
    ] == [3, 2]


@pytest.mark.parametrize(
    "changes",
    [
        {"sources": ["E99", "E2"]},
        {"columns": ["email"]},
        {"sort_by": "ip_address"},
        {"filters": [{"column": "E1.revenue", "operator": "gt", "value": "expensive"}]},
        {"sources": ["E1", "E1"]},
        {"sources": ["E1"]},
    ],
)
def test_invalid_views_fail_closed(rankings: Answer, changes: dict[str, object]) -> None:
    with pytest.raises(AppError):
        evaluate_view(
            plan("intersection", **changes), result_sources(rankings, DEMO_USERS["alice"])
        )


def test_incompatible_grains_and_duplicate_entities_rejected(rankings: Answer) -> None:
    sources = result_sources(rankings, DEMO_USERS["alice"])
    sources["E2"].key = "user_id"
    with pytest.raises(AppError, match="grain"):
        evaluate_view(plan(), sources)
    sources = result_sources(rankings, DEMO_USERS["alice"])
    sources["E1"].rows.append(sources["E1"].rows[0])
    with pytest.raises(AppError, match="unique"):
        evaluate_view(plan(), sources)


def test_cached_sources_recheck_scope(rankings: Answer) -> None:
    rankings.evidence[0].request = rankings.evidence[0].request.model_copy(
        update={"brands": ["Levi's"]}
    )
    with pytest.raises(AppError):
        result_sources(rankings, DEMO_USERS["alice"])


def test_route_cannot_mix_view_with_analytics_or_mutations() -> None:
    with pytest.raises(ValidationError):
        TurnPlan(route="analysis", view=plan())
    with pytest.raises(ValidationError):
        TurnPlan.model_validate(
            {
                "route": "result_view",
                "view": plan().model_dump(),
                "operations": [{"operation": "save"}],
            }
        )


@pytest.mark.asyncio
async def test_runtime_reuses_evidence_repairs_bad_reference_and_saves_view(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    store: ReportStore,
    rankings: Answer,
) -> None:
    provider = Provider(
        monkeypatch,
        [
            {"route": "result_view", "view": plan(columns=["made_up"]).model_dump()},
            {"route": "result_view", "view": plan().model_dump()},
            {"route": "save", "title": "Overlap"},
        ],
    )
    executor = FixtureExecutor()
    analyst = Analyst(settings, DEMO_USERS["alice"], executor, store, "views")

    def no_query(*args: object, **kwargs: object) -> None:
        pytest.fail("A result-only follow-up must not query BigQuery")

    monkeypatch.setattr(executor, "execute", no_query)
    analyst.last_answer = rankings
    answer = await analyst.ask("Which occur in both?")
    assert answer.view and len(answer.view.rows) == 2
    assert answer.evidence == rankings.evidence
    assert len(provider.requests) == 2
    parts = provider.requests[0].contents[0].parts
    assert parts is not None
    payload = json.loads(parts[0].text or "{}")
    assert "result_sources" in payload
    await analyst.ask("Save it as Overlap")
    saved = store.read("alice", store.list("alice")[0].id)
    assert saved.view == answer.view and saved.text == answer.text


def test_text_filters_and_other_entity_grains(rankings: Answer) -> None:
    filtered = evaluate_view(
        plan(filters=[{"column": "product_name", "operator": "eq", "value": "Product 2"}]),
        result_sources(rankings, DEMO_USERS["alice"]),
    )
    assert [r["product_id"] for r in filtered.rows] == [2]
    for item in rankings.evidence:
        item.request = item.request.model_copy(update={"dimension": Dimension.CUSTOMER})
        for row in item.rows:
            row["user_id"] = row.pop("product_id")
    view = evaluate_view(
        plan(columns=["user_id", "E1.orders"]), result_sources(rankings, DEMO_USERS["alice"])
    )
    assert [r["user_id"] for r in view.rows] == [2, 3]
    assert "product_name" not in view.columns


@pytest.mark.asyncio
async def test_empty_filtered_sales_is_valid_without_narrative_retry(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    store: ReportStore,
) -> None:
    from retail_agent.bigquery import QueryResult
    from tests.test_planning import analytical_plan

    provider = Provider(
        monkeypatch,
        [
            analytical_plan(
                product_ids=[8252, 23740],
                requirements=[{"dimension": "product", "metric": "revenue"}],
            )
        ],
    )
    executor = FixtureExecutor()

    def empty_query(*args: object) -> QueryResult:
        return QueryResult([], "empty", 0)

    monkeypatch.setattr(executor, "execute", empty_query)
    analyst = Analyst(settings, DEMO_USERS["alice"], executor, store, "empty")
    answer = await analyst.ask("Show those products in Q3.")
    assert answer.quality_status == "validated"
    assert "No qualifying sales" in answer.text and "8252" in answer.text
    assert "could not be validated" not in answer.text
    assert len(provider.requests) == 1


def test_empty_narrative_cannot_omit_nonempty_evidence(rankings: Answer) -> None:
    from retail_agent.quality import Narrative, validate_narrative

    assert "missing_fact_metrics" in validate_narrative(Narrative(facts=[]), rankings.evidence)


def test_first_table_exposes_displayed_columns_and_preserves_selected_view(
    rankings: Answer,
) -> None:
    from retail_agent.models import Intent

    rankings.intent = Intent.model_validate(
        {
            "period": {"start": "2025-04-01", "end": "2025-07-01"},
            "requirements": [
                {"dimension": "product", "metric": "revenue", "minimum_rows": 3},
                {"dimension": "product", "metric": "customers", "minimum_rows": 3},
            ],
        }
    )
    sources = result_sources(rankings, DEMO_USERS["alice"])
    assert sources["E1"].displayed_columns == [
        "E1.rank",
        "product_id",
        "product_name",
        "E1.revenue",
    ]
    assert sources["E2"].displayed_columns == [
        "E2.rank",
        "product_id",
        "product_name",
        "E2.customers",
    ]
    assert "E1.revenue_per_order" in sources["E1"].columns
    assert "E1.revenue_per_order" not in sources["E1"].displayed_columns
    rankings.view = evaluate_view(plan(), sources)
    assert result_sources(rankings, DEMO_USERS["alice"])["result"].displayed_columns == [
        "product_id",
        "product_name",
    ]


@pytest.mark.parametrize(
    ("offset", "limit", "ids"),
    [
        (0, 1, [2]),
        (1, 1, [3]),
        (-1, 1, [1]),
        (1, 2, [3, 1]),
        (3, 1, []),
        (10, 1, []),
        (-10, 1, []),
    ],
)
def test_positions_follow_display_order_not_original_rank(
    rankings: Answer, offset: int, limit: int, ids: list[int]
) -> None:
    rankings.evidence[0].rows[0]["orders"] = 10
    order = plan("select", sources=["E1"], sort_by="E1.revenue_per_order", descending=True)
    rankings.view = evaluate_view(order, result_sources(rankings, DEMO_USERS["alice"]))
    assert [r["product_id"] for r in rankings.view.rows] == [2, 3, 1]
    selection = plan("select", sources=["result"], offset=offset, limit=limit)
    view = evaluate_view(selection, result_sources(rankings, DEMO_USERS["alice"]))
    assert [r["product_id"] for r in view.rows] == ids
    assert [r["product_id"] for r in rankings.evidence[0].rows] == [1, 2, 3]
    assert [r["product_id"] for r in rankings.view.rows] == [2, 3, 1]


def test_single_month_is_conversational_with_only_used_source(rankings: Answer) -> None:
    from retail_agent.render import render_answer

    monthly = rankings.evidence[1]
    monthly.request = monthly.request.model_copy(update={"dimension": Dimension.MONTH})
    monthly.rows = [{"month": "2025-08", "revenue": 3483.52, "orders": 20, "units": 25}]
    selection = ViewPlan(sources=["E2"], operation="select", columns=["month", "E2.revenue"])
    view = evaluate_view(selection, result_sources(rankings, DEMO_USERS["alice"]))
    text = render_view(selection, view, rankings)
    assert "2025" in text and "3,483.52" in text
    assert "[E2]" not in text and "[E1]" not in text
    result = rankings.model_copy(update={"view": view, "text": text})
    assert "3,483.52" in render_answer(result)
    assert "Verified findings" not in render_answer(result)
    assert "[E1]" in render_answer(result, details=True)
    assert len(result.evidence) == 2
    selection.sources = ["result"]
    repeated = evaluate_view(selection, result_sources(result, DEMO_USERS["alice"]))
    assert repeated.source_ids == ["E2"]
    assert render_view(selection, repeated, result) == text
    selection.output = "table"
    table = evaluate_view(selection, result_sources(result, DEMO_USERS["alice"]))
    rendered = render_view(selection, table, result)
    assert "| Month | Revenue |" in rendered
    assert "[E2]" not in rendered
    assert "[E1]" not in rendered


def test_single_product_keeps_all_sources_needed_for_set_membership(rankings: Answer) -> None:
    selection = plan("difference")
    view = evaluate_view(selection, result_sources(rankings, DEMO_USERS["alice"]))
    text = render_view(selection, view, rankings)
    assert "Product 1" in text and "[E1]" not in text and "[E2]" not in text
    assert view.source_ids == ["E1", "E2"]
    assert "| Product ID | Product |" in text


@pytest.mark.asyncio
async def test_explanation_uses_saved_operations_and_arithmetic_without_queries(
    rankings: Answer, settings: Settings, store: ReportStore, monkeypatch: pytest.MonkeyPatch
) -> None:

    selection = plan(
        "select",
        sources=["E1"],
        columns=["product_name", "E1.revenue_per_order", "E1.customers"],
        sort_by="E1.revenue_per_order",
        descending=True,
        limit=1,
    )
    view = evaluate_view(selection, result_sources(rankings, DEMO_USERS["alice"]))
    rankings.view = view
    provider = Provider(
        monkeypatch,
        [
            {"route": "explain_result"},
            {
                "text": "I compared {{selection.count}} products and selected the highest revenue per order. For {{E1.r0.product_name}}, {{E1.r0.revenue}} divided by {{E1.r0.orders}} gives {{E1.r0.revenue_per_order}}. No new database query was needed.",
                "metric_ids": [
                    "selection.count",
                    "E1.r0.revenue",
                    "E1.r0.orders",
                    "E1.r0.revenue_per_order",
                ],
            },
            {"supported": True, "relevant": True, "safe": True},
        ],
    )
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "explanation")
    analyst.last_answer = rankings
    answer = await analyst.ask("How did you find this information?")
    assert "3 products" in answer.text and "highest" in answer.text
    assert r"300\.00 divided by 2 gives 150\.00" in answer.text
    assert "[E1]" not in answer.text and "[E2]" not in answer.text
    assert "no new database query" in answer.text.lower()
    assert "offset" not in answer.text and "select operation" not in answer.text
    assert analyst.last_answer is rankings
    assert len(provider.requests) == 3 and not store.list("alice")


def test_winner_reply_is_natural_and_names_the_source(rankings: Answer) -> None:
    selection = plan(
        "select",
        sources=["E1"],
        columns=["product_name", "E1.revenue_per_order", "E1.orders"],
        sort_by="E1.revenue_per_order",
        limit=1,
    )
    view = evaluate_view(selection, result_sources(rankings, DEMO_USERS["alice"]))
    text = render_view(selection, view, rankings)
    assert "150.00" in text and "Orders" in text
    assert "from BigQuery" not in text and "[E1]" not in text
    assert "orders was" not in text
    selection.offset = 1
    second = evaluate_view(selection, result_sources(rankings, DEMO_USERS["alice"]))
    assert "highest" not in render_view(selection, second, rankings)


@pytest.mark.parametrize("rejection", ["invented_number", "unsupported_relationship"])
@pytest.mark.asyncio
async def test_llm_explanation_fails_closed_without_canned_business_prose(
    rankings: Answer,
    settings: Settings,
    store: ReportStore,
    monkeypatch: pytest.MonkeyPatch,
    rejection: str,
) -> None:
    candidate = {
        "text": "Revenue was 999999."
        if rejection == "invented_number"
        else "{{E1.r0.product_name}} had the lowest revenue at {{E1.r0.revenue}}.",
        "metric_ids": ["E1.r0.revenue"],
    }
    provider = Provider(
        monkeypatch,
        [
            {"route": "explain_result"},
            candidate,
            {"supported": False, "relevant": True, "safe": True},
        ],
    )
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "rejection")
    analyst.last_answer = rankings
    result = await analyst.ask("How did you determine that?")
    assert "could not generate a verified explanation" in result.text
    assert "999999" not in result.text and "lowest revenue" not in result.text
    assert "select operation" not in result.text
    assert analyst.last_answer is rankings
    assert len(provider.requests) == (2 if rejection == "invented_number" else 3)
