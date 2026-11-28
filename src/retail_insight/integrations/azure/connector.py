"""Azure resources are independent of the Google inference connection."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file=None)
    foundry_project_endpoint: str = ""
    foundry_tracing: bool = False
    foundry_agent_id: str = "retail-insight"
    foundry_portal_url: str = "https://ai.azure.com"
    applicationinsights_connection_string: SecretStr = SecretStr("")
    azure_monitor_entra_auth: bool = False
    azure_auth_mode: Literal["default", "cli", "managed_identity"] = "default"
    azure_tenant_id: str = ""
    azure_openai_base_url: str = ""
    azure_openai_api_key: SecretStr = SecretStr("")

    @field_validator("foundry_project_endpoint", "azure_openai_base_url", "foundry_portal_url")
    @classmethod
    def https_endpoint(cls, value):
        if value:
            url = urlparse(value)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "Azure endpoints must be HTTPS URLs without credentials or query parameters"
                )
        return value.rstrip("/")


class AzureConnector:
    def __init__(self, settings: AzureSettings | None = None):
        self.settings = settings or AzureSettings()
        self._credential = None
        self._project = None
        self._evals = None

    def credential(self):
        if self._credential is None:
            from azure.identity import (
                AzureCliCredential,
                DefaultAzureCredential,
                ManagedIdentityCredential,
            )

            if self.settings.azure_auth_mode == "cli":
                self._credential = AzureCliCredential(
                    tenant_id=self.settings.azure_tenant_id, process_timeout=10
                )
            elif self.settings.azure_auth_mode == "managed_identity":
                self._credential = ManagedIdentityCredential()
            else:
                self._credential = DefaultAzureCredential(
                    exclude_interactive_browser_credential=True, process_timeout=10
                )
        return self._credential

    def project(self):
        if not self.settings.foundry_project_endpoint:
            raise ValueError(
                "Set FOUNDRY_PROJECT_ENDPOINT; project access requires Microsoft Entra credentials, not AZURE_OPENAI_API_KEY"
            )
        if self._project is None:
            from azure.ai.projects import AIProjectClient

            self._project = AIProjectClient(
                endpoint=self.settings.foundry_project_endpoint,
                credential=self.credential(),
                connection_timeout=10,
                read_timeout=10,
                retry_total=0,
            )
        return self._project

    def evaluations(self):
        if self._evals is None:
            self._evals = self.project().get_openai_client().with_options(timeout=10, max_retries=0)
        return self._evals

    def monitoring_connection(self):
        configured = self.settings.applicationinsights_connection_string.get_secret_value()
        if configured:
            return configured
        # New projects often expose telemetry through a managed-identity connection.
        from azure.ai.projects.models import ConnectionType

        connection = ""
        for item in self.project().connections.list(
            connection_type=ConnectionType.APPLICATION_INSIGHTS
        ):
            connection = (item.metadata or {}).get("ApplicationInsightsConnectionString", "")
            if connection:
                break
        if not connection:
            connection = self.project().telemetry.get_application_insights_connection_string()
        if not connection:
            raise ValueError(
                "Connect Application Insights to the Foundry project or set APPLICATIONINSIGHTS_CONNECTION_STRING"
            )
        return connection

    def model_client(self):
        """Optional Azure inference client; never selected implicitly by agents."""
        from openai import OpenAI

        if (
            not self.settings.azure_openai_base_url
            or not self.settings.azure_openai_api_key.get_secret_value()
        ):
            raise ValueError(
                "Set AZURE_OPENAI_BASE_URL and AZURE_OPENAI_API_KEY for Azure inference"
            )
        return OpenAI(
            base_url=self.settings.azure_openai_base_url,
            api_key=self.settings.azure_openai_api_key.get_secret_value(),
            timeout=30,
            max_retries=0,
        )

    def close(self):
        for resource in (self._evals, self._project, self._credential):
            if resource is not None:
                resource.close()
