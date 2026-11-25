"""Local launcher isolation without calling Docker or a model provider."""

import importlib.util
import json
from pathlib import Path

import pytest
from dotenv import dotenv_values


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "infra/agents/start.py"
    spec = importlib.util.spec_from_file_location("stack_launcher_test", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "STATE", tmp_path / ".artifacts/agents")
    monkeypatch.setattr(module, "dotenv_values", lambda _path: {})
    for key in module.MODEL_KEYS | module.WAREHOUSE_KEYS | module.MAPS_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "model-secret")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "warehouse-project")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "maps-secret")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-copy")
    catalog = tmp_path / "infra/agents/catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps(
            {
                "coordinator": {
                    "name": "Coordinator",
                    "card_url": "http://coordinator:8000/.well-known/agent-card.json",
                }
            }
        )
    )
    for relative in (
        "src/retail_insight/integrations/bigquery/fixtures.json",
        "knowledge/fixtures/retail_seed_v1.sql",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic warehouse rows")
    return module


def test_configuration_profiles_do_not_share_unneeded_credentials(launcher):
    launcher.prepare("fixture")
    secret_dir = launcher.STATE / "secrets"
    assert dotenv_values(secret_dir / "model.env") == {"GEMINI_API_KEY": "model-secret"}
    assert dotenv_values(secret_dir / "maps.env") == {"GOOGLE_MAPS_API_KEY": "maps-secret"}
    assert dotenv_values(secret_dir / "warehouse.env") == {
        "GOOGLE_CLOUD_PROJECT": "warehouse-project"
    }
    assert json.loads((secret_dir / "warehouse_adc.json").read_text()) == {}
    assert secret_dir.stat().st_mode & 0o777 == 0o700
    assert "must-not-copy" not in "".join(path.read_text() for path in secret_dir.iterdir())


def test_restarting_stack_preserves_identity_keys(launcher):
    launcher.prepare("fixture")
    signing = (launcher.STATE / "secrets/a2a_signing_key").read_text()
    demo = (launcher.STATE / "secrets/a2a_demo_token").read_text()
    assert signing != demo
    launcher.prepare("fixture")
    assert (launcher.STATE / "secrets/a2a_signing_key").read_text() == signing
    assert (launcher.STATE / "secrets/a2a_demo_token").read_text() == demo


def test_evaluation_mount_profile_requires_explicit_fixture_selection(launcher):
    with pytest.raises(RuntimeError, match="require --backend fixture"):
        launcher.prepare("bigquery", evaluation_fixtures=True)
    with pytest.raises(RuntimeError, match="fixture is missing"):
        launcher.prepare("fixture", evaluation_fixtures=True)
    source = launcher.ROOT / "evaluation/multi_agent"
    source.mkdir(parents=True)
    (source / "fixture.json").write_text("{}")
    (source / "retail_fixture.sql").write_text("SELECT 1;")
    launcher.prepare("fixture", evaluation_fixtures=True)
    assert any("compose.evaluation.yaml" in arg for arg in launcher.compose_args("up"))
    launcher.prepare("fixture")
    assert not any("compose.evaluation.yaml" in arg for arg in launcher.compose_args("up"))


def test_inspector_catalog_contains_no_credentials(launcher):
    launcher.prepare("fixture")
    catalog = json.loads((launcher.STATE / "inspector-catalog.json").read_text())
    assert catalog["specVersion"] == "1.0"
    assert catalog["entries"][0]["type"] == "application/a2a-agent-card+json"
    assert "secret" not in json.dumps(catalog)


def test_changed_source_rows_get_an_isolated_persistent_profile(launcher):
    launcher.prepare("fixture")
    first = dotenv_values(launcher.STATE / "compose.env")["RETAIL_STACK_DATA_PROFILE"]
    (launcher.ROOT / "src/retail_insight/integrations/bigquery/fixtures.json").write_text(
        "different warehouse rows"
    )
    launcher.prepare("fixture")
    second = dotenv_values(launcher.STATE / "compose.env")["RETAIL_STACK_DATA_PROFILE"]
    assert first != second
