"""Explicit evaluation limits and local-only Phoenix configuration."""

from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvaluationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    artifact_root: Path = Path(".artifacts/evaluation")
    phoenix_url: str = "http://127.0.0.1:6006"
    judge_model: str = "gemini-3.8-flash"
    judge_timeout_seconds: float = Field(default=60, gt=0, le=300)
    judge_max_output_tokens: int = Field(default=8192, ge=256, le=16384)
    input_usd_per_million: float = Field(default=2, gt=0)
    output_usd_per_million: float = Field(default=12, gt=0)

    @field_validator("phoenix_url")
    @classmethod
    def local_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Evaluation publication requires a localhost Phoenix endpoint.")
        return value.rstrip("/")
