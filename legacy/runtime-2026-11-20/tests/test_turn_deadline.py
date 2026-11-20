"""Exercise real ADK cancellation, including a stalled model and evaluator."""

import asyncio
import json
import time
from collections.abc import AsyncGenerator

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner

from retail_agent.agent import Analyst
from retail_agent.config import Settings
from retail_agent.evaluator import INSTRUCTION
from retail_agent.model import BoundedGemini
from retail_agent.models import DEMO_USERS, AppError
from retail_agent.reports import ReportStore
from tests.agent_script import Script, query, submit
from tests.fixture_data import FixtureExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["initial_model", "after_query", "evaluator"])
async def test_deadline_cancels_stalled_provider_and_preserves_evidence(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, stage: str
) -> None:
    # Short real deadline avoids a two-minute unit test; normal Settings validate >=5s.
    settings = settings.model_copy(
        update={"turn_timeout_seconds": 0.3, "model_min_interval_seconds": 0}
    )
    calls = 0
    cancelled = asyncio.Event()

    async def generate(
        model: BoundedGemini, request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        nonlocal calls
        del model, stream
        calls += 1
        if stage != "initial_model" and calls == 1:
            yield LlmResponse(content=query("SELECT SUM(sale_price) AS revenue FROM sales"))
        elif (
            stage == "evaluator"
            and request.config.model_dump(mode="json").get("system_instruction") != INSTRUCTION
        ):
            yield LlmResponse(content=submit("Revenue {{E1.r0.revenue}}. [E1]", "E1"))
        else:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    monkeypatch.setattr(BoundedGemini, "generate_content_async", generate)
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "deadline")
    started = time.monotonic()
    async with asyncio.timeout(2):
        if stage == "initial_model":
            with pytest.raises(AppError) as exc:
                await analyst.ask("Show revenue in Q1 2026.")
            assert exc.value.code == "deadline"
            assert "time limit" in str(exc.value)
        else:
            answer = await analyst.ask("Show revenue in Q1 2026.")
            assert answer.evaluation_status == "incomplete"
            assert answer.query_evidence and "deadline" in str(answer.warnings)
    assert time.monotonic() - started < 1.5
    assert cancelled.is_set() and not store.list("alice")
    events = [json.loads(s) for s in (settings.data_dir / "events.log").read_text().splitlines()]
    assert any(e.get("error") == "deadline" for e in events)


@pytest.mark.asyncio
async def test_runner_cleanup_cannot_leave_approved_answer_spinning(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    Script(monkeypatch, [submit("I can analyze your authorized retail data.")])
    cancelled = asyncio.Event()

    async def close(runner: Runner) -> None:
        del runner
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(Runner, "close", close)
    started = time.monotonic()
    async with asyncio.timeout(3):
        answer = await Analyst(
            settings, DEMO_USERS["alice"], FixtureExecutor(), store, "cleanup"
        ).ask("What can you analyze?")
    assert answer.evaluation_status == "approved" and cancelled.is_set()
    assert time.monotonic() - started < 2
