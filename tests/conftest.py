"""Isolated settings and real local services; no environment or credentials lookup."""

import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from retail_agent.config import Settings
from retail_agent.contracts import DEMO_USERS
from retail_agent.runtime import Analyst
from retail_agent.services.reports import ReportStore
from retail_agent.services.warehouse import QueryGateway
from tests.support.models import ScriptedModel
from tests.support.warehouse import SQL


@pytest.fixture(autouse=True)
def offline_configuration_boundary(request, monkeypatch):
    """Fail on ambient dotenv/ADC discovery; explicit live tests opt in separately."""
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("phoenix"):
        return

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Offline tests must inject settings and external service boundaries")

    names = {field.casefold() for field in Settings.model_fields}
    names.update(
        {
            "google_api_key",
            "google_application_credentials",
            "gcloud_project",
            "google_cloud_quota_project",
            "google_genai_use_vertexai",
            "google_cloud_location",
        }
    )
    for key in list(os.environ):
        if key.casefold() in names:
            monkeypatch.delenv(key)
    for target in (
        "retail_agent.config.load_dotenv",
        "dotenv.load_dotenv",
        "dotenv.dotenv_values",
        "google.auth.default",
        "google.auth._default.default",
        "google.auth.load_credentials_from_file",
        "google.auth._default.load_credentials_from_file",
    ):
        monkeypatch.setattr(target, forbidden)


@pytest.fixture
def warehouse_fixture(tmp_path):
    path = tmp_path / "contract_warehouse.sql"
    path.write_text(SQL)
    return path


@pytest.fixture
def settings(tmp_path, warehouse_fixture):
    root = Path(__file__).resolve().parents[1]
    return Settings.model_construct(
        gemini_api_key=SecretStr("offline-placeholder"),
        google_cloud_project="offline-project",
        data_dir=tmp_path / "app",
        backend="fixture",
        fixture_path=warehouse_fixture,
        golden_path=root / "knowledge/golden/bootstrap.json",
        golden_bootstrap=False,
        turn_timeout_seconds=60,
        review_reserve_seconds=1,
        question_budget_usd=10,
        max_model_calls=12,
        max_context_bytes=400_000,
        model_min_interval_seconds=0,
    )


@pytest.fixture
def gateway(warehouse_fixture):
    return QueryGateway(("Calvin Klein",), backend="fixture", fixture_path=warehouse_fixture)


@pytest.fixture
def reports(tmp_path):
    store = ReportStore(tmp_path / "reports.sqlite")
    yield store
    store.close()


@pytest.fixture
def make_agent(settings):
    applications = []

    def create(script=(), reviews=(), *, user="alice", **changes):
        config = settings.model_copy(
            update={
                "data_dir": settings.data_dir / str(len(applications)),
                **changes,
            }
        )
        app = Analyst(
            config,
            DEMO_USERS[user],
            model=ScriptedModel(script=list(script)),
            reviewer_model=ScriptedModel(script=list(reviews)),
        )
        applications.append(app)
        return app

    yield create
    for app in applications:
        app.reports.close()
