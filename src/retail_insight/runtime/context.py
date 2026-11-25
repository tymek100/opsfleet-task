"""Validated delegation data, separate from tasks and application authority."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DelegationContext(BaseModel):
    """Created by the coordinator runtime; accepted only over service authentication."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_agent: Literal["coordinator"] = "coordinator"
    original_user_request: str = Field(min_length=1, max_length=6000)
    evidence: list[dict] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def bounded(self):
        if not self.original_user_request.strip():
            raise ValueError("An original user request is required")
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode()) > 32_000:
            raise ValueError("Delegated context exceeds 32,000 bytes")
        return self
