import json
from pathlib import Path

import pytest

from retail_agent.agent import Analyst
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, AppError
from retail_agent.reports import ReportStore
from tests.fixture_data import FixtureExecutor
from tests.test_planning import Provider, analytical_plan


@pytest.mark.asyncio
async def test_failed_diagnostics_warn_on_nonanalytical_response(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    Provider(monkeypatch, [{"route": "capabilities"}])
    # A directory at the log path makes only the diagnostic file unavailable.
    (settings.data_dir / "events.log").mkdir()
    answer = await Analyst(
        settings, DEMO_USERS["alice"], FixtureExecutor(), store, "diagnostics"
    ).ask("What can you analyze?")
    assert any("Diagnostic file unavailable" in w for w in answer.warnings)
    assert answer.text and not answer.evidence


@pytest.mark.asyncio
async def test_failure_reports_phase_category_and_trace_without_question(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    Provider(monkeypatch, [analytical_plan()])
    settings.max_queries = 1
    settings.question_budget_usd = 0.000001
    with pytest.raises(AppError) as error:
        await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "budget").ask(
            "Show revenue for the first quarter of 2026"
        )
    assert error.value.code == "cost_limit" and "Trace:" in str(error.value)
    log = Path(settings.data_dir / "events.log").read_text()
    events = [json.loads(line) for line in log.splitlines()]
    failures = [e for e in events if e["event"] == "turn_failed"]
    assert failures[-1]["error"] == "cost_limit" and failures[-1]["phase"] == "planning"
    assert "Show revenue" not in log
