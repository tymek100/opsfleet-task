"""Standalone demo data and CLI work without the removed example collection."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from retail_insight.config import Settings, repository_root
from retail_insight.integrations.bigquery.retail import QueryGateway
from retail_insight.interfaces.cli import app


async def test_packaged_demo_backend_works_outside_repository_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings.model_construct(backend="fixture")
    assert settings.fixture_path.is_file()
    assert settings.fixture_path.name == "retail_demo.sql"
    assert repository_root() == Path(__file__).resolve().parents[2]
    gateway = QueryGateway(None, backend="fixture", fixture_path=settings.fixture_path)
    result = await gateway.query("SELECT COUNT(*) AS products FROM products")
    assert result["rows"][0]["products"] > 0


@pytest.mark.parametrize("command", ["chat", "ask"])
def test_cli_and_settings_no_longer_offer_example_retrieval(command):
    result = CliRunner().invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "golden" not in result.output.lower()
    assert not any(name.startswith("golden") for name in Settings.model_fields)
