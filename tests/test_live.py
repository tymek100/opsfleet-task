"""Explicitly opt in: uv run pytest -m live --force-enable-socket -s tests/test_live.py."""

import logging
from pathlib import Path

import pytest

from retail_agent.agent import Analyst
from retail_agent.bigquery import BigQueryExecutor
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, Dimension
from retail_agent.reports import ReportStore

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


async def test_live_rankings_followup_and_churn(tmp_path: Path) -> None:
    settings = Settings.load()
    if not settings.gemini_api_key.get_secret_value() or not settings.google_cloud_project:
        pytest.skip("External credentials required")
    settings.data_dir = tmp_path
    logging.getLogger("google").setLevel(logging.CRITICAL)
    store = ReportStore(tmp_path / "live.sqlite3")
    analyst = Analyst(
        settings,
        DEMO_USERS["alice"],
        BigQueryExecutor(settings.google_cloud_project),
        store,
        "live",
    )
    try:
        ranking = await analyst.ask(
            "List the top 10 best sellers by revenue and by number of customers for Q1 2026."
        )
        assert {
            e.request.rank_by for e in ranking.evidence if e.request.dimension == Dimension.PRODUCT
        } >= {"revenue", "customers"}
        assert ranking.quality_status == "validated"
        assert all(len(e.rows) <= 50 for e in ranking.evidence)
        print("rankings:", len(ranking.evidence), "queries; reserve", ranking.estimated_cost_usd)
        followup = await analyst.ask(
            "For that same quarter, show total revenue and the monthly breakdown."
        )
        assert followup.quality_status == "validated"
        assert {e.request.dimension for e in followup.evidence} >= {
            Dimension.TOTAL,
            Dimension.MONTH,
        }
        assert all(e.request.start.year == 2026 for e in followup.evidence)
        print("follow-up:", len(followup.evidence), "queries; reserve", followup.estimated_cost_usd)
        # Fresh context keeps scenarios independent and prevents previous periods overriding this question.
        analyst.reset_context()
        churn = await analyst.ask(
            "Why did our churn rate spike last month? Verify whether it actually increased. Use the 90-day inactivity definition."
        )
        assert churn.quality_status == "validated"
        assert any(e.request.kind == "churn" for e in churn.evidence)
        print("churn:", len(churn.evidence), "queries; reserve", churn.estimated_cost_usd)
    finally:
        store.close()


async def test_live_quarterly_report(tmp_path: Path) -> None:
    settings = Settings.load()
    if not settings.gemini_api_key.get_secret_value() or not settings.google_cloud_project:
        pytest.skip("External credentials required")
    settings.data_dir = tmp_path
    logging.getLogger("google").setLevel(logging.CRITICAL)
    store = ReportStore(tmp_path / "live.sqlite3")
    analyst = Analyst(
        settings,
        DEMO_USERS["alice"],
        BigQueryExecutor(settings.google_cloud_project),
        store,
        "live-report",
    )
    try:
        report = await analyst.ask(
            "Create a report for Q1 2026 including insights and action items for Q2 2026."
        )
        assert report.quality_status == "validated"
        assert report.evidence and (
            "action" in report.text.lower() or "recommend" in report.text.lower()
        )
        assert store.list("alice") == []
        print("Q1 report:", len(report.evidence), "queries; reserve", report.estimated_cost_usd)
        print("Live event log:", tmp_path / "events.log")
        assert "2026-04-01 to 2026-07-01" in report.text
        assert "Proposed actions" in report.text
        assert "Verified findings" in report.text
        assert "high-margin" not in report.text.lower()
        (tmp_path / "answer.json").write_text(report.model_dump_json(indent=2))
    finally:
        store.close()
