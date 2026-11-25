"""Independent references, distinguishing data, and admission/isolation contracts."""

from __future__ import annotations

import ast
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation import data
from evaluation.data import (
    fixture_path,
    load_calibration,
    load_cases,
    reference_for,
    validate_case,
    validate_dataset,
)
from evaluation.models import Case, Fact
from evaluation.oracles import retail
from retail_insight.integrations.bigquery.retail import QueryGateway
from retail_insight.runtime.turn import Turn
from retail_insight.tools.analytics import DataTools


def case_named(name: str) -> Case:
    return load_cases(name)[0]


def test_pilot_admission_is_honest_and_runtime_knowledge_remains_separate():
    report = validate_dataset()
    assert report["valid"], report["errors"]
    assert report["cases"] == 43
    assert report["fixtures"] == 9
    assert report["calibration_controls"] == 40
    assert report["human_reviewed_cases"] == report["sealed_holdout"] == 0
    assert len(load_cases("smoke")) == 4
    assert len(load_cases("challenge")) == 3
    assert all(not case.provenance.human_reviewed for case in load_cases())
    assert all(case.provenance.oracle_verified for case in load_cases())
    assert "knowledge/golden" not in str(fixture_path(case_named("totals-q1")))
    with pytest.raises(ValueError, match="Unknown suite"):
        load_cases("not-a-suite")


def test_oracle_cannot_reuse_application_sql_or_gateway():
    tree = ast.parse(Path(retail.__file__).read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any(name.startswith(("retail_insight", "duckdb", "sqlglot")) for name in imports)


def test_reference_admission_rejects_mutated_fact_instead_of_relaxing_tolerance():
    case = case_named("totals-q1").model_copy(deep=True)
    reference_for(case, "turn-1").facts[0].value = "799"
    reference_for(case, "turn-1").facts[0].tolerance = Decimal("1000")
    with pytest.raises(ValueError, match="Invalid oracle fact"):
        validate_case(case)


def test_invalid_case_schema_is_reported_without_hiding_other_cases(tmp_path, monkeypatch):
    split = tmp_path / "dev"
    split.mkdir()
    case = case_named("totals-q1")
    (split / "totals-q1.json").write_text(case.model_dump_json())
    (split / "broken.json").write_text('{"id": "broken"}')
    monkeypatch.setattr(data, "GOLDEN", tmp_path)
    report = validate_dataset()
    assert report["status"] == "INVALID_CASE"
    assert report["cases"] == 1
    assert report["errors"][0]["case_id"] == "broken"


def test_reference_admission_rejects_changed_scope_or_unknown_metric():
    case = case_named("totals-q1").model_copy(deep=True)
    reference_for(case, 0).facts[0].scope = "Levi's"
    with pytest.raises(ValueError, match="scope"):
        validate_case(case)
    case = case_named("totals-q1").model_copy(deep=True)
    reference_for(case, 0).facts[0].source_key = "invented.metric"
    with pytest.raises(ValueError, match="Invalid oracle fact"):
        validate_case(case)


def test_fixture_hash_and_sql_derivation_are_both_enforced(tmp_path, monkeypatch):
    case = case_named("totals-q1")
    for suffix in (".json", ".sql"):
        (tmp_path / f"retail_v1{suffix}").write_bytes(
            retail.fixture_file("retail_v1", suffix).read_bytes()
        )
    monkeypatch.setattr(retail, "FIXTURES", tmp_path)
    fixture_path(case)
    sql = tmp_path / "retail_v1.sql"
    sql.write_text(sql.read_text().replace("250", "251", 1))
    with pytest.raises(ValueError, match="SQL fixture"):
        fixture_path(case)
    raw = tmp_path / "retail_v1.json"
    raw.write_text(raw.read_text() + "\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        fixture_path(case)


@pytest.mark.parametrize("unsafe", ["../escape", "/absolute", "case/child", "", "a\nfile"])
def test_case_ids_are_safe_artifact_names(unsafe):
    raw = case_named("totals-q1").model_dump(mode="json")
    raw["id"] = unsafe
    with pytest.raises(ValidationError):
        Case.model_validate(raw)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "not a number", None])
def test_nonfinite_or_non_numeric_references_are_rejected(value):
    with pytest.raises(ValidationError):
        Fact(id="f", value=value, source_key="q1.revenue", metric="revenue")


def test_input_whitelist_never_exposes_reference_or_environment():
    case = case_named("report-injection")
    public = case.runtime_input()
    assert set(public) == {"case_id", "identity", "steps"}
    assert "reference_answer" not in str(public)
    assert "999999" not in str(public)
    assert "fixture_sha256" not in str(public)
    assert "criteria" not in str(public)


def test_conditional_clarification_and_trusted_actions_are_explicit():
    branching = case_named("period-clarification")
    assert branching.steps[1].when_previous_outcome == ["clarification"]
    assert branching.references["turn-1"].allowed_outcomes == ["clarification"]
    assert case_named("report-delete-confirm").steps[-1].kind == "confirm_delete"
    assert case_named("report-delete-cancel").steps[-1].kind == "cancel_delete"
    assert "trusted-action" not in case_named("report-delete-confirm").references
    final = case_named("report-delete-confirm").expected_final_reports
    assert final is not None and [report.title for report in final] == ["Keep This Report"]
    cancelled = case_named("report-delete-cancel")
    assert cancelled.expected_final_reports == cancelled.initial_reports


def test_independent_hand_calculations_cover_grain_scope_status_and_boundaries():
    truth = retail.snapshot("retail_v1")
    assert {
        key: truth[f"q1.{key}"] for key in ("revenue", "items", "orders", "customers", "aov")
    } == {"revenue": "798", "items": "22", "orders": "20", "customers": "12", "aov": "39.9"}
    assert truth["q4.revenue"] == "570"
    assert Decimal(truth["change.revenue.percent"] or "0") == Decimal(40)
    # 11 extra orders / 9 baseline orders must retain Decimal precision, not float arithmetic.
    assert truth["change.orders.percent"] == str(Decimal(11) / Decimal(9) * 100)
    assert truth["jan.revenue"] == "330"
    assert truth["q2.revenue"] == "1000"
    assert truth["q1_all_status.revenue"] == str(798 + 4 * 999)
    assert truth["q1.new_customers"] == "4"
    assert retail.snapshot("retail_v1", "bob")["q1.revenue"] == "940"
    assert retail.snapshot("retail_v1", "ceo")["q1.orders"] == "21"


def test_signed_category_reconciliation_distinguishes_remainder_meaning():
    truth = retail.snapshot("retail_v1")
    assert [truth[f"category.{i}.name"] for i in (1, 2, 3)] == ["Outerwear", "Suits", "Tops"]
    components = [Decimal(truth[f"category.{i}.change"] or "0") for i in (1, 2, 3)]
    assert components == [Decimal(240), Decimal(-140), Decimal(60)]
    assert sum(components) + Decimal(truth["category.other.change"] or "0") == Decimal(228)
    assert truth["category.other_after_two.change"] == "128"
    assert truth["category.other.change"] == "68"
    assert sum(abs(value) for value in components) + Decimal(68) != Decimal(228)


def test_scope_and_repeat_purchase_metamorphic_variants():
    base = retail.snapshot("retail_v1")
    assert retail.snapshot("foreign_noise_v1") == base
    shifted = retail.snapshot("shifted_v1")
    assert shifted["q1.customers"] == base["q1.customers"]
    assert Decimal(shifted["q1.orders"] or "0") == Decimal(base["q1.orders"] or "0") + 1
    assert Decimal(shifted["q1.revenue"] or "0") == Decimal(base["q1.revenue"] or "0") + 1000
    assert shifted["rank.revenue.1.product_id"] != base["rank.revenue.1.product_id"]


def test_empty_and_zero_baseline_preserve_undefined_values():
    empty = retail.snapshot("empty_q1_v1")
    assert empty["q1.revenue"] == empty["q1.orders"] == "0"
    assert empty["q1.aov"] is None
    assert empty["rank.revenue.count"] == "0"
    zero = retail.snapshot("zero_baseline_v1")
    assert zero["q4.revenue"] == "0"
    assert zero["change.revenue.absolute"] == "798"
    assert zero["change.revenue.percent"] is None


@pytest.mark.parametrize(
    "defect", ["duplicate_item", "owner_mismatch", "missing_product", "extra_column"]
)
def test_raw_fixture_admission_rejects_broken_identity_or_schema(defect):
    raw = deepcopy(retail.load_fixture("retail_v1"))
    if defect == "duplicate_item":
        raw["items"].append(dict(raw["items"][0]))
    elif defect == "owner_mismatch":
        raw["items"][0]["user_id"] = 9999
    elif defect == "missing_product":
        raw["items"][0]["product_id"] = 9999
    else:
        raw["items"][0]["secret"] = "not in schema"
    with pytest.raises(ValueError):
        retail.validate_rows(raw)


@pytest.mark.parametrize(
    "fixture,identity",
    [
        ("retail_v1", "alice"),
        ("retail_v1", "bob"),
        ("retail_v1", "ceo"),
        ("shifted_v1", "alice"),
        ("empty_q1_v1", "alice"),
        ("zero_baseline_v1", "alice"),
        ("foreign_noise_v1", "alice"),
        ("injection_v1", "alice"),
        ("nullable_v1", "alice"),
        ("zero_net_v1", "alice"),
        ("paged_results_v1", "alice"),
    ],
)
async def test_real_gateway_denotation_matches_independent_reference(fixture, identity):
    gateway = QueryGateway(
        retail.SCOPES[identity],
        backend="fixture",
        fixture_path=retail.fixture_file(fixture, ".sql"),
    )
    result = await gateway.query("""SELECT COALESCE(SUM(sale_price), 0) AS revenue,
        COUNT(*) AS items, COUNT(DISTINCT order_id) AS orders,
        COUNT(DISTINCT user_id) AS customers,
        SUM(sale_price) / NULLIF(COUNT(DISTINCT order_id), 0) AS aov
        FROM sales WHERE purchased_at >= TIMESTAMP('2026-01-01')
        AND purchased_at < TIMESTAMP('2026-04-01')""")
    observed = result["rows"][0]
    truth = retail.snapshot(fixture, identity)
    for key, actual in observed.items():
        expected = truth[f"q1.{key}"]
        if expected is None:
            assert actual is None
        else:
            assert abs(Decimal(str(actual)) - Decimal(expected)) < Decimal("0.0000001")


@pytest.mark.parametrize(
    "sql,reference_key",
    [
        (
            "SELECT COUNT(user_id) AS value FROM sales WHERE purchased_at >= TIMESTAMP('2026-01-01') AND purchased_at < TIMESTAMP('2026-04-01')",
            "q1.customers",
        ),
        (
            "SELECT SUM(sale_price) / COUNT(*) AS value FROM sales WHERE purchased_at >= TIMESTAMP('2026-01-01') AND purchased_at < TIMESTAMP('2026-04-01')",
            "q1.aov",
        ),
        (
            "SELECT SUM(sale_price) AS value FROM transactions WHERE item_status NOT IN ('Cancelled', 'Returned') AND purchased_at >= TIMESTAMP('2026-01-01') AND purchased_at < TIMESTAMP('2026-04-01')",
            "q1.revenue",
        ),
        (
            "SELECT SUM(sale_price) AS value FROM transactions WHERE order_status NOT IN ('Cancelled', 'Returned') AND purchased_at >= TIMESTAMP('2026-01-01') AND purchased_at < TIMESTAMP('2026-04-01')",
            "q1.revenue",
        ),
        (
            "SELECT SUM(sale_price) AS value FROM sales WHERE purchased_at >= TIMESTAMP('2026-01-01') AND purchased_at <= TIMESTAMP('2026-04-01')",
            "q1.revenue",
        ),
    ],
)
async def test_distinguishing_fixture_rejects_semantically_wrong_sql(sql, reference_key):
    gateway = QueryGateway(
        retail.SCOPES["alice"],
        backend="fixture",
        fixture_path=retail.fixture_file("retail_v1", ".sql"),
    )
    result = await gateway.query(sql)
    assert Decimal(str(result["rows"][0]["value"])) != Decimal(
        retail.snapshot("retail_v1")[reference_key] or "0"
    )


def test_calibration_families_are_split_together_and_claim_spans_are_real():
    controls = load_calibration()
    assert len(controls) == 40
    family_splits: dict[str, set[str]] = {}
    for control in controls:
        family_splits.setdefault(control["family"], set()).add(control["split"])
        assert control["human_reviewed"] is False
        assert control["code_verified"] is True
        assert all(claim["span"] in control["answer"] for claim in control["expected_claims"])
    assert all(len(splits) == 1 for splits in family_splits.values())
    assert len(family_splits) == 20
    for family in family_splits:
        assert {
            control["expected_pass"] for control in controls if control["family"] == family
        } == {True, False}


def test_sql_null_aggregates_keep_unknown_prices_distinct_from_empty_activity():
    assert retail.sql_sum([]) is None
    assert retail.sql_sum([None, None]) is None
    assert retail.sql_sum([Decimal("1.25"), None, Decimal("2.75")]) == Decimal("4.00")
    totals = retail.totals([{"price": None, "order_id": 1, "user_id": 1}])
    assert totals["revenue"] is totals["sql_revenue"] is totals["aov"] is None
    assert totals["items"] == totals["orders"] == totals["customers"] == 1
    assert totals["priced_items"] == 0
    assert totals["null_price_items"] == 1
    assert retail.totals([])["revenue"] == 0
    assert retail.totals([])["sql_revenue"] is None


async def test_nullable_rows_match_sql_three_valued_status_and_sum_semantics():
    gateway = QueryGateway(
        retail.SCOPES["alice"],
        backend="fixture",
        fixture_path=retail.fixture_file("nullable_v1", ".sql"),
    )
    period = "purchased_at >= TIMESTAMP('2026-01-01') AND purchased_at < TIMESTAMP('2026-04-01')"
    result = await gateway.query(
        f"SELECT COUNT(*) AS items, COUNT(sale_price) AS priced_items FROM sales WHERE {period}"
    )
    assert result["rows"] == [{"items": 23, "priced_items": 22}]
    missing = await gateway.query(
        f"SELECT COUNT(*) AS items, SUM(sale_price) AS revenue FROM sales WHERE sale_price IS NULL AND {period}"
    )
    assert missing["rows"] == [{"items": 1, "revenue": None}]
    # Treating NULL statuses as Complete is a distinguishing semantic defect.
    mutation = await gateway.query(
        f"SELECT SUM(sale_price) AS revenue FROM transactions WHERE {period} AND COALESCE(item_status, 'Complete') NOT IN ('Cancelled', 'Returned') AND COALESCE(order_status, 'Complete') NOT IN ('Cancelled', 'Returned')"
    )
    assert mutation["rows"][0]["revenue"] == 30798
    assert retail.snapshot("nullable_v1")["q1.revenue"] == "798"


async def test_zero_net_category_fixture_has_nonzero_offsetting_denotations():
    gateway = QueryGateway(
        retail.SCOPES["alice"],
        backend="fixture",
        fixture_path=retail.fixture_file("zero_net_v1", ".sql"),
    )
    result = await gateway.query("""SELECT category,
        SUM(CASE WHEN purchased_at >= TIMESTAMP('2026-01-01') THEN sale_price ELSE -sale_price END) AS change
        FROM sales WHERE purchased_at >= TIMESTAMP('2025-10-01') AND purchased_at < TIMESTAMP('2026-04-01')
        GROUP BY category ORDER BY ABS(change) DESC, category ASC""")
    truth = retail.snapshot("zero_net_v1")
    for rank, row in enumerate(result["rows"], 1):
        assert row["category"] == truth[f"category.{rank}.name"]
        assert Decimal(str(row["change"])) == Decimal(truth[f"category.{rank}.change"] or "0")
    changes = [Decimal(str(row["change"])) for row in result["rows"]]
    assert sum(changes) == 0
    assert all(change != 0 for change in changes)
    assert sum(changes[3:]) == Decimal(50)
    assert truth["change.revenue.percent"] == "0"


async def test_all_25_ranking_rows_are_solvable_through_real_bounded_tool_pages(make_agent):
    case = case_named("complete-result-pagination")
    app = make_agent(fixture_path=fixture_path(case))
    tools = DataTools(Turn(app, case.steps[0].message))
    preview = await tools.query_data(
        """SELECT product_id, SUM(sale_price) AS revenue FROM sales
        WHERE purchased_at >= TIMESTAMP('2026-01-01') AND purchased_at < TIMESTAMP('2026-04-01')
        GROUP BY product_id ORDER BY revenue DESC, product_id ASC""",
        "Rank every qualifying Q1 product by revenue",
    )
    assert preview["preview_only"] is True
    assert preview["stored_rows"] == 25
    assert len(preview["rows"]) == 20
    tail = await tools.read_result(preview["id"], offset=20, limit=20)
    assert len(tail["rows"]) == 5
    assert tail["preview_only"] is False
    assert tail["parents"] == [preview["id"]]
    assert not {row["product_id"] for row in preview["rows"]} & {
        row["product_id"] for row in tail["rows"]
    }
    truth = retail.snapshot(case.fixture)
    for rank, row in enumerate([*preview["rows"], *tail["rows"]], 1):
        assert str(row["product_id"]) == truth[f"ranking.revenue.{rank}.product_id"]
        assert Decimal(str(row["revenue"])) == Decimal(
            truth[f"ranking.revenue.{rank}.revenue"] or "0"
        )


@pytest.mark.parametrize(
    "case_id,step_id,requested_phrases,required_keys",
    [
        (
            "unsupported-cause",
            "turn-1",
            ("revenue in each quarter", "absolute and percentage change"),
            {"q4.revenue", "q1.revenue", "change.revenue.absolute", "change.revenue.percent"},
        ),
        (
            "new-returning",
            "turn-1",
            ("both counts", "total distinct customers"),
            {"q1.new_customers", "q1.returning_customers", "q1.customers"},
        ),
        (
            "false-churn-spike",
            "turn-1",
            ("eligible count", "inactive count", "rate at each date"),
            {
                f"inactivity.{date}.{metric}"
                for date in ("start", "end")
                for metric in ("eligible", "inactive", "percent")
            },
        ),
        (
            "ranking-overlap",
            "turn-2",
            ("overlap count", "product ids", "at most 100 words"),
            {
                "overlap.count",
                "overlap.1.product_id",
                "overlap.2.product_id",
                "overlap.3.product_id",
            },
        ),
        (
            "category-summary",
            "turn-3",
            ("absolute and percentage revenue growth", "outerwear and suits", "combined remainder"),
            {
                "change.revenue.absolute",
                "change.revenue.percent",
                "category.1.change",
                "category.2.change",
                "category.other_after_two.change",
            },
        ),
    ],
)
def test_required_facts_have_explicit_requests_in_repaired_cases(
    case_id, step_id, requested_phrases, required_keys
):
    """Prevent regressions to mandatory grading of merely optional/unasked content."""
    case = case_named(case_id)
    prompt = next(step.message.casefold() for step in case.steps if step.id == step_id)
    assert all(phrase in prompt for phrase in requested_phrases)
    assert {fact.source_key for fact in case.references[step_id].facts} == required_keys
    if case_id == "category-summary":
        assert "if you group" not in prompt


def test_quarter_boundary_criterion_does_not_demand_an_unasked_date_explanation():
    case = case_named("quarter-boundary")
    assert "april 1" in case.steps[0].message.casefold()
    assert all(
        "july" not in criterion.description.casefold()
        for criterion in case.references["turn-1"].criteria
    )
