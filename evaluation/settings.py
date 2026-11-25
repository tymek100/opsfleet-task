"""Explicit evaluation limits and local-only Phoenix configuration."""

import math
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_EVALUATION_COST_USD = 2.0


def validate_run_budget(value: float) -> float:
    """Enforce the project spending policy before any evaluation work starts."""
    if not math.isfinite(value) or not 0 < value <= MAX_EVALUATION_COST_USD:
        raise ValueError(
            f"Evaluation budget must be finite, positive, and at most ${MAX_EVALUATION_COST_USD:g} per run."
        )
    return value


def parse_run_budget(value: str) -> float:
    """The same policy for standalone argparse entry points."""
    return validate_run_budget(float(value))


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
