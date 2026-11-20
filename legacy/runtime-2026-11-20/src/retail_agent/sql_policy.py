"""Compile untrusted analytical SQL over scoped virtual relations only.

Every physical leaf is replaced with a code-owned subquery. No model-provided
SQL runs against the raw dataset, including through nested CTEs or subqueries.
Geography is deliberately absent; its separate aggregate tool owns suppression.
"""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from retail_agent.models import AccessDeniedError, AppError, Identity
from retail_agent.queries import DATASET, CompiledQuery

TRANSACTION_COLUMNS = {
    "item_id": "INT64",
    "order_id": "INT64",
    "user_id": "INT64",
    "product_id": "INT64",
    "sale_price": "FLOAT64",
    "purchased_at": "TIMESTAMP",
    "brand": "STRING",
    "category": "STRING",
    "product_name": "STRING",
    "item_status": "STRING",
    "order_status": "STRING",
}
CATALOG_COLUMNS = {
    "product_id": "INT64",
    "brand": "STRING",
    "category": "STRING",
    "product_name": "STRING",
}
SCHEMA: dict[str, object] = {
    "sales": TRANSACTION_COLUMNS,
    "transactions": TRANSACTION_COLUMNS,
    "products": CATALOG_COLUMNS,
}

# This is a SQL language boundary, not a list of business questions. Unsupported
# syntax fails closed and can be reformulated by the model within its budget.
NODE_KEYS = {
    "select",
    "union",
    "intersect",
    "except",
    "subquery",
    "with",
    "cte",
    "table",
    "tablealias",
    "identifier",
    "column",
    "alias",
    "from",
    "join",
    "where",
    "group",
    "having",
    "qualify",
    "order",
    "ordered",
    "limit",
    "offset",
    "distinct",
    "literal",
    "null",
    "boolean",
    "star",
    "paren",
    "tuple",
    "case",
    "if",
    "when",
    "interval",
    "datatype",
    "datatypeparam",
    "var",
    "window",
    "windowspec",
    "partition",
    "rownumber",
    "rank",
    "denserank",
    "lag",
    "lead",
    "firstvalue",
    "lastvalue",
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "and",
    "or",
    "not",
    "is",
    "in",
    "between",
    "like",
    "ilike",
    "exists",
    "add",
    "sub",
    "mul",
    "div",
    "intdiv",
    "mod",
    "neg",
    "nullsafeeq",
    "nullsafeneq",
}
FUNCTIONS = {
    "ABS",
    "AVG",
    "CEIL",
    "CEILING",
    "COALESCE",
    "COUNT",
    "COUNT_IF",
    "DATE",
    "DATE_ADD",
    "DATE_SUB",
    "DATE_DIFF",
    "DATE_TRUNC",
    "DATEDIFF",
    "DATETIME",
    "TIMESTAMP",
    "TIMESTAMP_TRUNC",
    "TIMESTAMP_DIFF",
    "TIMESTAMPDIFF",
    "EXTRACT",
    "FLOOR",
    "FORMAT_DATE",
    "FORMAT_TIMESTAMP",
    "GREATEST",
    "LEAST",
    "IF",
    "IFNULL",
    "LAG",
    "LEAD",
    "LOWER",
    "UPPER",
    "MAX",
    "MIN",
    "NULLIF",
    "ROUND",
    "ROW_NUMBER",
    "RANK",
    "DENSE_RANK",
    "SAFE_DIVIDE",
    "SUM",
    "CAST",
    "TRY_CAST",
    "FIRST_VALUE",
    "LAST_VALUE",
    "STDDEV",
    "STDDEV_POP",
    "STDDEV_SAMP",
    "VARIANCE",
    "VAR_POP",
    "VAR_SAMP",
    "CONCAT",
    "SUBSTRING",
    "TRIM",
    "LENGTH",
    "PERCENTILE_CONT",
    "PERCENTILE_DISC",
}

DEFINITIONS = (
    "Scoped SQL v2. sales contains item-level purchases excluding Cancelled/Returned "
    "at BOTH order and item level. transactions contains all statuses; explicitly define "
    "any status overrides. Revenue uses sale_price; orders/customers require distinct IDs. "
    "Brand access is applied before every join, cohort and history calculation. "
    "UTC time; use [start,end) boundaries. Current statuses cannot reconstruct historical "
    "status changes. No customer geography or contact columns are available."
)


def describe_schema() -> dict[str, object]:
    return {
        "dialect": "BigQuery Standard SQL",
        "relations": SCHEMA,
        "definitions": DEFINITIONS,
        "rules": [
            "Use only these unqualified virtual relations. Raw dataset paths are forbidden.",
            "CTEs, joins, unions, windows, conditional aggregates and subqueries are supported.",
            "Give every output expression a unique explicit name; return scalar columns.",
            "At most 100 result rows. Add suitable ordering and a limit for rankings.",
            "Customer IDs are allowed; geography is available only through analyze_states.",
            "For inactivity, derive first/last sales before each as-of boundary; never prefilter away the history.",
            "Default inactivity: first purchase and last purchase before as_of minus 90 days; show numerator, denominator and share.",
            "products includes authorized catalog entries even when they have no purchases.",
        ],
    }


def compile_analysis(sql: str, identity: Identity) -> CompiledQuery:
    if not identity.ceo and not identity.brands:
        raise AccessDeniedError("No brands are assigned to this identity.")
    if not sql.strip() or len(sql) > 16000:
        raise AppError("Provide a SQL query of at most 16000 characters.", code="invalid_query")
    try:
        statements = sqlglot.parse(sql, read="bigquery")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
            raise AccessDeniedError("Only one read-only analytical SELECT is allowed.")
        tree = statements[0]
        for node in tree.walk():
            if isinstance(node, exp.With) and node.args.get("recursive"):
                raise AppError("Recursive queries are not supported.", code="invalid_query")
            if isinstance(node, exp.Func) and node.key not in NODE_KEYS:
                if isinstance(node, exp.Anonymous) or node.sql_name() not in FUNCTIONS:
                    raise AppError(
                        "Unsupported SQL function; use documented SQL built-ins.",
                        code="invalid_query",
                    )
            elif node.key not in NODE_KEYS:
                raise AppError(f"Unsupported SQL construct: {node.key}.", code="invalid_query")
            if isinstance(node, exp.Table) and (
                node.db or node.catalog or not isinstance(node.this, exp.Identifier)
            ):
                raise AccessDeniedError(
                    "Raw tables and table functions are forbidden; use the virtual schema."
                )
            if isinstance(node, exp.CTE) and node.alias.lower() in SCHEMA:
                raise AppError("CTE names must not shadow virtual relations.", code="invalid_query")
            if isinstance(node, exp.Identifier) and not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", node.name
            ):
                raise AppError("Use simple SQL identifiers.", code="invalid_query")
        # Resolve every leaf through SQLGlot's scope graph, including scalar
        # subqueries, unions and aliases. Unknown relations never reach BigQuery.
        for scope in traverse_scope(tree):
            for source in scope.sources.values():
                if isinstance(source, exp.Table) and source.name.lower() not in SCHEMA:
                    raise AccessDeniedError(
                        "Query references a relation outside the virtual schema."
                    )
        tree = qualify(tree, dialect="bigquery", schema=SCHEMA, allow_partial_qualification=False)
        if tree.find(exp.TableColumn):
            raise AppError("Select scalar columns, not entire table records.", code="invalid_query")
        columns = tuple(tree.named_selects)
        if (
            not columns
            or len(columns) > 30
            or len(set(columns)) != len(columns)
            or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", c) for c in columns)
        ):
            raise AppError(
                "Use at most 30 uniquely named scalar output columns.", code="invalid_query"
            )
        leaves: list[exp.Table] = []
        for scope in traverse_scope(tree):
            for source in scope.sources.values():
                if isinstance(source, exp.Table):
                    leaves.append(source)
        if not leaves:
            raise AppError(
                "Analytical queries must read the permitted data relations.", code="invalid_query"
            )
        for leaf in leaves:
            relation = leaf.name.lower()
            scoped = sqlglot.parse_one(_source_sql(relation), read="bigquery")
            leaf.replace(
                exp.Subquery(
                    this=scoped, alias=exp.TableAlias(this=exp.to_identifier(leaf.alias_or_name))
                )
            )
        # 101 is a sentinel, not silent truncation: the executor rejects >100.
        wrapped = exp.select("*").from_(tree.subquery("analysis_result")).limit(101)
        return CompiledQuery(
            sql=wrapped.sql(dialect="bigquery"),
            parameters={"all_brands": identity.ceo, "allowed_brands": list(identity.brands)},
            definitions=DEFINITIONS,
            output_columns=columns,
            allow_serialization_repair=False,
        )
    except SqlglotError:
        raise AppError(
            "SQL could not be resolved against the virtual schema. Check column names, aliases, grouping and syntax.",
            code="invalid_query",
        ) from None


def _source_sql(relation: str) -> str:
    scope = "(@all_brands OR p.brand IN UNNEST(@allowed_brands))"
    if relation == "products":
        return f"SELECT p.id AS product_id, p.brand, p.category, p.name AS product_name FROM `{DATASET}.products` p WHERE {scope}"
    status = (
        " AND oi.status NOT IN ('Cancelled', 'Returned') AND o.status NOT IN ('Cancelled', 'Returned')"
        if relation == "sales"
        else ""
    )
    return f"""SELECT oi.id AS item_id, oi.order_id, oi.user_id, oi.product_id,
        oi.sale_price, oi.created_at AS purchased_at, p.brand, p.category,
        p.name AS product_name, oi.status AS item_status, o.status AS order_status
        FROM `{DATASET}.order_items` oi
        JOIN `{DATASET}.orders` o ON o.order_id=oi.order_id AND o.user_id=oi.user_id
        JOIN `{DATASET}.products` p ON p.id=oi.product_id
        WHERE {scope}{status}"""
