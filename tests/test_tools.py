from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from retail_insight.config import Settings
from retail_insight.tools.bigquery import BigQueryTools, validate_sql
from retail_insight.tools.skills import read_skill


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM products WHERE TRUE",
        "SELECT 1; SELECT 2",
        "CREATE TABLE test AS SELECT 1",
        "SELECT * FROM `another-project.private.products`",
        "SELECT * FROM users",
        "SELECT * FROM EXTERNAL_QUERY('connection', 'SELECT 1')",
        "SELECT `project.dataset.remote`(1)",
        "SELECT AI.GENERATE('test')",
        "EXPORT DATA OPTIONS(uri='gs://x/y', format='CSV') AS SELECT * FROM products",
        "WITH x AS (SELECT * FROM users) SELECT * FROM x",
    ],
)
def test_unsafe_queries_are_rejected(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_ctes_and_standard_analytics_use_only_public_tables():
    sql = validate_sql(
        "WITH totals AS (SELECT product_id, SUM(sale_price) revenue FROM order_items GROUP BY 1) SELECT p.name, t.revenue FROM totals t JOIN products p ON p.id=t.product_id ORDER BY revenue DESC LIMIT 5"
    )
    assert "bigquery-public-data" in sql and "thelook_ecommerce" in sql
    assert validate_sql("SELECT SAFE_DIVIDE(10, 2)") == "SELECT SAFE_DIVIDE(10, 2)"


async def test_query_has_server_cost_limit_and_explicit_truncation():
    client = Mock()
    client.query_and_wait.return_value = [{"id": i} for i in range(101)]
    tools = BigQueryTools(Settings(max_query_bytes=123456), client=client)
    result = await tools.query("SELECT id FROM products")
    options = client.query_and_wait.call_args.kwargs
    assert options["job_config"].maximum_bytes_billed == 123456
    assert int(options["job_config"].job_timeout_ms) == 30000
    assert options["wait_timeout"] == 30 and options["max_results"] == 101
    assert result["truncated"] and len(result["rows"]) == 100
    client.query_and_wait.reset_mock()
    assert "error" in await tools.query("DROP TABLE products")
    client.query_and_wait.assert_not_called()


async def test_schema_uses_actual_table_metadata():
    client = Mock()
    client.get_table.return_value = SimpleNamespace(
        schema=[SimpleNamespace(name="id", field_type="INTEGER")]
    )
    result = await BigQueryTools(Settings(), client=client).describe_tables()
    assert result["tables"]["products"] == [{"name": "id", "type": "INTEGER"}]
    assert len(client.get_table.call_args_list) == 3


async def test_skill_paths_are_allowlisted():
    assert "Revenue" in (await read_skill("sales-analysis"))["instructions"]
    assert "error" in await read_skill("../../.env")
