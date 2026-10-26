"""Additional display measures must not change the selected ranking population."""

import pytest

from retail_agent.intent import completion_issues, execution_requests, validate_contract
from retail_agent.models import DEMO_USERS, Answer, AppError, Dimension, Intent, Period, Requirement
from retail_agent.quality import Narrative, render_narrative, required_facts


@pytest.mark.parametrize(
    "dimension",
    [Dimension.PRODUCT, Dimension.CUSTOMER, Dimension.CATEGORY, Dimension.MONTH, Dimension.TOTAL],
)
def test_extra_measures_share_population_and_are_required(
    answer: Answer, dimension: Dimension
) -> None:
    source = answer.evidence[0].model_copy(deep=True)
    source.request = source.request.model_copy(update={"dimension": dimension})
    source.rows = [
        {
            "product_id": 42,
            "product_name": "Fixture product",
            "user_id": 9,
            "category": "Fixture category",
            "month": "2026-01",
            "revenue": 600,
            "orders": 4,
            "units": 12,
            "customers": 2,
        }
    ]
    intent = Intent(
        period=Period(start=source.request.start, end=source.request.end),
        requirements=[
            Requirement(
                dimension=dimension,
                metric="revenue",
                measures=["orders", "units", "customers", "revenue_per_order"],
            )
        ],
    )
    validate_contract(intent, DEMO_USERS["alice"])
    requests = execution_requests(intent)
    assert len(requests) == 1 and requests[0].rank_by == "revenue"
    facts = required_facts(intent, [source])
    assert set(facts) == {
        f"E1.r0.{m}" for m in ("revenue", "orders", "units", "customers", "revenue_per_order")
    }
    assert completion_issues(intent, [source], facts) == []
    assert completion_issues(intent, [source], [f for f in facts if not f.endswith("orders")])
    rendered = render_narrative(Narrative(facts=facts), [source], intent)
    assert "150" in rendered and "600" in rendered
    assert "orders" in rendered.lower() and "customers" in rendered.lower()


def test_separate_rankings_stay_separate_with_additional_columns(answer: Answer) -> None:
    source = answer.evidence[0]
    intent = Intent(
        period=Period(start=source.request.start, end=source.request.end),
        requirements=[
            Requirement(
                dimension=Dimension.PRODUCT, metric="units", measures=["revenue"], minimum_rows=5
            ),
            Requirement(
                dimension=Dimension.PRODUCT,
                metric="customers",
                measures=["revenue", "orders"],
                minimum_rows=5,
            ),
        ],
    )
    assert [(r.rank_by, r.limit) for r in execution_requests(intent)] == [
        ("units", 5),
        ("customers", 5),
    ]


def test_churn_cannot_request_sales_columns(answer: Answer) -> None:
    source = answer.evidence[0]
    intent = Intent(
        kind="churn",
        period=Period(start=source.request.start, end=source.request.end),
        requirements=[
            Requirement(dimension=Dimension.TOTAL, metric="inactivity_share", measures=["revenue"])
        ],
    )
    with pytest.raises(AppError, match="Sales measures"):
        validate_contract(intent, DEMO_USERS["alice"])


def test_provider_schema_simplification_preserves_local_bounds() -> None:
    from pydantic import ValidationError

    from retail_agent.planning import TurnPlan, provider_schema

    original = TurnPlan.model_json_schema()
    simplified = provider_schema(original)
    assert "maxItems" not in str(simplified)
    assert "maxItems" in str(original)
    assert "revenue_per_order" in str(simplified) and "enum" in str(simplified)
    with pytest.raises(ValidationError):
        Requirement(dimension=Dimension.PRODUCT, minimum_rows=51)
    with pytest.raises(ValidationError):
        Requirement(dimension=Dimension.PRODUCT, measures=["orders"] * 10)


def test_large_output_keeps_every_requested_fact(answer: Answer) -> None:
    product = answer.evidence[0].model_copy(deep=True)
    product.request = product.request.model_copy(
        update={"dimension": Dimension.PRODUCT, "limit": 20}
    )
    product.rows = [
        {
            "product_id": i,
            "product_name": f"Product {i}",
            "revenue": 600,
            "orders": 4,
            "units": 12,
            "customers": 2,
        }
        for i in range(20)
    ]
    monthly = product.model_copy(deep=True)
    monthly.id = "E2"
    monthly.request = monthly.request.model_copy(update={"dimension": Dimension.MONTH})
    monthly.rows = [
        {"month": f"2026-{i:02d}", "revenue": 100, "orders": 2, "customers": 2, "units": 3}
        for i in range(1, 13)
    ]
    intent = Intent(
        period=Period(start=product.request.start, end=product.request.end),
        requirements=[
            Requirement(
                dimension=Dimension.PRODUCT,
                minimum_rows=20,
                measures=["orders", "units", "customers", "revenue_per_order"],
            ),
            Requirement(dimension=Dimension.MONTH, measures=["orders", "customers"]),
        ],
    )
    evidence = [product, monthly]
    facts = required_facts(intent, evidence)
    assert len(facts) == 136
    narrative = Narrative(facts=facts)
    assert not completion_issues(intent, evidence, narrative.facts)
    text = render_narrative(narrative, evidence, intent)
    assert "Revenue per order" in text
    assert "| 20 | 19 | 600.00 | 4 | 12 | 2 | 150.00 |" in text
    assert "| 19 | Product 19 |" in text
    assert "| Month | Revenue | Orders | Distinct customers |" in text
