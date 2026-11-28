from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from retail_insight.integrations.azure.connector import AzureConnector, AzureSettings
from retail_insight.integrations.gcp.connector import GCPConnector
from retail_insight.observability.tracing import configure_tracing, observation, span
from tests.support.tracing import MemoryClient


def test_google_connection_does_not_follow_azure_settings(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://azure.example/project")
    create = Mock()
    monkeypatch.setattr("retail_insight.integrations.gcp.connector.genai.Client", create)
    GCPConnector.model_client("existing-google-key", timeout_seconds=12)
    assert create.call_args.kwargs["api_key"] == "existing-google-key"
    assert create.call_args.kwargs["vertexai"] is False
    assert create.call_args.kwargs["http_options"].retry_options.attempts == 1


def test_azure_project_uses_entra_never_model_api_key(monkeypatch):
    settings = AzureSettings(
        foundry_project_endpoint="https://project.example/api/projects/retail",
        azure_openai_api_key=SecretStr("model-key"),
    )
    connector = AzureConnector(settings)
    credential = object()
    monkeypatch.setattr(connector, "credential", lambda: credential)
    create = Mock()
    monkeypatch.setattr("azure.ai.projects.AIProjectClient", create)
    connector.project()
    assert create.call_args.kwargs["credential"] is credential
    assert "api_key" not in create.call_args.kwargs


def test_managed_identity_project_connection_metadata(monkeypatch):
    connector = AzureConnector(AzureSettings(applicationinsights_connection_string=SecretStr("")))
    project = SimpleNamespace(
        connections=SimpleNamespace(
            list=lambda **kwargs: [
                SimpleNamespace(
                    metadata={"ApplicationInsightsConnectionString": "InstrumentationKey=example"}
                )
            ]
        )
    )
    monkeypatch.setattr(connector, "project", lambda: project)
    assert connector.monitoring_connection() == "InstrumentationKey=example"


def test_secrets_and_large_captures_survive_cloud_boundary(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret-canary")
    exporter = MemoryClient()
    tracing = configure_tracing(exporter=exporter, mode="synthetic")
    with span("test") as current:
        current.observations.append(
            {"event": "prompt_input", "question": "界" * 25000 + "azure-secret-canary"}
        )
    tracing.close()
    saved = exporter.get_finished_spans()[0]
    assert "界" * 25000 in saved.inputs["question"]
    assert "azure-secret-canary" not in saved.to_json()
    assert all(len(v.encode()) < 8192 for v in saved.attributes.values() if isinstance(v, str))
    assert "password" not in observation({"password": "secret", "event": "test"}, mode="synthetic")


def test_azure_plain_http_endpoint_rejected():
    with pytest.raises(ValueError):
        AzureSettings(foundry_project_endpoint="http://wrong.example")
