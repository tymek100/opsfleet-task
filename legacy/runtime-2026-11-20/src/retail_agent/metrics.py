"""Deterministic premise checks, separate from the model's interpretation."""

from retail_agent.models import Analysis, Scalar


def churn_comparisons(request: Analysis, rows: list[dict[str, Scalar]]) -> list[dict[str, Scalar]]:
    if request.kind != "churn":
        return []
    comparisons: list[dict[str, Scalar]] = []
    for cohort in sorted({str(row["cohort"]) for row in rows}):
        previous = next(
            (
                r.get("inactivity_share")
                for r in rows
                if str(r["cohort"]) == cohort and r["period"] == str(request.start)
            ),
            None,
        )
        current = next(
            (
                r.get("inactivity_share")
                for r in rows
                if str(r["cohort"]) == cohort and r["period"] == str(request.end)
            ),
            None,
        )
        if isinstance(previous, (float, int)) and isinstance(current, (float, int)):
            change = round((current - previous) * 100, 4)
            direction = "increased" if change > 0 else "decreased" if change < 0 else "unchanged"
            comparisons.append(
                {"cohort": cohort, "percentage_point_change": change, "direction": direction}
            )
        else:
            comparisons.append(
                {"cohort": cohort, "percentage_point_change": None, "direction": "undefined"}
            )
    return comparisons
