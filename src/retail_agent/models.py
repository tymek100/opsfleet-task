"""Validated contracts. Identity never comes from model arguments."""

from datetime import date
from enum import StrEnum
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

type Scalar = str | int | float | bool | None
type ComparisonMetric = Literal[
    "revenue_change", "revenue_change_pct", "revenue_per_day_change_pct"
]


class AppError(Exception):
    """A safe message plus a content-free diagnostic category."""

    code = "application_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class AccessDeniedError(AppError):
    """An authorization denial must not be retried as a query correction."""

    code = "access_denied"


class RateLimitError(AppError):
    """Provider throttling exposed without raw SDK details."""

    code = "rate_limit"

    def __init__(self) -> None:
        super().__init__(
            "Gemini rate limit reached. Please try again later. "
            "If this persists, check your Gemini API quota."
        )


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


MAX_PERIOD_DAYS = 366 * 5
CHURN_DIMENSIONS = (Dimension.TOTAL, Dimension.BRAND)


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["sales", "churn"] = "sales"
    dimension: Dimension = Dimension.TOTAL
    start: date = Field(description="UTC inclusive start date")
    end: date = Field(description="UTC exclusive end date")
    rank_by: Literal["revenue", "customers", "orders", "units"] = "revenue"
    limit: int = Field(default=10, ge=1, le=50)
    brands: list[str] = Field(default_factory=list, max_length=10)
    product_ids: list[int] = Field(default_factory=lambda: list[int](), max_length=20)
    customer_id: int | None = Field(default=None, ge=1)
    completed_only: bool = False
    inactivity_days: int = Field(
        default=90,
        ge=7,
        le=365,
        description="Days without a qualifying purchase; same threshold for cohort eligibility",
    )

    @model_validator(mode="after")
    def check_scope(self) -> "Analysis":
        if self.end <= self.start or (self.end - self.start).days > MAX_PERIOD_DAYS:
            raise ValueError("Use a positive period of at most five years.")
        if self.dimension == Dimension.STATE and (self.customer_id or self.product_ids):
            raise ValueError("State cohorts cannot be filtered by customer or product IDs.")
        if self.kind == "churn" and (
            self.dimension not in CHURN_DIMENSIONS or self.customer_id or self.product_ids
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


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: date = Field(description="UTC inclusive start date")
    end: date = Field(description="UTC exclusive end date")

    @model_validator(mode="after")
    def ordered(self) -> "Period":
        if self.end <= self.start:
            raise ValueError("Period end must follow start")
        return self


SalesMeasure = Literal[
    "revenue",
    "customers",
    "orders",
    "units",
    "revenue_per_order",
    "revenue_per_unit",
    "units_per_order",
    "days",
    "revenue_per_day",
]


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dimension: Dimension
    metric: Literal[
        "revenue", "customers", "orders", "units", "inactivity_share", "days", "revenue_per_day"
    ] = "revenue"
    measures: list[SalesMeasure] = Field(
        default_factory=lambda: list[SalesMeasure](),
        max_length=9,
        description="Additional columns to display for this same selected population, not separate rankings.",
    )
    minimum_rows: int = Field(default=1, ge=1, le=50)


class Intent(BaseModel):
    """Model-proposed analytical contract; identity and authorization remain external."""

    model_config = ConfigDict(extra="forbid")
    period: Period | None = None
    comparison: Period | None = None
    action_period: Period | None = None
    actions: bool = False
    report: bool = False
    kind: Literal["sales", "churn"] = "sales"
    requirements: list[Requirement] = Field(default_factory=lambda: list[Requirement]())
    comparison_requirements: list[Requirement] = Field(default_factory=lambda: list[Requirement]())
    customer_id: int | None = None
    product_ids: list[int] = Field(default_factory=lambda: list[int]())
    comparison_metrics: list[ComparisonMetric] = Field(
        default_factory=lambda: list[ComparisonMetric]()
    )
    brands: list[str] = Field(default_factory=list, max_length=10)
    completed_only: bool = False
    inactivity_days: int = Field(
        default=90,
        ge=7,
        le=365,
        description="Days without a qualifying purchase; same threshold for cohort eligibility",
    )
    explanation_requested: bool = False

    @model_validator(mode="before")
    @classmethod
    def read_legacy_contract(cls, value: object) -> object:
        # Stored reports from the retired parser remain readable. This is data
        # migration only; no text interpretation or legacy execution path.
        if isinstance(value, dict):
            return {
                k: v
                for k, v in cast(dict[str, object], value).items()
                if k not in {"period_error", "pending_quarter", "clarification"}
            }
        return value


class ViewSelection(BaseModel):
    operation: str
    candidate_count: int
    sort_by: str | None = None
    descending: bool = True
    offset: int = 0
    limit: int | None = None


class ResultView(BaseModel):
    """A materialized subset of evidence; hidden columns support subsequent follow-ups."""

    key: str
    columns: list[str]
    rows: list[dict[str, Scalar]]
    displayed_columns: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    concise: bool = False
    derivation: list[str] = Field(default_factory=list)
    selection: ViewSelection | None = None


class Answer(BaseModel):
    view: ResultView | None = None
    text: str
    evidence: list[Evidence] = Field(default_factory=lambda: list[Evidence]())
    trace_id: str
    estimated_cost_usd: float = 0
    quality_status: Literal["not_applicable", "validated", "fallback"] = "not_applicable"
    intent: Intent | None = None
    versions: dict[str, str] = Field(default_factory=lambda: dict[str, str]())
    warnings: list[str] = Field(default_factory=lambda: list[str]())
