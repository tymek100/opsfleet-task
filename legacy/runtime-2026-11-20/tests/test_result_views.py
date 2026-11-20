"""Distinguishing evidence fixtures for relational follow-ups and their runtime boundary."""

import pytest
from pydantic import ValidationError

from retail_agent.models import DEMO_USERS, Analysis, Answer, AppError, Dimension, Evidence
from retail_agent.planning import TurnPlan
from retail_agent.result_views import ViewPlan, evaluate_view, render_view, result_sources


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
