from unittest.mock import Mock

import pytest
from google.api_core import exceptions as errors
from google.cloud import bigquery

from retail_agent.bigquery import BigQueryExecutor
from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, Analysis, AppError
from retail_agent.observability import Trace
from retail_agent.queries import compile_query


def gateway(monkeypatch: pytest.MonkeyPatch) -> tuple[BigQueryExecutor, Mock, Mock, Mock]:
    client = Mock(spec=bigquery.Client)
    dry = Mock(spec=bigquery.QueryJob)
    dry.total_bytes_processed = 10_000_000
    job = Mock(spec=bigquery.QueryJob)
    job.total_bytes_processed = 10_000_000
    job.cache_hit = False
    client.query.side_effect = [dry, job]

    def client_factory(**_: object) -> Mock:
        return client

    monkeypatch.setattr(bigquery, "Client", client_factory)
    return BigQueryExecutor("offline"), client, dry, job


def test_dry_run_and_execution_limits(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    executor, client, _, job = gateway(monkeypatch)
    query = compile_query(
        Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01"}), DEMO_USERS["alice"]
    )
    job.result.return_value = [
        bigquery.Row(
            ["all", 100.0, 2, 1, 1, "2026-03-01"],
            dict(zip(query.output_columns, range(6), strict=True)),
        )
    ]
    result = executor.execute(query, Budget(settings), Trace())
    assert result.rows[0]["revenue"] == 100
    assert client.query.call_count == 2
    call = client.query.call_args
    assert call.kwargs["job_config"].maximum_bytes_billed == settings.max_query_bytes
    assert call.kwargs["job_retry"] is None
    assert call.kwargs["job_id"].startswith("retail_")


def test_oversized_query_never_executes(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    executor, client, dry, _ = gateway(monkeypatch)
    dry.total_bytes_processed = 10**12
    query = compile_query(
        Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01"}), DEMO_USERS["alice"]
    )
    with pytest.raises(AppError, match="scan limit"):
        executor.execute(query, Budget(settings), Trace())
    assert client.query.call_count == 1


def test_uncertain_submit_recovers_same_job_without_resubmit(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    executor, client, dry, job = gateway(monkeypatch)
    client.query.side_effect = [dry, errors.ServiceUnavailable("temporary")]
    client.get_job.return_value = job
    job.result.return_value = []
    query = compile_query(
        Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01"}), DEMO_USERS["alice"]
    )
    executor.execute(query, Budget(settings), Trace())
    assert client.query.call_count == 2
    assert client.get_job.call_args.args[0] == client.query.call_args.kwargs["job_id"]


def test_unexpected_source_fields_blocked(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    executor, _, _, job = gateway(monkeypatch)
    job.result.return_value = [bigquery.Row(["canary@example.test"], {"email": 0})]
    query = compile_query(
        Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01"}), DEMO_USERS["alice"]
    )
    trace = Trace()
    with pytest.raises(AppError, match="Unexpected query output"):
        executor.execute(query, Budget(settings), trace)
    assert "canary" not in str(trace.events)


def test_timeout_cancels_without_resubmission(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    executor, client, _, job = gateway(monkeypatch)
    job.result.side_effect = TimeoutError()
    query = compile_query(
        Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01"}), DEMO_USERS["alice"]
    )
    with pytest.raises(AppError, match="timed out"):
        executor.execute(query, Budget(settings), Trace())
    assert client.cancel_job.call_count == 1 and client.query.call_count == 2


def test_provider_error_content_not_exposed(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    executor, client, _, _ = gateway(monkeypatch)
    client.query.side_effect = errors.BadRequest("SQL contains canary@example.test")
    query = compile_query(
        Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01"}), DEMO_USERS["alice"]
    )
    trace = Trace()
    with pytest.raises(AppError) as info:
        executor.execute(query, Budget(settings), trace)
    assert "canary" not in str(info.value) and "canary" not in str(trace.events)


def test_syntax_recovery_keeps_scope_and_params(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    executor, client, dry, job = gateway(monkeypatch)
    syntax = errors.BadRequest(
        "not forwarded", errors=[{"reason": "invalidQuery", "message": "Syntax error: quoting"}]
    )
    client.query.side_effect = [syntax, dry, job]
    job.result.return_value = []
    query = compile_query(
        Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01", "product_ids": [123]}),
        DEMO_USERS["alice"],
    )
    trace = Trace()
    budget = Budget(settings)
    result = executor.execute(query, budget, trace)
    assert client.query.call_count == 3 and budget.queries == 2
    from retail_agent.queries import repair_sql_syntax

    repaired = repair_sql_syntax(query)
    assert repaired.parameters == query.parameters
    assert (
        repaired.definitions == query.definitions
        and repaired.output_columns == query.output_columns
    )
    assert client.query.call_args.args[0] == repaired.sql
    assert result.sql_hash == repaired.fingerprint != query.fingerprint
    assert any(e["event"] == "query_syntax_repair" for e in trace.events)
    assert (
        client.query.call_args.kwargs["job_config"].maximum_bytes_billed == settings.max_query_bytes
    )


def test_syntax_recovery_is_once_and_shares_budget(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    executor, client, _, _ = gateway(monkeypatch)
    client.query.side_effect = errors.BadRequest(
        "private provider body",
        errors=[{"reason": "invalidQuery", "message": "Syntax error: nope"}],
    )
    query = compile_query(
        Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01"}), DEMO_USERS["alice"]
    )
    with pytest.raises(AppError, match="BigQuery rejected"):
        executor.execute(query, Budget(settings), Trace())
    assert client.query.call_count == 2
    client.reset_mock()
    settings.max_queries = 1
    with pytest.raises(AppError, match="Query limit"):
        executor.execute(query, Budget(settings), Trace())
    assert client.query.call_count == 1


def test_schema_error_is_not_a_syntax_repair(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    executor, client, _, _ = gateway(monkeypatch)
    client.query.side_effect = errors.BadRequest(
        "private name", errors=[{"reason": "invalidQuery", "message": "Unrecognized name: gone"}]
    )
    query = compile_query(
        Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01"}), DEMO_USERS["alice"]
    )
    with pytest.raises(AppError) as error:
        executor.execute(query, Budget(settings), Trace())
    assert error.value.code == "invalid_query" and client.query.call_count == 1
