"""Executable schemas are the source of capability and constraint descriptions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_agent.models import CHURN_DIMENSIONS, MAX_PERIOD_DAYS, Analysis, Requirement

FILTER_FIELDS = ("brands", "product_ids", "customer_id", "completed_only", "inactivity_days")


def capability_manifest() -> dict[str, object]:
    return {
        "max_period_days": MAX_PERIOD_DAYS,
        "churn_dimensions": [d.value for d in CHURN_DIMENSIONS],
        "query_schema": Analysis.model_json_schema(),
        "output_schema": Requirement.model_json_schema(),
        "filter_fields": list(FILTER_FIELDS),
        "time": "UTC calendar dates, start inclusive and end exclusive; explicit fiscal dates required",
        "sales": "Every query returns revenue from item sale_price, units, distinct orders and customers. Totals also expose calendar days and revenue/day. Default excludes cancelled/returned orders AND items; completed_only restricts both to Complete.",
        "churn": "Total/brand snapshots at BOTH start and end. Each includes eligible_customers, inactive_customers and inactivity_share, plus computed percentage-point change. Requesting inactivity_share includes these population counts automatically. Eligibility: first qualifying purchase more than inactivity_days ago; inactivity: last qualifying purchase more than inactivity_days ago. Empty denominator is undefined.",
        "privacy": "No customer contact details or individual geography. State aggregates require >=5 customers and forbid customer/product filters. Customer spending by internal ID is supported.",
        "scope": "Empty brands uses trusted identity scope. Explicit brands may narrow it but never grant access. All filters remain in effect for empty results.",
        "monthly_rows": "Monthly output requires one row for every intersected calendar month, including partial months. Compute the inclusive calendar-month count from the exclusive end date. This count must fit query_schema.properties.limit.maximum. If it exceeds that bound, report out_of_range with field=limit and value=the required row count; never truncate or substitute a yearly grouping.",
        "execution": "Code executes every requested output directly. Total/month metrics share one query; different ranked metrics require separate queries. No arbitrary SQL, code, web tools or hard-delete confirmation is model-accessible.",
    }


class CapabilityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["unsupported_filter", "unsupported_metric", "out_of_range"]
    field: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z][A-Za-z0-9_ ]*$",
        description="For out_of_range use the exact bounded numeric property from query_schema, such as limit or inactivity_days. For unsupported metrics/filters use the requested unavailable measure/filter name.",
    )
    value: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def verify_against_schema(self) -> "CapabilityIssue":
        if self.kind == "unsupported_filter":
            if self.field in FILTER_FIELDS or self.field in Analysis.model_fields:
                raise ValueError(
                    "This field exists; explain a specific incompatible combination instead"
                )
        elif self.kind == "unsupported_metric":
            metrics = Requirement.model_json_schema()["properties"]["metric"]["enum"]
            if self.field in metrics:
                raise ValueError("This metric is supported; do not report it as unavailable")
        else:
            properties = Analysis.model_json_schema()["properties"]
            spec = properties.get(self.field, {})
            if self.value is None or not (
                ("minimum" in spec and self.value < spec["minimum"])
                or ("maximum" in spec and self.value > spec["maximum"])
            ):
                raise ValueError("An out-of-range issue must violate an executable numeric bound")
        return self

    def explanation(self) -> str:
        if self.kind == "unsupported_filter":
            return (
                f"Filtering by {self.field} is not supported. Available filters: "
                + ", ".join(FILTER_FIELDS)
                + ". No query was run; the requested filter was not dropped."
            )
        if self.kind == "unsupported_metric":
            return f"The requested measure ({self.field}) is unavailable. No substitute analysis was run."
        spec = Analysis.model_json_schema()["properties"][self.field]
        bounds = ", ".join(
            f"{name} {spec[name]}" for name in ("minimum", "maximum") if name in spec
        )
        return f"The requested {self.field} value ({self.value:g}) is outside the supported bounds: {bounds}. No default value was substituted; nothing was queried."
