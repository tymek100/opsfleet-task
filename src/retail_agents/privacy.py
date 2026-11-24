"""Public facility coordinates require direct warehouse-column provenance.

An arbitrary result with latitude/longitude-shaped fields is not sufficient.
The exception is intentionally conservative for SQL expressions and derived data.
"""

from collections import Counter
from decimal import Decimal, InvalidOperation

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from retail_agent.privacy import screen

_FIELDS = ("center_id", "center_latitude", "center_longitude")


def facility_coordinates(evidence: dict) -> frozenset[tuple[Decimal, Decimal]]:
    """Extract only coordinates selected directly from the same centers row."""
    if evidence.get("metric_version") != "scoped-inventory-v1":
        return frozenset()
    sql = evidence.get("sql")
    if not isinstance(sql, str):
        return frozenset()
    try:
        statements = sqlglot.parse(sql, read="bigquery")
    except ParseError:
        return frozenset()
    if len(statements) != 1:
        return frozenset()
    tree = statements[0]
    if not isinstance(tree, exp.Select) or tree.args.get("with_"):
        return frozenset()
    source = tree.args.get("from_")
    if source is None:
        return frozenset()
    relations = [source.this, *(join.this for join in tree.args.get("joins", []))]
    names = Counter(expression.alias_or_name for expression in tree.expressions)
    pairs: set[tuple[Decimal, Decimal]] = set()
    for relation in relations:
        if (
            not isinstance(relation, exp.Table)
            or relation.name.lower() != "centers"
            or relation.db
            or relation.catalog
        ):
            continue
        alias = relation.alias_or_name
        outputs: dict[str, str] = {}
        for expression in tree.expressions:
            column = expression.this if isinstance(expression, exp.Alias) else expression
            if (
                isinstance(column, exp.Column)
                and column.name in _FIELDS
                and (column.table == alias or (not column.table and len(relations) == 1))
                and names[expression.alias_or_name] == 1
            ):
                outputs[column.name] = expression.alias_or_name
        if set(outputs) != set(_FIELDS):
            continue
        for row in evidence.get("rows", []):
            if not isinstance(row, dict) or type(row.get(outputs["center_id"])) is not int:
                continue
            try:
                latitude = Decimal(str(row[outputs["center_latitude"]]))
                longitude = Decimal(str(row[outputs["center_longitude"]]))
            except (KeyError, InvalidOperation):
                continue
            if (
                latitude.is_finite()
                and longitude.is_finite()
                and -90 <= latitude <= 90
                and -180 <= longitude <= 180
            ):
                pairs.add((latitude, longitude))
    return frozenset(pairs)


def screen_role_text(text: str, app) -> str:
    """Grant the facility-only capability from this runtime's authorized observations."""
    public: set[tuple[Decimal, Decimal]] = set()
    if app.role in {"distribution", "coordinator"}:
        for evidence in app.results.values():
            if (
                evidence.get("scope") != app.identity.scope
                or evidence.get("as_of") != app.as_of
                or evidence.get("snapshot_at") != app.snapshot_at
                or evidence.get("backend") != app.settings.backend
            ):
                continue
            if app.role == "coordinator" and (
                evidence.get("source_agent") != "distribution" or not evidence.get("source_task_id")
            ):
                continue
            public.update(facility_coordinates(evidence))
    return screen(text, public_coordinates=frozenset(public))
