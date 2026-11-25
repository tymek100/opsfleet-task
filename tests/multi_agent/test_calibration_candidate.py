import copy
import json
from pathlib import Path

import pytest

from evaluation.multi_agent.calibration_candidate import (
    CONTROLS,
    build_controls,
    candidate_reference,
    independent_totals,
    run,
)
from evaluation.multi_agent.semantic_contracts import ATOMIC_CRITERIA

CUTOFF = "2026-04-01T00:00:00+00:00"


def source():
    def item(item_id, product=1, center: int | None = 1, cost: str | None = "2.50", **values):
        return {
            "id": item_id,
            "product_id": product,
            "created_at": "2026-01-01T00:00:00Z",
            "sold_at": None,
            "product_distribution_center_id": center,
            "cost": cost,
            **values,
        }

    return {
        "products": [
            {"id": 1, "brand": "Calvin Klein"},
            {"id": 2, "brand": "Calvin Klein"},
            {"id": 3, "brand": "Levi's"},
        ],
        "distribution_centers": [{"id": 1}, {"id": 2}],
        "inventory_items": [
            item(1),
            item(1),  # Counts and costs use distinct inventory IDs.
            item(2, center=999, cost=None),
            item(3, center=None, sold_at="2026-04-02T00:00:00Z"),
            item(4, created_at=None),
            item(5, sold_at=CUTOFF),
            item(6, created_at="2026-04-02T00:00:00Z"),
            item(7, product=3, cost="99.00"),
        ],
    }


def frozen_reference():
    return {
        "facts": [],
        "criteria": [],
        "reference_answer": "Only answer what is supported by available records.",
    }


def test_totals_preserve_scope_population_unknown_and_cutoff():
    totals = independent_totals(source(), "workspace", CUTOFF)
    assert totals["global_modeled_units_including_unknown"] == 4
    assert totals["known_center_modeled_units"] == 2
    assert totals["unknown_center_modeled_units"] == 2
    assert totals["known_recorded_stock_cost"] == "104.00"
    assert totals["units_with_missing_cost"] == 1
    assert totals["distinct_stocked_products"] == 2
    assert totals["distinct_catalog_products"] == 3
    assert totals["recognized_center_directory_count"] == 2
    assert totals["recognized_centers_with_scoped_stock"] == 1
    assert totals["distinct_recorded_nonnull_item_center_ids"] == 2
    assert totals["unmatched_nonnull_item_center_ids"] == [999]


def test_candidate_reference_does_not_change_frozen_reference_or_require_extra_facts():
    frozen = frozen_reference()
    before = copy.deepcopy(frozen)
    candidate = candidate_reference(frozen, independent_totals(source(), "workspace", CUTOFF))
    assert frozen == before
    assert candidate.facts == []
    assert len(candidate.criteria) == len(ATOMIC_CRITERIA)
    assert len({c.id for c in candidate.criteria}) == len(ATOMIC_CRITERIA)
    assert "NOT required" in next(
        c.description for c in candidate.criteria if c.id == "domain-global-reconciliation-v3"
    )


def test_pairs_change_only_answer_and_leave_baseline_files_untouched(tmp_path):
    scenarios = {"inventory": [], "distribution": []}
    references = {"inventory": {}, "distribution": {}}
    for control in CONTROLS:
        role, scenario, turn = control["role"], control["scenario"], control["turn"]
        if not any(c["id"] == scenario for c in scenarios[role]):
            scenarios[role].append(
                {
                    "id": scenario,
                    "identity": "workspace",
                    "question": "Initial?",
                    "follow_up": "Follow-up?",
                }
            )
        references[role].setdefault(scenario, {})[f"turn-{turn}"] = frozen_reference()
        directory = tmp_path / role / scenario
        directory.mkdir(parents=True, exist_ok=True)
        raw = {
            "as_of": CUTOFF,
            "markdown": "\n".join(before for before, _ in control["repairs"]),
            "evidence": [{"id": "E1", "rows": [{"units": 3}]}],
        }
        (directory / f"turn-{turn}.json").write_text(json.dumps(raw))
        if turn == 2 and not (directory / "turn-1.json").exists():
            (directory / "turn-1.json").write_text(json.dumps({"markdown": "Previous answer"}))
    for name, value in [
        ("snapshot", source()),
        ("scenarios", scenarios),
        ("references", references),
    ]:
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    original = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    pairs = build_controls(tmp_path)
    assert len(pairs) == len(CONTROLS)
    for pair in pairs:
        bad, fixed = pair["variants"]["observed_bad"], pair["variants"]["minimal_repair"]
        assert bad["markdown"] != fixed["markdown"]
        assert {k: v for k, v in bad.items() if k != "markdown"} == {
            k: v for k, v in fixed.items() if k != "markdown"
        }
    assert original == {p: p.read_bytes() for p in tmp_path.rglob("*.json")}


@pytest.mark.parametrize("cost,deadline", [(float("nan"), 1), (1, float("inf")), (-1, 1), (1, 0)])
async def test_calibration_rejects_invalid_limits_before_reading_files(cost, deadline):
    with pytest.raises(ValueError, match="Positive finite"):
        await run(Path("nonexistent"), max_cost_usd=cost, deadline_seconds=deadline)
