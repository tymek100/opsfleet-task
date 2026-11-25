"""Independent truth, tie choices, grounding, unresolved work and reference integrity."""

from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest

from evaluation.conversation_references import Snapshot, bundle, reference_for
from evaluation.graders.conversations import grade_conversation, resolve_selections
from evaluation.graders.judge import JudgeUnavailable, judge_input
from evaluation.manual_reference import queries, summarize
from evaluation.results import Claim, CriterionFinding, ExtractedFact, Judgment, TurnRecord
from evaluation.runners.artifacts import digest, read_json, write_json
from evaluation.runners.authored import final_summary
from evaluation.runners.manual import load_scenarios
from retail_insight.integrations.bigquery.retail import QueryGateway, compile_query
from tests.evaluation.test_manual_reference import item


@pytest.fixture
def snapshot(tmp_path):
    rows = [
        item(i, i, i, str(price), "2026-02-01T00:00:00+00:00", product=i, category=f"Category {i}")
        for i, price in enumerate((100, 90, 80, 70, 60, 30, 50), 1)
    ]
    rows.append(item(8, 6, 6, "30", "2026-02-01T00:00:00+00:00", product=6, category="Category 6"))
    products = [
        {k: r[k] for k in ("product_id", "product_name", "brand", "category")} for r in rows[:7]
    ]
    directory = tmp_path / "reference"
    data = {
        "transactions.json": rows,
        "products.json": products,
        "states.json": [],
        "summary.json": summarize(rows, products, []),
    }
    from evaluation.conversation_references import clean

    for name, value in data.items():
        write_json(directory / name, clean(value))
    write_json(
        directory / "manifest.json",
        {
            "status": "completed",
            "brands": ["Calvin Klein", "Levi's"],
            "created_at": "2026-11-22T00:00:00+00:00",
            "snapshot_at": "2026-11-22T00:00:00+00:00",
            "source_dataset": "bigquery-public-data.thelook_ecommerce",
            "point_in_time_consistent": True,
            "files_sha256": {name: digest(directory / name) for name in data},
        },
    )
    return Snapshot.load(directory)


@pytest.fixture
def scenarios():
    return {s.id: s for s in load_scenarios(Path("evaluation/scenarios/manual_20.json"))}


def judgment(facts=(), criteria=(), claims=()):
    return Judgment(
        facts=list(facts),
        criteria=list(criteria),
        claims=list(claims),
        response_kind="substantive",
        coverage_complete=True,
    )


def test_all_twenty_cases_have_two_independent_reference_records(snapshot, scenarios):
    definitions = bundle(list(scenarios.values()), snapshot)
    assert len(definitions["cases"]) == 20
    assert all(set(c) == {"turn-1", "turn-2"} for c in definitions["cases"].values())
    revenue = reference_for(scenarios["scenario-15"], 1, snapshot).reference.facts[0]
    assert revenue.value == "510"
    hypothetical = reference_for(scenarios["scenario-15"], 2, snapshot).reference.facts[0]
    assert hypothetical.value == "469.20"
    empty = reference_for(scenarios["scenario-13"], 2, snapshot).reference.facts[0]
    assert empty.value is None and empty.value_type == "null"


def test_tied_product_selection_binds_its_own_units_and_price(snapshot, scenarios):
    spec = reference_for(scenarios["scenario-04"], 1, snapshot)
    facts = [
        ExtractedFact(id=f"products_{rank}_entity", value=str(product), span=f"Product {product}")
        for rank, product in enumerate((1, 2, 3, 4, 6), 1)
    ]
    resolved, selected, scores = resolve_selections(spec, judgment(facts=facts))
    assert selected["products"] == ["1", "2", "3", "4", "6"]
    assert all(s.status == "PASS" for s in scores)
    expected = {f.id: f.value for f in resolved.facts}
    assert expected["products_5_units"] == "2"
    assert expected["products_5_average_realized_unit_price"] == "30"
    follow_up = reference_for(scenarios["scenario-04"], 2, snapshot, initial=selected)
    assert follow_up.selections[0]["rows"][-1]["key"] == "6"
    assert follow_up.selections[0]["rows"][-1]["metrics"]["aov"] == "60"


def test_duplicate_or_lower_ranked_product_cannot_pass(snapshot, scenarios):
    spec = reference_for(scenarios["scenario-04"], 1, snapshot)
    facts = [
        ExtractedFact(id=f"products_{rank}_entity", value=str(product), span=f"Product {product}")
        for rank, product in enumerate((1, 2, 3, 4, 4), 1)
    ]
    _, _, scores = resolve_selections(spec, judgment(facts=facts))
    assert scores[-1].status == "FAIL"


def test_followup_keeps_the_selected_set_without_inventing_an_order_requirement(
    snapshot, scenarios
):
    spec = reference_for(
        scenarios["scenario-04"], 2, snapshot, initial={"products": ["1", "2", "3", "4", "6"]}
    )
    facts = [
        ExtractedFact(id=f"products_{rank}_entity", value=str(product), span=f"Product {product}")
        for rank, product in enumerate((6, 4, 3, 2, 1), 1)
    ]
    reference, _, scores = resolve_selections(spec, judgment(facts=facts))
    assert all(s.status == "PASS" for s in scores)
    assert next(f for f in reference.facts if f.id == "products_1_aov").value == "60"


async def test_provider_failure_is_unresolved_and_does_not_call_judges(snapshot, scenarios):
    class ForbiddenJudge:
        version: ClassVar = {"model": "forbidden"}

        async def evaluate(self, *args):
            raise AssertionError("Do not spend judge credits when no answer exists")

        async def evaluate_trajectory(self, *args):
            raise AssertionError("Do not grade an unavailable provider as a reasoning error")

    turns = [TurnRecord(step_id=f"turn-{n}", status="unavailable") for n in (1, 2)]
    result = await grade_conversation(scenarios["scenario-15"], turns, snapshot, ForbiddenJudge())
    assert result["status"] == "ERROR"
    assert all(t["status"] == "ERROR" for t in result["turns"])
    assert final_summary([result], 1)["exit_code"] == 2


def test_reference_hash_and_recalculation_are_both_checked(snapshot):
    path = snapshot.directory / "summary.json"
    value = read_json(path)
    value["Calvin Klein"]["qualifying"]["q1_2026"]["revenue"] = "999999"
    write_json(path, value)
    with pytest.raises(ValueError, match="changed"):
        Snapshot.load(snapshot.directory)
    manifest = read_json(snapshot.directory / "manifest.json")
    manifest["files_sha256"]["summary.json"] = digest(path)
    write_json(snapshot.directory / "manifest.json", manifest)
    with pytest.raises(ValueError, match="does not match"):
        Snapshot.load(snapshot.directory)


def test_extraction_judge_never_receives_expected_values_or_selection_catalogs(snapshot, scenarios):
    spec = reference_for(scenarios["scenario-04"], 1, snapshot)
    payload = judge_input(
        TurnRecord(step_id="turn-1", prompt="Rank products", status="approved", markdown="Unknown"),
        spec.reference,
        [],
    )
    assert all(
        "value" not in f and "source_key" not in f and "tolerance" not in f
        for f in payload["trusted"]["fact_bindings"]
    )
    assert "selection_rules" not in payload and "reference_answer" not in payload["trusted"]


async def test_supported_but_wrong_number_fails_independent_reference(snapshot, scenarios):
    class ControlledJudge:
        version: ClassVar = {"model": "controlled"}

        async def evaluate(self, turn, reference, prior):
            return judgment(
                facts=[
                    ExtractedFact(
                        id=reference.facts[0].id,
                        value="999" if turn.step_id == "turn-1" else "469.20",
                        span=turn.markdown,
                    )
                ],
                claims=[
                    Claim(
                        span=turn.markdown,
                        label="SUPPORTED",
                        evidence_ids=["E1"],
                        reason="The observed SQL result agrees.",
                    )
                ],
                criteria=[
                    CriterionFinding(id=c.id, passed=True, finding="Controlled semantic pass")
                    for c in reference.criteria
                    if c.kind == "semantic"
                ],
            )

    turns = [
        TurnRecord(
            step_id=f"turn-{i}",
            status="approved",
            outcome="answer",
            markdown=text,
            context={"evidence": [{"id": "E1"}]},
        )
        for i, text in enumerate(("Revenue: 999.", "Hypothetical EUR: 469.20."), 1)
    ]
    result = await grade_conversation(
        scenarios["scenario-15"], turns, snapshot, ControlledJudge(), trajectory_enabled=False
    )
    assert result["status"] == "FAIL"
    scores = {s["name"]: s["status"] for s in result["turns"][0]["scores"]}
    assert scores["numeric_fact"] == "FAIL" and scores["claim_support"] == "PASS"
    assert result["turns"][1]["status"] == "PASS"


async def test_judge_failure_stays_unresolved(snapshot, scenarios):
    class Unavailable:
        version: ClassVar = {"model": "unavailable"}

        async def evaluate(self, *args):
            raise JudgeUnavailable("Judge budget exhausted")

    turns = [
        TurnRecord(
            step_id=f"turn-{n}", status="approved", outcome="answer", markdown="Revenue 510."
        )
        for n in (1, 2)
    ]
    result = await grade_conversation(
        scenarios["scenario-15"], turns, snapshot, Unavailable(), trajectory_enabled=False
    )
    assert result["status"] == "ERROR"
    assert final_summary([result], 1)["exit_code"] == 2


def test_same_snapshot_applies_to_every_physical_relation_and_reference_query():
    timestamp = datetime(2026, 11, 22, tzinfo=UTC)
    sql = compile_query(
        "SELECT SUM(s.sale_price) FROM sales s JOIN products p USING(product_id)",
        ("Calvin Klein",),
        snapshot_at=timestamp,
    )
    assert sql.count("FOR SYSTEM_TIME AS OF") == 4
    assert "2026-11-22T00:00:00+00:00" in sql
    references = queries("bigquery-public-data.thelook_ecommerce", timestamp)
    assert references["states"].count("FOR SYSTEM_TIME AS OF") == 4
    assert references["transactions"].count("FOR SYSTEM_TIME AS OF") == 3
    with pytest.raises(ValueError, match="timezone"):
        compile_query("SELECT * FROM products", (), snapshot_at=datetime(2026, 11, 22))


async def test_geography_uses_the_same_snapshot_without_changing_privacy(monkeypatch):
    gateway = QueryGateway(("Calvin Klein",), snapshot_at=datetime(2026, 11, 22, tzinfo=UTC))
    captured = []

    async def execute(sql, logical, timeout):
        captured.append(sql)
        return {"rows": []}

    monkeypatch.setattr(gateway, "_warehouse", execute)
    await gateway.state_summary("2026-01-01", "2026-04-01")
    assert captured[0].count("FOR SYSTEM_TIME AS OF") == 4
    assert "HAVING COUNT(DISTINCT i.user_id) >= 5" in captured[0]
