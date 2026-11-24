"""Domain authorization, time boundaries and Maps capability contracts."""

import datetime as dt
import json
from pathlib import Path

import pytest

from retail_agent.services.warehouse import DataError
from retail_agents.domains.maps import MapsClient, validate_maps_arguments
from retail_agents.domains.warehouse import DomainGateway, compile_domain_query

AS_OF = dt.datetime(2026, 4, 1, tzinfo=dt.UTC)


def gateway(role="inventory", brands=("Calvin Klein",)):
    return DomainGateway(role, brands, backend="fixture", clock=lambda: AS_OF)


@pytest.mark.asyncio
async def test_stock_scope_cost_and_exact_time_boundaries():
    result = await gateway().query("""SELECT COUNT(DISTINCT inventory_id) AS units,
      SUM(cost) AS known_cost, COUNT(cost) AS costed_units FROM stock""")
    assert result["rows"] == [{"units": 5, "known_cost": 97.5, "costed_units": 4}]
    assert result["as_of"] == AS_OF.isoformat()
    ids = await gateway().query("SELECT inventory_id FROM stock ORDER BY inventory_id")
    assert [r["inventory_id"] for r in ids["rows"]] == [9001, 9002, 9003, 9004, 9005]
    assert (await gateway(brands=()).query("SELECT COUNT(*) AS n FROM stock"))["rows"] == [{"n": 0}]
    assert (await gateway(brands=("Levi's",)).query("SELECT SUM(cost) AS cost FROM stock"))[
        "rows"
    ] == [{"cost": 99.99}]


@pytest.mark.asyncio
async def test_distribution_left_join_preserves_unknown_and_zero_centers():
    result = await gateway("distribution").query("""SELECT COALESCE(c.center_name, 'Unknown') AS center,
      COUNT(DISTINCT s.inventory_id) AS units FROM stock s LEFT JOIN centers c
      ON c.center_id = s.inventory_center_id GROUP BY center ORDER BY center""")
    assert result["rows"] == [
        {"center": "Demo Chicago", "units": 3},
        {"center": "Demo Memphis", "units": 1},
        {"center": "Unknown", "units": 1},
    ]
    zero = await gateway("distribution").query("""SELECT c.center_id, COUNT(s.inventory_id) AS units
      FROM centers c LEFT JOIN stock s ON s.inventory_center_id=c.center_id
      GROUP BY c.center_id ORDER BY c.center_id""")
    assert zero["rows"][-1] == {"center_id": 3, "units": 0}


@pytest.mark.asyncio
async def test_inventory_catalog_attribution_and_quality_remain_distinct():
    result = await gateway().query("""SELECT COUNT(*) AS mismatches FROM stock
      WHERE inventory_center_id <> catalog_center_id""")
    assert result["rows"] == [{"mismatches": 1}]
    quality = await gateway().query("""SELECT COUNTIF(created_at IS NULL) AS missing_created,
      COUNTIF(sold_at < created_at) AS invalid_chronology FROM inventory""")
    assert quality["rows"] == [{"missing_created": 1, "invalid_chronology": 1}]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM `bigquery-public-data.thelook_ecommerce.inventory_items`",
        "SELECT * FROM sales",
        "SELECT * FROM users",
        "DELETE FROM inventory",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM raw_inventory_items",
        "WITH stock AS (SELECT 1) SELECT * FROM stock",
        "SELECT * FROM inventory; SELECT 1",
    ],
)
def test_domain_sql_cannot_escape_logical_sources(sql):
    with pytest.raises(DataError):
        compile_domain_query(sql, ("Calvin Klein",), role="distribution", as_of=AS_OF)


def test_inventory_cannot_query_center_coordinates_and_scope_is_per_source():
    with pytest.raises(DataError):
        compile_domain_query("SELECT * FROM centers", None, role="inventory", as_of=AS_OF)
    compiled = compile_domain_query(
        "SELECT a.product_id FROM stock a JOIN inventory b USING(product_id)",
        ("Calvin Klein",),
        role="inventory",
        as_of=AS_OF,
    )
    assert compiled.count("@__scope_brands") == 2
    assert "product_distribution_center_id" in compiled


@pytest.mark.asyncio
async def test_maps_missing_credentials_never_returns_fabricated_facts():
    maps = MapsClient(api_key="")
    assert (await maps.describe())["status"] == "unavailable"
    result = await maps.call(
        "compute_routes", {"origin": {"address": "Chicago"}, "destination": {"address": "Memphis"}}
    )
    assert result["status"] == "unavailable"
    assert "result" not in result


@pytest.mark.parametrize(
    "tool,args",
    [
        ("search_places", {}),
        (
            "compute_routes",
            {
                "origin": "a",
                "destination": "b",
                "routing_preference": "ROUTING_PREFERENCE_TRAFFIC_AWARE_OPTIMAL",
            },
        ),
        (
            "compute_routes",
            {"origin": "a", "destination": "b", "intermediate_waypoints": [{}] * 11},
        ),
        ("compute_routes", {"origin": "a", "destination": "b", "travel_mode": "WALK"}),
        ("lookup_weather", {"location": "x", "capabilities": ["POLLEN"]}),
        ("lookup_weather", {"location": "x", "air_quality_options": {}}),
    ],
)
def test_maps_paid_capability_allowlist(tool, args):
    with pytest.raises(DataError):
        validate_maps_arguments(tool, args)


@pytest.mark.asyncio
async def test_maps_preserves_attribution_and_does_not_expose_credentials(monkeypatch):
    class Response:
        isError = False

        def model_dump(self, **kwargs):
            return {
                "structuredContent": {
                    "routes": [{"distanceMeters": 1234}],
                    "attribution": {"googleMapsLinks": ["https://maps.google.com/"]},
                }
            }

    async def request(*args):
        return Response()

    maps = MapsClient(api_key="private-test-key")
    monkeypatch.setattr(maps, "_request", request)
    result = await maps.call(
        "compute_routes", {"origin": {"address": "a"}, "destination": {"address": "b"}}
    )
    assert result["status"] == "ok"
    assert result["trace_content"] is False
    assert "googleMapsLinks" in json.dumps(result)
    assert "private-test-key" not in json.dumps(result)


@pytest.mark.asyncio
async def test_runtime_method_queries_match_their_separate_synthetic_fixture():
    root = Path(__file__).resolve().parents[2]
    for role in ("inventory", "distribution"):
        corpus = json.loads((root / "knowledge/golden" / role / "methods.json").read_text())
        assert len(corpus["examples"]) == 8
        assert corpus["provenance"]["human_reviewed"] is False
        results = {}
        for example in corpus["examples"]:
            if example["example_sql"]:
                results[example["id"]] = (await gateway(role).query(example["example_sql"]))["rows"]
        if role == "inventory":
            assert results["stock_age"] == [{"aged_units": 2}]
            assert results["historical_balance"] == [{"units": 4}]
        else:
            assert sum(row["products"] for row in results["nonadditive_products"]) == 4
            costs = {
                row["inventory_center_id"]: row["known_cost"] for row in results["center_cost"]
            }
            assert costs == {1: 11.25, 2: 86.25, None: None}
