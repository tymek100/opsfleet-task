"""Deterministic contract validation. Natural-language interpretation lives in planning.py."""

from retail_agent.models import Analysis, AppError, Dimension, Evidence, Identity, Intent, Period
from retail_agent.queries import compile_query


def validate_contract(intent: Intent, identity: Identity) -> None:
    if intent.period is None or not intent.requirements:
        raise AppError("The analysis plan needs a period and at least one requested output.")
    if intent.actions != (intent.action_period is not None):
        raise AppError("The plan must specify an action period exactly when actions are requested.")
    if intent.comparison is None and (intent.comparison_requirements or intent.comparison_metrics):
        raise AppError("Comparison outputs require a comparison period.")
    if intent.comparison and not intent.comparison_requirements:
        raise AppError("The plan must state which comparison outputs are required.")
    if intent.comparison_metrics and (
        intent.kind != "sales"
        or not all(
            any(req.dimension == Dimension.TOTAL for req in requirements)
            for requirements in (intent.requirements, intent.comparison_requirements)
        )
    ):
        raise AppError("Revenue comparison metrics require totals in both periods.")
    if intent.comparison == intent.period:
        raise AppError("Comparison periods must differ.")
    for period, requirements in [
        (intent.period, intent.requirements),
        (intent.comparison, intent.comparison_requirements),
    ]:
        if period is None:
            continue
        if len(requirements) > 12:
            raise AppError("Too many requested outputs; narrow the analysis.")
        for requirement in requirements:
            if requirement.dimension == Dimension.MONTH:
                months = (
                    (period.end.year - period.start.year) * 12
                    + period.end.month
                    - period.start.month
                    + (period.end.day > 1)
                )
                if months > 50:
                    raise AppError("Monthly analysis is limited to 50 months; narrow the period.")
            if intent.kind == "churn" and requirement.measures:
                raise AppError("Sales measures cannot be added to an inactivity analysis.")
            if intent.kind == "churn" and requirement.metric != "inactivity_share":
                raise AppError(
                    "Churn plans must request inactivity share and its population evidence."
                )
            if intent.kind == "sales" and requirement.metric == "inactivity_share":
                raise AppError("Inactivity share requires a churn analysis.")
            if {requirement.metric, *requirement.measures} & {
                "days",
                "revenue_per_day",
            } and requirement.dimension != Dimension.TOTAL:
                raise AppError("Calendar-day comparisons require total outputs.")
            request = Analysis(
                kind=intent.kind,
                dimension=requirement.dimension,
                start=period.start,
                end=period.end,
                rank_by=requirement.metric
                if requirement.metric in ("revenue", "orders", "units", "customers")
                else "revenue",
                limit=requirement.minimum_rows,
                brands=intent.brands,
                product_ids=intent.product_ids,
                customer_id=intent.customer_id,
                completed_only=intent.completed_only,
                inactivity_days=intent.inactivity_days,
            )
            compile_query(
                request, identity
            )  # Existing authorization and safe SQL boundary; no I/O.


def execution_requests(intent: Intent) -> list[Analysis]:
    """Expand a validated data contract, never user text, into minimal bounded queries."""
    requests: dict[tuple[object, ...], Analysis] = {}
    for period, requirements in (
        (intent.period, intent.requirements),
        (intent.comparison, intent.comparison_requirements),
    ):
        if period is None:
            continue
        for req in requirements:
            rank_by = (
                req.metric
                if req.metric in ("revenue", "orders", "units", "customers")
                else "revenue"
            )
            if req.dimension in (Dimension.TOTAL, Dimension.MONTH) or intent.kind == "churn":
                rank_by = (
                    "revenue"  # These return all measures and have no metric-based row selection.
                )
            limit = req.minimum_rows
            if req.dimension == Dimension.MONTH:
                limit = (
                    (period.end.year - period.start.year) * 12
                    + period.end.month
                    - period.start.month
                    + (period.end.day > 1)
                )
            key = (period.start, period.end, req.dimension, rank_by)
            if key in requests:
                limit = max(limit, requests[key].limit)
            requests[key] = Analysis(
                kind=intent.kind,
                dimension=req.dimension,
                start=period.start,
                end=period.end,
                rank_by=rank_by,
                limit=limit,
                brands=intent.brands,
                product_ids=intent.product_ids,
                customer_id=intent.customer_id,
                completed_only=intent.completed_only,
                inactivity_days=intent.inactivity_days,
            )
    return list(requests.values())


def validate_request(request: Analysis, intent: Intent, identity: Identity) -> None:
    validate_contract(intent, identity)
    period = Period(start=request.start, end=request.end)
    if period not in (intent.period, intent.comparison):
        raise AppError("Query period does not match the reviewed analysis plan.")
    if request.kind != intent.kind:
        raise AppError("Query kind does not match the reviewed analysis plan.")
    if request.customer_id != intent.customer_id or set(request.product_ids) != set(
        intent.product_ids
    ):
        raise AppError("Individual/product filters do not match the reviewed analysis plan.")
    if set(request.brands) != set(intent.brands):
        raise AppError("Brand filters do not match the reviewed analysis plan.")
    if (
        request.completed_only != intent.completed_only
        or request.inactivity_days != intent.inactivity_days
    ):
        raise AppError("Metric override was not requested in the reviewed analysis plan.")
    requirements = (
        intent.requirements if period == intent.period else intent.comparison_requirements
    )
    if not any(req.dimension == request.dimension for req in requirements):
        raise AppError("Query grouping was not requested in the reviewed analysis plan.")
    if request.dimension == Dimension.MONTH:
        months = (
            (request.end.year - request.start.year) * 12
            + request.end.month
            - request.start.month
            + (request.end.day > 1)
        )
        if request.limit < months:
            raise AppError("Monthly query limit would truncate the requested period.")
    for req in requirements:
        if (
            request.dimension == req.dimension
            and request.rank_by == req.metric
            and request.limit < req.minimum_rows
        ):
            raise AppError("Ranking limit is smaller than requested in the reviewed analysis plan.")


def completion_issues(intent: Intent, evidence: list[Evidence], facts: list[str]) -> list[str]:
    issues: list[str] = []
    periods = [p for p in (intent.period, intent.comparison) if p]
    for period in periods:
        requirements = (
            intent.comparison_requirements or intent.requirements
            if period == intent.comparison
            else intent.requirements
        )
        for req in requirements:
            matching = [
                e
                for e in evidence
                if e.request.start == period.start
                and e.request.end == period.end
                and e.request.dimension == req.dimension
                and e.request.kind == intent.kind
                and (
                    req.dimension
                    not in (
                        Dimension.PRODUCT,
                        Dimension.CUSTOMER,
                        Dimension.BRAND,
                        Dimension.CATEGORY,
                        Dimension.STATE,
                    )
                    or e.request.rank_by == req.metric
                )
            ]
            if not matching:
                issues.append(f"missing_evidence:{req.dimension}:{req.metric}:{period.start}")
                continue
            selected = matching[0]
            count = (
                len(selected.rows)
                if req.dimension == Dimension.MONTH or intent.kind == "churn"
                else min(req.minimum_rows, len(selected.rows))
            )
            expected = {
                f"{selected.id}.r{i}.{measure}"
                for i in range(count)
                for measure in [req.metric, *req.measures]
            }
            if not expected <= set(facts):
                issues.append(f"missing_facts:{req.dimension}:{req.metric}:{period.start}")
            if intent.kind == "churn":
                population = {
                    f"{selected.id}.r{i}.{metric}"
                    for i in range(len(selected.rows))
                    for metric in ("eligible_customers", "inactive_customers")
                }
                if not population <= set(facts):
                    issues.append("missing_churn_population_counts")
                needed = {
                    f"{selected.id}.c{i}.percentage_point_change"
                    for i in range(len(selected.comparisons))
                }
                if not needed <= set(facts):
                    issues.append("missing_churn_premise_check")
    if intent.comparison_metrics and intent.period and intent.comparison:
        totals: list[Evidence] = []
        for period in (intent.period, intent.comparison):
            item = next(
                (
                    e
                    for e in evidence
                    if e.request.kind == "sales"
                    and e.request.dimension == Dimension.TOTAL
                    and e.request.start == period.start
                    and e.request.end == period.end
                ),
                None,
            )
            if item:
                totals.append(item)
        if len(totals) == 2:
            new, old = totals
            expected_changes = {
                f"{new.id}.vs.{old.id}.{name}" for name in intent.comparison_metrics
            }
            if not expected_changes <= set(facts):
                issues.append("missing_period_comparison_metrics")
    return sorted(set(issues))
