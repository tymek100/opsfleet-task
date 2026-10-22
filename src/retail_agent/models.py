"""Validated contracts. Identity never comes from model arguments."""

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

type Scalar = str | int | float | bool | None


class AppError(Exception):
    """A safe, actionable error whose message may be shown to the user."""


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str
    brands: tuple[str, ...]
    ceo: bool = False

    @property
    def scope(self) -> str:
        return "all brands" if self.ceo else ", ".join(self.brands)


DEMO_USERS = {
    "alice": Identity(user_id="alice", brands=("Calvin Klein",)),
    "bob": Identity(user_id="bob", brands=("Levi's",)),
    "ceo": Identity(user_id="ceo", brands=(), ceo=True),
}


class Dimension(StrEnum):
    TOTAL = "total"
    PRODUCT = "product"
    BRAND = "brand"
    CATEGORY = "category"
    MONTH = "month"
    STATE = "state"
    CUSTOMER = "customer"


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["sales", "churn"] = "sales"
    dimension: Dimension = Dimension.TOTAL
    start: date
    end: date
    rank_by: Literal["revenue", "customers", "orders", "units"] = "revenue"
    limit: int = Field(default=10, ge=1, le=50)
    brands: list[str] = Field(default_factory=list, max_length=10)
    product_ids: list[int] = Field(default_factory=lambda: list[int](), max_length=20)
    customer_id: int | None = Field(default=None, ge=1)
    completed_only: bool = False
    inactivity_days: int = Field(default=90, ge=7, le=365)

    @model_validator(mode="after")
    def check_scope(self) -> "Analysis":
        if self.end <= self.start or (self.end - self.start).days > 366 * 5:
            raise ValueError("Use a positive period of at most five years.")
        if self.dimension == Dimension.STATE and (self.customer_id or self.product_ids):
            raise ValueError("State cohorts cannot be filtered by customer or product IDs.")
        if self.kind == "churn" and (
            self.dimension not in (Dimension.TOTAL, Dimension.BRAND)
            or self.customer_id
            or self.product_ids
        ):
            raise ValueError("Churn supports total or brand cohorts, with no individual filters.")
        if any(len(b) > 100 for b in self.brands) or any(i < 1 for i in self.product_ids):
            raise ValueError("Invalid filter.")
        return self


class Evidence(BaseModel):
    id: str
    request: Analysis
    scope: str
    definitions: str
    rows: list[dict[str, Scalar]]
    job_id: str
    sql_hash: str
    bytes_processed: int
    queried_at: str
    source_latest_at: str | None = None
    comparisons: list[dict[str, Scalar]] = Field(default_factory=lambda: list[dict[str, Scalar]]())


class Answer(BaseModel):
    text: str
    evidence: list[Evidence] = Field(default_factory=lambda: list[Evidence]())
    trace_id: str
    estimated_cost_usd: float = 0
    quality_status: Literal["not_applicable", "validated", "fallback"] = "not_applicable"
