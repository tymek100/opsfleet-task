"""BigQuery client is the fake boundary; scoping, job policy and recovery are real."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import Conflict

from retail_agent.services.warehouse import DataError, QueryGateway


def client_with_rows():
    client = MagicMock()
    rows = MagicMock(total_rows=1)
    rows.schema = [SimpleNamespace(name="revenue")]
    rows.__iter__.side_effect = lambda: iter([{"revenue": 65.65}])
    job = MagicMock(total_bytes_processed=80, job_id="external-job")
    job.result.return_value = rows
    return client, job


async def test_dry_run_cap_rejects_before_billable_submission():
    gateway = QueryGateway(("Calvin Klein",), project="offline-project", max_bytes=100)
    gateway._client = client = MagicMock()
    client.query.return_value.total_bytes_processed = 101
    with pytest.raises(DataError) as error:
        await gateway.query("SELECT SUM(sale_price) revenue FROM sales")
    assert error.value.code == "limit_reached"
    assert client.query.call_count == 1
    assert client.query.call_args.kwargs["job_config"].dry_run is True


async def test_scope_billing_and_read_limits_are_enforced_at_client_boundary():
    gateway = QueryGateway(("Calvin Klein",), project="offline-project", max_bytes=500, row_limit=7)
    client, job = client_with_rows()
    gateway._client = client
    client.query.side_effect = [SimpleNamespace(total_bytes_processed=100), job]
    result = await gateway.query("SELECT SUM(sale_price) revenue FROM sales")
    assert result["rows"] == [{"revenue": 65.65}]
    actual = client.query.call_args
    config = actual.kwargs["job_config"]
    assert config.maximum_bytes_billed == 500
    assert config.query_parameters[0].values == ["Calvin Klein"]
    assert actual.kwargs["retry"] is None and actual.kwargs["job_retry"] is None
    assert "@__scope_brands" in actual.args[0]
    assert job.result.call_args.kwargs["max_results"] == 7
    assert job.result.call_args.kwargs["page_size"] == 7


async def test_retries_recover_same_job_only_within_one_prompt():
    gateway = QueryGateway(("Calvin Klein",), project="offline-project")
    client, job = client_with_rows()
    gateway._client = client
    dry = SimpleNamespace(total_bytes_processed=100)
    client.query.side_effect = [dry, job, dry, Conflict("already submitted"), dry, job]
    client.get_job.return_value = job
    sql = "SELECT SUM(sale_price) revenue FROM sales"
    gateway.begin_turn()
    await gateway.query(sql)
    await gateway.query(sql)
    first = client.query.call_args_list[1].kwargs["job_id"]
    assert client.query.call_args_list[3].kwargs["job_id"] == first
    assert client.get_job.call_args.args == (first,)
    gateway.begin_turn()
    await gateway.query(sql)
    assert client.query.call_args_list[5].kwargs["job_id"] != first
