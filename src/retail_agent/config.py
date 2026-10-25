"""Explicit settings load: importing this module does not read credentials."""

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file=None)
    google_cloud_project: str = ""
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.8-flash"
    thinking_level: Literal["low", "medium", "high"] = "medium"
    max_output_tokens: int = Field(default=8192, ge=1024, le=16384)
    commentary_enabled: bool = True
    data_dir: Path = Path(".retail-agent")
    question_budget_usd: float = Field(default=1.0, gt=0, le=10)
    max_query_bytes: int = Field(default=100_000_000, ge=10_000_000)
    turn_timeout_seconds: int = Field(default=120, ge=5, le=300)
    max_model_calls: int = Field(default=8, ge=1, le=12)
    model_min_interval_seconds: float = Field(default=13.0, ge=0, le=60)
    max_queries: int = Field(default=6, ge=1, le=12)
    # Conservative admission rates, configurable for the selected model/region.
    input_usd_per_million: float = Field(default=2.0, gt=0)
    output_usd_per_million: float = Field(default=12.0, gt=0)
    bigquery_usd_per_tib: float = Field(default=6.25, gt=0)

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(".env", override=False)
        return cls()
