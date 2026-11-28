"""Small, explicit configuration. Credentials stay outside agent messages."""

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    gemini_api_key: SecretStr = SecretStr("")
    google_cloud_project: str = ""
    gemini_model: str = "gemini-3.8-flash"
    thinking_level: Literal["low", "medium", "high"] = "low"
    max_model_calls: int = Field(default=8, ge=1, le=20)
    max_output_tokens: int = Field(default=4096, ge=128, le=8192)
    turn_timeout_seconds: int = Field(default=120, ge=10, le=300)
    max_query_bytes: int = Field(default=100_000_000, ge=1, le=1_000_000_000)

    @classmethod
    def load(cls):
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
        return cls()
