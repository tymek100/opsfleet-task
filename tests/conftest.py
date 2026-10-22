"""Offline defaults: credentials never loaded; cloud boundaries replaced explicitly."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from retail_agent.config import Settings
from retail_agent.models import Analysis, Answer, Evidence
from retail_agent.reports import ReportStore


@pytest.fixture(autouse=True)
def isolated_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    if request.keywords.get("live"):
        return
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-offline-tests")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "absent.json"))
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "offline-project")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, question_budget_usd=1)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ReportStore]:
    instance = ReportStore(tmp_path / "reports.sqlite3")
    yield instance
    instance.close()


@pytest.fixture
def answer() -> Answer:
    return Answer(
        text="Calvin Klein revenue [E1]",
        trace_id="fixture",
        evidence=[
            Evidence(
                id="E1",
                request=Analysis.model_validate({"start": "2026-01-01", "end": "2026-04-01"}),
                scope="Calvin Klein",
                definitions="fixture",
                rows=[{"revenue": 100.0}],
                job_id="fixture",
                sql_hash="fixture",
                bytes_processed=0,
                queried_at="2026-04-01T00:00:00Z",
            )
        ],
    )
