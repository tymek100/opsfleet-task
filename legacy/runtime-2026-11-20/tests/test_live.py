"""Opt-in smoke checks, not a numerical/semantic quality benchmark.

Run: uv run pytest -m live --force-enable-socket -s tests/test_live.py
Five user turns may consume up to five configured question budgets. Inspect saved
artifacts and SQL for business correctness; approval alone is not that proof.
"""

import logging
from pathlib import Path

import pytest

from retail_agent.agent import Analyst
from retail_agent.bigquery import BigQueryExecutor
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, Answer
from retail_agent.reports import ReportStore

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


def runtime(tmp_path: Path, store: ReportStore) -> Analyst:
    settings = Settings.load()
    if not settings.gemini_api_key.get_secret_value() or not settings.google_cloud_project:
        pytest.skip("External credentials required")
    settings.data_dir = tmp_path
    logging.getLogger("google").setLevel(logging.CRITICAL)
    return Analyst(
        settings,
        DEMO_USERS["alice"],
        BigQueryExecutor(settings.google_cloud_project),
        store,
        "live",
    )


def record(answer: Answer, path: Path) -> None:
    path.write_text(answer.model_dump_json(indent=2))
    assert answer.evaluation_status == "approved"
    assert answer.quality_status == "validated" and answer.query_evidence
    assert all(e.scope == DEMO_USERS["alice"].scope for e in answer.query_evidence)
    assert all(len(e.rows) <= 100 for e in answer.query_evidence)
    print(
        path.name, len(answer.query_evidence), "evidence sets; reserve", answer.estimated_cost_usd
    )


async def test_live_rankings_followup(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "live.sqlite3")
    try:
        analyst = runtime(tmp_path, store)
        ranking = await analyst.ask(
            "Show the top ten products by revenue and, separately, by distinct customers for Q1 2026. "
            "Use product_id and revenue columns in the first table, product_id and customers in the second."
        )
        record(ranking, tmp_path / "rankings.json")
        for metric in ("revenue", "customers"):
            rankings = [
                e.rows
                for e in ranking.query_evidence
                if e.rows and {"product_id", metric} <= set(e.rows[0])
            ]
            assert rankings, f"Missing the requested {metric} ranking"
            assert any(
                len(rows) <= 10
                and [float(str(r[metric])) for r in rows]
                == sorted((float(str(r[metric])) for r in rows), reverse=True)
                for rows in rankings
            )
        followup = await analyst.ask(
            "For that same quarter, show total revenue in one table with a revenue column, "
            "and a monthly breakdown in another table with month and revenue columns."
        )
        record(followup, tmp_path / "followup.json")
        totals = [
            e.rows[0]["revenue"]
            for e in followup.query_evidence
            if len(e.rows) == 1 and set(e.rows[0]) == {"revenue"}
        ]
        monthly = [
            e.rows
            for e in followup.query_evidence
            if e.rows and {"month", "revenue"} <= set(e.rows[0])
        ]
        assert totals and monthly
        assert float(str(totals[0])) == pytest.approx(
            sum(float(str(r["revenue"])) for r in monthly[0])
        )
        assert store.list("alice") == []
    finally:
        store.close()


async def test_live_quarterly_report(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "live.sqlite3")
    try:
        report = await runtime(tmp_path, store).ask(
            "Create a report for Q1 2026 including insights and action items for Q2 2026."
        )
        record(report, tmp_path / "report.json")
        assert "action" in report.text.lower() or "recommend" in report.text.lower()
        assert "Q2" in report.text
        assert store.list("alice") == []
    finally:
        store.close()


async def test_live_churn(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "live.sqlite3")
    try:
        churn = await runtime(tmp_path, store).ask(
            "Why did our inactivity rate spike in March 2026? First verify whether it increased "
            "between 2026-03-01 and 2026-04-01 using the 90-day inactivity definition. "
            "Show the eligible and inactive counts and share at both dates; distinguish measured "
            "associations from hypotheses. Do not assume a spike occurred."
        )
        record(churn, tmp_path / "churn.json")
        assert any(
            "inactive" in " ".join(e.rows[0]).lower() for e in churn.query_evidence if e.rows
        )
        assert store.list("alice") == []
    finally:
        store.close()


async def test_live_exact_quick_start_prompt(tmp_path: Path) -> None:
    """Regression for the user's reported long-running turn, without alias hints."""
    import time

    store = ReportStore(tmp_path / "exact-example.sqlite3")
    try:
        analyst = runtime(tmp_path, store)
        started = time.monotonic()
        answer = await analyst.ask(
            "Show our top five products by revenue and, separately, by distinct customers in Q1 2026."
        )
        record(answer, tmp_path / "exact-example.json")
        print("Exact example elapsed seconds:", round(time.monotonic() - started, 1))
        assert len(answer.query_evidence) >= 2
        assert all(len(e.rows) <= 5 for e in answer.query_evidence)
        assert store.list("alice") == []
    finally:
        store.close()
