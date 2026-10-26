"""Bounded BigQuery adapter; no DataFrames or raw customer records cross it."""

from collections.abc import Iterable, Mapping
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date
from typing import Protocol, cast
from uuid import uuid4

from google.api_core import exceptions as cloud_errors
from google.api_core.retry import Retry
from google.cloud import bigquery

from retail_agent.budget import Budget
from retail_agent.models import AppError, Scalar
from retail_agent.observability import Trace
from retail_agent.privacy import safe_text
from retail_agent.queries import CompiledQuery, repair_sql_syntax


class QueryErrorDetails(Protocol):
    @property
    def errors(self) -> list[dict[str, object]]: ...


@dataclass
class QueryResult:
    rows: list[dict[str, Scalar]]
    job_id: str
    bytes_processed: int
    sql_hash: str = ""


class Executor(Protocol):
    def execute(self, query: CompiledQuery, budget: Budget, trace: Trace) -> QueryResult: ...


class BigQueryExecutor:
    def __init__(self, project: str) -> None:
        self.project = project
        self._client: bigquery.Client | None = None

    @property
    def client(self) -> bigquery.Client:
        # Report-library commands remain available without cloud credentials.
        if self._client is None:
            if not self.project:
                raise AppError(
                    "Set GOOGLE_CLOUD_PROJECT and configure application-default credentials."
                )
            self._client = bigquery.Client(project=self.project, location="US")
        return self._client

    def execute(self, query: CompiledQuery, budget: Budget, trace: Trace) -> QueryResult:
        budget.query()
        params: list[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter] = []
        for name, value in query.parameters.items():
            if isinstance(value, list):
                params.append(
                    bigquery.ArrayQueryParameter(
                        name, "INT64" if name == "product_ids" else "STRING", value
                    )
                )
            else:
                kind = (
                    "BOOL"
                    if isinstance(value, bool)
                    else "INT64"
                    if isinstance(value, int)
                    else "DATE"
                    if isinstance(value, date)
                    else "STRING"
                )
                params.append(bigquery.ScalarQueryParameter(name, kind, value))
        job_id = "retail_" + uuid4().hex
        trace.emit(
            "query_started", job_id=job_id, sql_hash=query.fingerprint, attempt=budget.queries
        )
        try:
            config = bigquery.QueryJobConfig(
                dry_run=True,
                use_query_cache=False,
                query_parameters=params,
                maximum_bytes_billed=budget.settings.max_query_bytes,
            )
            try:
                dry = self.client.query(
                    query.sql,
                    job_config=config,
                    retry=Retry(predicate=lambda _: False),
                    timeout=min(10, budget.remaining()),
                )
            except cloud_errors.BadRequest as exc:
                # Only a dry-run syntax rejection is eligible. Never repair auth,
                # missing columns, execution failures, or valid empty data.
                if not any(
                    item.get("reason") == "invalidQuery"
                    and str(item.get("message", "")).lstrip().startswith("Syntax error:")
                    for item in cast(QueryErrorDetails, exc).errors
                ):
                    raise
                original_hash = query.fingerprint
                query = repair_sql_syntax(query)
                budget.query()  # The single recovery shares the original deadline/cap.
                trace.emit(
                    "query_syntax_repair",
                    original_sql_hash=original_hash,
                    sql_hash=query.fingerprint,
                    attempt=1,
                )
                dry = self.client.query(
                    query.sql,
                    job_config=config,
                    retry=Retry(predicate=lambda _: False),
                    timeout=min(10, budget.remaining()),
                )
            if (dry.total_bytes_processed or 0) > budget.settings.max_query_bytes:
                raise AppError(
                    "Query exceeds the scan limit. Narrow the requested analysis.",
                    code="query_byte_limit",
                )
            config.dry_run = False
            config.use_query_cache = True
            config.labels = {"app": "retail-agent", "trace": trace.id}
            try:
                job = self.client.query(
                    query.sql,
                    job_config=config,
                    job_id=job_id,
                    retry=Retry(predicate=lambda _: False),
                    job_retry=None,
                    timeout=min(10, budget.remaining()),
                )
            except (
                cloud_errors.DeadlineExceeded,
                cloud_errors.ServiceUnavailable,
                cloud_errors.Conflict,
            ):
                # Never resubmit a possibly-running paid query under a new ID.
                recovered = self.client.get_job(
                    job_id,
                    retry=Retry(predicate=lambda _: False),
                    timeout=min(10, budget.remaining()),
                )
                if not isinstance(recovered, bigquery.QueryJob):
                    raise AppError("Unexpected recovered job type.") from None
                job = recovered
            try:
                result = job.result(
                    timeout=min(45, budget.remaining()), retry=None, job_retry=None, max_results=101
                )
            except (FutureTimeout, cloud_errors.DeadlineExceeded):
                self.client.cancel_job(job_id, retry=Retry(predicate=lambda _: False), timeout=5)
                raise AppError(
                    "BigQuery timed out; cancellation requested. Try a narrower period."
                ) from None
            rows: list[dict[str, Scalar]] = []
            for row in cast(Iterable[bigquery.Row], result):
                raw = cast(Mapping[str, object], dict(row.items()))
                if set(raw) != set(query.output_columns):
                    raise AppError("Unexpected query output was blocked.")
                safe: dict[str, Scalar] = {}
                for key, value in raw.items():
                    if value is None or isinstance(value, (bool, int, float)):
                        safe[key] = value
                    elif isinstance(value, str):
                        safe[key] = safe_text(value, limit=160)
                    else:
                        raise AppError("Unsupported result type was blocked.")
                rows.append(safe)
            if len(rows) > 100:
                raise AppError("Result exceeds the row limit.")
            processed = job.total_bytes_processed or 0
            trace.emit(
                "query_complete",
                job_id=job_id,
                rows=len(rows),
                bytes_processed=processed,
                bytes_billed=job.total_bytes_billed or 0,
                cached=bool(job.cache_hit),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]  # SDK property lacks return annotation.,
            )
            return QueryResult(rows, job_id, processed, query.fingerprint)
        except AppError:
            raise
        except cloud_errors.BadRequest:
            trace.emit("query_error", job_id=job_id, error="invalid_query")
            raise AppError(
                "BigQuery rejected the compiled query. No broader query was attempted. Check the trace or try another supported analysis.",
                code="invalid_query",
            ) from None
        except (cloud_errors.TooManyRequests, cloud_errors.ServiceUnavailable):
            trace.emit("query_error", job_id=job_id, error="temporarily_unavailable")
            raise AppError("BigQuery is temporarily unavailable. Try again shortly.") from None
        except Exception:
            trace.emit("query_error", job_id=job_id, error="provider_failure")
            raise AppError(
                "BigQuery failed. Check project, ADC permissions, and the trace ID."
            ) from None
