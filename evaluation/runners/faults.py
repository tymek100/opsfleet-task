"""Faults at external boundaries, after normal SQL admission checks."""

from collections.abc import AsyncGenerator

import httpx
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from pydantic import PrivateAttr

from evaluation.models import Fault
from retail_agent.services.reports import ReportError, ReportStore
from retail_agent.services.warehouse import DataError, QueryGateway, compile_query


class Schedule:
    def __init__(self, faults: list[Fault]):
        self.faults = faults
        self.counts: dict[str, int] = {}

    def next(self, boundary: str) -> Fault | None:
        self.counts[boundary] = self.counts.get(boundary, 0) + 1
        return next(
            (
                f
                for f in self.faults
                if f.boundary == boundary and f.occurrence == self.counts[boundary]
            ),
            None,
        )


class FaultGateway(QueryGateway):
    schedule: Schedule

    async def query(self, sql: str, parameters: dict | None = None, timeout: float = 30) -> dict:
        compile_query(sql, self.brands, parameters)
        fault = self.schedule.next("query")
        if fault:
            raise DataError(fault.code, fault.message)
        return await super().query(sql, parameters, timeout)


class FaultReports(ReportStore):
    schedule: Schedule

    def save(self, *args, **kwargs) -> dict:
        fault = self.schedule.next("report_save")
        if fault:
            raise ReportError(fault.code, fault.message)
        return super().save(*args, **kwargs)


class FaultModel(BaseLlm):
    delegate: BaseLlm
    _schedule: Schedule = PrivateAttr()

    def bind(self, schedule: Schedule) -> "FaultModel":
        self._schedule = schedule
        return self

    @property
    def capabilities(self):
        return self.delegate.capabilities

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        fault = self._schedule.next("provider")
        if fault:
            # Unknown usage is deliberately retained by AccountedModel.
            raise httpx.ReadTimeout(fault.message)
        async for response in self.delegate.generate_content_async(llm_request, stream):
            yield response
