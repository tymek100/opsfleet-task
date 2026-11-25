"""Configuration is loaded explicitly; importing the package reads no secrets."""

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file=None)
    gemini_api_key: SecretStr = SecretStr("")
    google_cloud_project: str = ""
    warehouse_source_dataset: str = "bigquery-public-data.thelook_ecommerce"
    gemini_model: str = "gemini-3.8-flash"
    thinking_level: Literal["low", "medium", "high"] = "low"
    review_thinking_level: Literal["low", "medium", "high"] = "medium"
    data_dir: Path = Path(".retail-agent")
    backend: Literal["bigquery", "fixture"] = "bigquery"
    fixture_path: Path = Field(
        default_factory=lambda: Path(__file__).parent / "integrations/bigquery/retail_demo.sql"
    )
    turn_timeout_seconds: float = Field(default=120, ge=1, le=600)
    question_budget_usd: float = Field(default=1, gt=0, le=10)
    max_model_calls: int = Field(default=12, ge=2, le=30)
    max_tool_calls: int = Field(default=24, ge=1, le=80)
    max_queries: int = Field(default=8, ge=1, le=20)
    max_query_bytes: int = Field(default=100_000_000, ge=1)
    max_output_tokens: int = Field(default=4096, ge=128, le=16384)
    review_output_tokens: int = Field(default=2048, ge=128, le=4096)
    max_answer_reviews: int = Field(default=3, ge=1, le=5)
    max_context_bytes: int = Field(default=150_000, ge=4000)
    max_review_bytes: int = Field(default=60_000, ge=2000)
    review_overhead_bytes: int = Field(default=12_000, ge=4000)
    review_reserve_seconds: float = Field(default=30, ge=0, le=60)
    model_min_interval_seconds: float = Field(default=0, ge=0, le=30)
    input_usd_per_million: float = Field(default=2, gt=0)
    output_usd_per_million: float = Field(default=12, gt=0)
    bigquery_usd_per_tib: float = Field(default=6.25, gt=0)

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(repository_root() / ".env", override=False)
        return cls()
