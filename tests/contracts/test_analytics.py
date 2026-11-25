"""Distinguishing data checks semantic SQL behavior, not query-string similarity."""

from decimal import Decimal

import pytest

from retail_insight.integrations.bigquery.retail import (
    DataError,
    QueryGateway,
    analyze_results,
    compile_query,
)
from tests.support.warehouse import Q1


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM sales",
        "SELECT * FROM fixture_items",
        "SELECT * FROM users",
        "SELECT email FROM sales",
        "SELECT city FROM sales",
        "SELECT * FROM sales; SELECT 1",
        "SELECT * FROM read_csv_auto('/tmp/private.csv')",
        "SELECT * FROM EXTERNAL_QUERY('connection', 'select secret')",
        "WITH sales AS (SELECT 1) SELECT * FROM sales",
        "SELECT @@project_id",
        "SELECT * FROM `bigquery-public-data.thelook_ecommerce.order_items`",
    ],
)
def test_sql_cannot_escape_logical_read_only_boundary(sql):
    with pytest.raises(DataError):
        compile_query(sql, ("Calvin Klein",))


@pytest.mark.parametrize(
    "sql,parameters",
    [
        ("SELECT @missing", {}),
        ("SELECT 1", {"unused": 1}),
        ("SELECT * FROM sales", {"__scope_brands": ["Levi's"]}),
    ],
)
def test_parameters_cannot_override_authorization_or_hide_binding_errors(sql, parameters):
    with pytest.raises(DataError):
        compile_query(sql, ("Calvin Klein",), parameters)


async def test_money_item_order_customer_grains_and_half_open_period(gateway):
    result = await gateway.query(f"""SELECT SUM(sale_price) revenue, COUNT(*) items,
        COUNT(DISTINCT order_id) orders, COUNT(DISTINCT user_id) customers,
        SUM(sale_price)/COUNT(DISTINCT order_id) aov FROM sales WHERE {Q1}""")
    row = result["rows"][0]
    # Authored directly from four eligible purchases, including two in one order.
    expected = sum(map(Decimal, ["10.10", "20.20", "30.30", "5.05"]))
    assert Decimal(str(row["revenue"])) == expected == Decimal("65.65")
    assert (row["items"], row["orders"], row["customers"]) == (4, 3, 2)
    assert float(row["aov"]) == pytest.approx(float(expected / 3))
    assert result["scope"] == ["Calvin Klein"]


async def test_both_order_and_item_status_exclusions_remain_explicit(gateway):
    result = await gateway.query(f"""SELECT item_status, order_status, SUM(sale_price) revenue
        FROM transactions WHERE {Q1} GROUP BY item_status, order_status""")
    values = {
        (r["item_status"], r["order_status"]): Decimal(str(r["revenue"])) for r in result["rows"]
    }
    assert values == {
        ("Complete", "Complete"): Decimal("65.65"),
        ("Complete", "Cancelled"): Decimal("1000"),
        ("Complete", "Returned"): Decimal("2000"),
        ("Returned", "Complete"): Decimal("3000"),
        ("Cancelled", "Complete"): Decimal("4000"),
    }


async def test_scope_is_applied_before_lifetime_history_and_cohort_joins(gateway):
    result = await gateway.query(f"""WITH cohort AS (
        SELECT DISTINCT user_id FROM sales WHERE {Q1}
    ), history AS (
        SELECT user_id, MIN(purchased_at) first_purchase, SUM(sale_price) lifetime
        FROM sales GROUP BY user_id
    ) SELECT h.user_id, h.lifetime FROM history h JOIN cohort c USING(user_id)
      ORDER BY user_id""")
    assert [(r["user_id"], Decimal(str(r["lifetime"]))) for r in result["rows"]] == [
        (1, Decimal("60.60")),
        (2, Decimal("5.05")),
    ]


@pytest.mark.parametrize("brands,expected", [((), 0), (("Calvin Klein",), 4), (None, 6)])
async def test_explicit_reference_filter_controls_rows_even_without_sql_filter(
    warehouse_fixture, brands, expected
):
    query = QueryGateway(brands, backend="fixture", fixture_path=warehouse_fixture)
    result = await query.query(f"SELECT COUNT(*) n FROM sales WHERE {Q1}")
    assert result["rows"] == [{"n": expected}]


async def test_catalog_left_join_keeps_unsold_products_and_stable_ties(gateway):
    result = await gateway.query(f"""SELECT p.product_id, COUNT(DISTINCT s.user_id) customers
        FROM products p LEFT JOIN sales s ON p.product_id = s.product_id AND {Q1}
        GROUP BY p.product_id ORDER BY customers DESC, product_id ASC""")
    assert result["rows"] == [
        {"product_id": 11, "customers": 2},
        {"product_id": 12, "customers": 1},
        {"product_id": 13, "customers": 0},
    ]


async def test_truncated_rows_cannot_be_reaggregated_as_complete(gateway):
    gateway.row_limit = 2
    result = await gateway.query("SELECT * FROM sales ORDER BY item_id")
    assert result["truncated"] is True
    assert len(result["rows"]) == 2
    with pytest.raises(DataError):
        await analyze_results({"E1": result}, "SELECT COUNT(*) FROM E1")


async def test_local_analysis_uses_only_supplied_evidence(gateway):
    source = await gateway.query(f"SELECT product_id, sale_price FROM sales WHERE {Q1}")
    result = await analyze_results(
        {"E1": source},
        "SELECT product_id, SUM(sale_price) revenue FROM E1 GROUP BY product_id ORDER BY product_id",
    )
    assert [Decimal(str(row["revenue"])) for row in result["rows"]] == [
        Decimal("35.35"),
        Decimal("30.30"),
    ]
    for sql in ("SELECT * FROM sales", "SELECT * FROM read_csv_auto('/tmp/private')"):
        with pytest.raises(DataError):
            await analyze_results({"E1": source}, sql)


async def test_bound_parameter_text_cannot_inject_sql(gateway):
    value = "' OR TRUE; DELETE FROM products; --"
    result = await gateway.query(
        "SELECT COUNT(*) n FROM products WHERE product_name = @name", {"name": value}
    )
    assert result["rows"] == [{"n": 0}]
    assert (await gateway.query("SELECT COUNT(*) n FROM products"))["rows"] == [{"n": 3}]


@pytest.mark.parametrize("foreign_price", ["0.01", "99999999.99"])
async def test_foreign_brand_mutation_cannot_change_manager_aggregate(
    warehouse_fixture, foreign_price
):
    with warehouse_fixture.open("a") as stream:
        stream.write(
            f"UPDATE fixture_items SET sale_price = {foreign_price} WHERE product_id = 91;"
        )
    gateway = QueryGateway(("Calvin Klein",), backend="fixture", fixture_path=warehouse_fixture)
    result = await gateway.query(f"SELECT SUM(sale_price) revenue FROM sales WHERE {Q1}")
    assert Decimal(str(result["rows"][0]["revenue"])) == Decimal("65.65")


async def test_tied_revenue_is_stably_ranked_without_losing_unsold_catalog(warehouse_fixture):
    with warehouse_fixture.open("a") as stream:
        stream.write(
            "INSERT INTO fixture_items VALUES (20, 103, 2, 13, 30.30, '2026-02-01', 'Complete');"
        )
    gateway = QueryGateway(("Calvin Klein",), backend="fixture", fixture_path=warehouse_fixture)
    result = await gateway.query(f"""SELECT product_id, SUM(sale_price) revenue FROM sales
        WHERE {Q1} GROUP BY product_id ORDER BY revenue DESC, product_id ASC""")
    assert [r["product_id"] for r in result["rows"]] == [11, 12, 13]
    assert Decimal(str(result["rows"][1]["revenue"])) == Decimal(str(result["rows"][2]["revenue"]))


async def test_empty_period_produces_no_invented_aov_or_percentage_change(gateway):
    result = await gateway.query("""SELECT SUM(sale_price) revenue, COUNT(DISTINCT order_id) orders,
        SAFE_DIVIDE(SUM(sale_price), COUNT(DISTINCT order_id)) aov
        FROM sales WHERE purchased_at >= TIMESTAMP('2030-01-01')""")
    assert result["rows"] == [{"revenue": None, "orders": 0, "aov": None}]
