"""Independent oracle, leakage and shared evaluation admission contracts."""

import asyncio
import copy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from evaluation.multi_agent.build_fixture import build, retail_sql
from evaluation.multi_agent.grading import evidence_ids, turn_record
from evaluation.multi_agent.oracle import Snapshot, background, reference
from evaluation.multi_agent.publication import dataset_rows
from evaluation.multi_agent.runner import RunBudget, cost_of, validate_deployment
from evaluation.multi_agent.scenarios import load_suites


def values(snapshot, topic, identity="workspace"):
    return {f.metric: f.value for f in snapshot.calculate(topic, identity)}


def test_fixture_is_frozen_and_runtime_demo_data_is_independent():
    snapshot = Snapshot.load(Path("evaluation/multi_agent/fixture.json"))
    assert snapshot.raw == build()
    assert Path("evaluation/multi_agent/retail_fixture.sql").read_text() == retail_sql(build())
    demo = Path("src/retail_insight/integrations/bigquery/retail_demo.sql").read_text()
    assert "Evaluation linen shirt" not in demo


def test_stock_boundary_and_null_cost_truth():
    snapshot = Snapshot(build())
    assert values(snapshot, "stock_totals") == {
        "modeled unsold units": "45",
        "recorded cost of units with non-null cost": "729.00",
        "distinct stocked products": "8",
    }
    assert (
        values(snapshot, "future_created")[
            "inventory rows created after cutoff, excluded from stock"
        ]
        == "1"
    )
    assert (
        values(snapshot, "sold_boundary")["rows sold exactly at cutoff, excluded from stock"] == "1"
    )
    assert values(snapshot, "sold_later")["stocked units with recorded sale after cutoff"] == "8"
    assert values(snapshot, "missing_cost")["stocked units with missing recorded cost"] == "7"


def test_complete_day_aging_excludes_fractional_ninetieth_day():
    raw = build()
    baseline = Snapshot(raw)
    for offset, age in enumerate((90, 90.5, 91)):
        raw["inventory_items"].append(
            {
                "id": 880001 + offset,
                "product_id": 710,
                "created_at": (baseline.as_of - timedelta(days=age)).isoformat(),
                "sold_at": None,
                "cost": "2.00",
                "product_distribution_center_id": 1,
            }
        )
    changed = Snapshot(raw)
    assert values(baseline, "aged")["modeled unsold units"] == "17"
    assert values(changed, "aged")["modeled unsold units"] == "18"
    assert values(changed, "aged")["recorded cost of units with non-null cost"] == "329.25"
    before = {f.entity: Decimal(f.value) for f in baseline.calculate("center_age")}
    after = {f.entity: Decimal(f.value) for f in changed.calculate("center_age")}
    assert sum(after.values()) == sum(before.values()) + 1
    assert after["Memphis TN"] == before["Memphis TN"] + 1


def test_sales_exclude_both_statuses_and_use_all_calendar_days():
    snapshot = Snapshot(build())
    assert values(snapshot, "sales_total")["qualifying units over 30 complete days"] == "26"
    assert len(snapshot.sales("workspace")) == 26
    coverage = snapshot.calculate("coverage")
    shirt = next(f for f in coverage if f.entity.startswith("product 710 "))
    assert Decimal(shirt.value) == Decimal(10) * 30 / 7


def test_all_brand_oracle_includes_rows_from_every_brand():
    source = build()
    baseline = Snapshot(source).calculate("stock_totals")
    changed = copy.deepcopy(source)
    foreign = next(r for r in changed["inventory_items"] if r["product_id"] == 718)
    for i in range(20):
        changed["inventory_items"].append({**foreign, "id": 80000 + i, "cost": "999999.99"})
    assert Snapshot(changed).calculate("stock_totals") != baseline
    assert Snapshot(changed).calculate("stock_totals", "workspace") != Snapshot(source).calculate(
        "stock_totals", "workspace"
    )


def test_unit_grain_and_unknown_centers_reconcile():
    source = build()
    source["inventory_items"].append(copy.deepcopy(source["inventory_items"][0]))
    snapshot = Snapshot(source)
    assert values(snapshot, "stock_totals")["modeled unsold units"] == "45"
    facts = snapshot.calculate("center_all")
    assert sum(Decimal(f.value) for f in facts[:-1]) == Decimal(facts[-1].value)
    assert any(f.entity == "Unknown" and Decimal(f.value) > 0 for f in facts)
    products = snapshot.calculate("center_products")
    assert sum(Decimal(f.value) for f in products[:-1]) > Decimal(products[-1].value)


def test_each_suite_has_twenty_two_turn_tasks_and_actual_references():
    snapshot = Snapshot(build())
    for role, cases in load_suites().items():
        assert [c["id"] for c in cases] == [f"scenario-{i:02d}" for i in range(1, 21)]
        assert len({c["question"] for c in cases}) == 20
        for row, case in zip(dataset_rows(role, cases, snapshot), cases, strict=True):
            assert set(row["output"]["turns"]) == {"turn-1", "turn-2"}
            assert row["output"]["provenance"]["human_reviewed"] is False
            assert "facts" not in row["input"] and "reference" not in row["input"]
            for turn in (1, 2):
                ref = reference(snapshot, case, turn)
                assert ref.reference_answer and ref.criteria
                assert len({f.id for f in ref.facts}) == len(ref.facts)


def test_namespaced_single_and_plural_evidence_ids_are_recognized():
    assert evidence_ids(
        {
            "id": "inventory:E1",
            "evidence_id": "distribution:E3",
            "evidence_ids": ["retail:E2"],
            "rows": [{"id": "not_evidence"}],
        }
    ) == {"inventory:E1", "distribution:E3", "retail:E2"}


def test_answer_judge_receives_published_answer_and_evidence_not_superseded_drafts():
    import json

    from evaluation.graders.judge import judge_input
    from evaluation.models import TurnReference

    raw = {
        "status": "approved",
        "markdown": "There are 32 modeled unsold units.",
        "evidence": [{"id": "E-prior", "rows": [{"units": 32}]}],
        "observations": [
            {"event": "initial_context", "context": {"scope": "Calvin Klein"}},
            {"event": "tool_observation", "name": "query_data", "result": {"id": "E-new"}},
            {"event": "tool_call", "name": "finish_answer", "args": {"markdown": "BAD-DRAFT 26"}},
            {"event": "tool_observation", "name": "finish_answer", "result": "BAD-DRAFT 26"},
            {"event": "answer_candidate", "candidate": {"markdown": "BAD-DRAFT 26"}},
            {"event": "review_result", "review": "BAD-DRAFT 26 approved"},
            {"event": "turn_result", "result": {"markdown": "BAD-DRAFT 26"}},
        ],
        "trace": [{"event": "review_result", "review": "BAD-DRAFT 26 approved"}],
    }
    original = copy.deepcopy(raw)
    turn = turn_record(raw, "Count our stock.", 1, [])
    payload = judge_input(turn, TurnReference(reference_answer="32 modeled unsold units."), [])
    serialized = json.dumps(payload)
    assert "BAD-DRAFT" not in serialized
    assert payload["untrusted"]["answer"] == raw["markdown"]
    assert {"E-prior", "E-new"} <= evidence_ids(turn.observations)
    assert "Calvin Klein" in serialized
    assert raw == original and turn.trace == raw["trace"]


def test_concurrent_budget_reservations_wait_then_settle_actual_usage():
    async def exercise():
        budget = RunBudget(2)
        assert await budget.reserve(1.5)
        waiting = asyncio.create_task(budget.reserve(1.5))
        await asyncio.sleep(0)
        assert not waiting.done()
        await budget.settle(1.5, 0.1)
        assert await waiting
        assert budget.reserved == 1.5
        await budget.settle(1.5, None)
        assert budget.used == pytest.approx(1.6)
        assert not await budget.reserve(0.5)

    asyncio.run(exercise())


def test_unknown_usage_is_not_treated_as_free():
    assert cost_of({"usage": {}}) is None
    assert cost_of({"usage": {"accounted_usd": 0.25}}) == 0.25


def test_multiagent_trajectory_contract_supports_judge_trace_rendering():
    from evaluation.graders.judge import _trace_summary
    from evaluation.multi_agent.trajectory import Trajectory

    result = Trajectory(findings=[], coverage_complete=False)
    summary = _trace_summary(
        {
            "status": "completed",
            "kind": "trajectory",
            "resolved_judgment": result.model_dump(mode="json"),
        }
    )
    assert "Coverage complete: False" in summary


def test_optional_claim_truth_includes_nonranked_entities_without_required_output():
    snapshot = Snapshot(build())
    truth = background(snapshot, "workspace")
    product = next(p for p in truth["products"] if p["product_id"] == 714)
    assert product["modeled_unsold_units"] == 3
    assert any(p["product_id"] == 718 for p in truth["products"])
    follow = reference(snapshot, load_suites()["coordinator"][0], 2)
    assert not follow.facts
    assert any(
        c.id == "optional-claim-truth" and c.options["independent_facts"]["products"]
        for c in follow.criteria
    )


def test_cached_background_preserves_exact_truth_and_isolates_consumers(monkeypatch):
    import evaluation.multi_agent.oracle as oracle

    raw = build()
    snapshot = Snapshot(raw)
    expected = oracle._calculate_background(snapshot, "workspace")
    calls = []
    calculate = oracle._calculate_background

    def tracked(source, identity):
        calls.append(identity)
        return calculate(source, identity)

    monkeypatch.setattr(oracle, "_calculate_background", tracked)
    first = background(snapshot, "workspace")
    assert first == expected
    first["products"].clear()
    raw["inventory_items"].clear()
    assert background(snapshot, "workspace") == expected
    assert calls == ["workspace"]
    assert background(snapshot, "workspace")["total"]["modeled_unsold_units"] == 45
    assert calls == ["workspace"]


def test_trajectory_judge_event_choices_are_limited_to_captured_occurrences():
    from evaluation.multi_agent.trajectory import response_schema

    schema = response_schema({"turn-1:event-2", "turn-1:outcome"})
    choices = schema["$defs"]["Finding"]["properties"]["event_ids"]["items"]["enum"]
    assert choices == ["turn-1:event-2", "turn-1:outcome"]
    assert response_schema([])["$defs"]["Finding"]["properties"]["event_ids"]["maxItems"] == 0


def test_wrong_fixture_or_backend_is_rejected_before_agent_execution():
    health = {
        "inventory": {
            "role": "inventory",
            "status": "ok",
            "backend": "fixture",
            "fixture_sha256": "wrong",
        }
    }
    with pytest.raises(ValueError, match="source differs"):
        validate_deployment(health, "fixture", {"inventory": "expected"})
    health["inventory"]["fixture_sha256"] = "expected"
    validate_deployment(health, "fixture", {"inventory": "expected"})
    with pytest.raises(ValueError, match="backend"):
        validate_deployment(health, "bigquery", {})


def test_inventory_scope_follow_up_requires_only_requested_metrics():
    snapshot = Snapshot(build())
    ref = reference(snapshot, load_suites()["inventory"][14], 2)
    assert {f.metric for f in ref.facts} == {
        "modeled unsold units",
        "recorded cost of units with non-null cost",
    }


def test_large_optional_catalog_keeps_asserted_prior_and_required_entities():
    from evaluation.models import Criterion, Fact, TurnReference
    from evaluation.multi_agent.reference_context import bounded_reference

    catalog = [
        {"product_id": 10000 + i, "product_name": f"Distinct named product {i}"} for i in range(150)
    ]
    ref = TurnReference(
        facts=[Fact(id="f1", value="2", source_key="test", metric="units", entity="product 10045")],
        criteria=[
            Criterion(
                id="truth",
                kind="semantic",
                description="Check optional assertions",
                options={"independent_facts": {"products": catalog, "total": {"units": 999}}},
            )
        ],
        reference_answer="Reference",
    )
    selected = bounded_reference(
        ref, "Product 10003 has two units", [{"answer": "Previously selected product 10008"}]
    )
    truth = selected.criteria[0].options["independent_facts"]
    assert {p["product_id"] for p in truth["products"]} == {10003, 10008, 10045}
    assert truth["total"] == {"units": 999}
    assert (
        selected.facts == ref.facts
        and len(ref.criteria[0].options["independent_facts"]["products"]) == 150
    )
