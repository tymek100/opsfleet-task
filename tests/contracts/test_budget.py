"""Admission limits and observed provider charges are separate accounting states."""

import pytest

from retail_insight.runtime.budget import Budget, LimitReached


def test_settlement_releases_only_its_hold_and_is_idempotent(settings):
    ledger = Budget(settings)
    first = ledger.model(1000, 4096, reviewer=False)
    second = ledger.model(2000, 2048, reviewer=True)
    held = ledger.reserved_usd
    assert ledger.settle_model(first, input_tokens=100, output_tokens=20, thinking_tokens=5)
    assert 0 < ledger.reserved_usd < held
    assert ledger.spent_usd == pytest.approx(0.0005)
    snapshot = ledger.snapshot()
    assert not ledger.settle_model(first, input_tokens=100, output_tokens=20, thinking_tokens=5)
    assert ledger.snapshot() == snapshot
    assert ledger.settle_model(second, input_tokens=0, output_tokens=0, thinking_tokens=0)
    assert ledger.reserved_usd == 0


@pytest.mark.parametrize("count", [-1, True, 1.5, "1", None])
def test_invalid_usage_cannot_refund_unknown_work(settings, count):
    ledger = Budget(settings)
    reservation = ledger.model(100, 100, reviewer=False)
    before = ledger.snapshot()
    assert not ledger.settle_model(
        reservation, input_tokens=count, output_tokens=0, thinking_tokens=0
    )
    assert ledger.snapshot() == before


def test_last_model_and_tool_slots_belong_to_completion(settings):
    ledger = Budget(settings.model_copy(update={"max_model_calls": 2, "max_tool_calls": 2}))
    ledger.model(10, 10, reviewer=False)
    with pytest.raises(LimitReached, match="model_calls"):
        ledger.model(10, 10, reviewer=False)
    ledger.model(10, 10, reviewer=True)
    ledger.tool()
    with pytest.raises(LimitReached):
        ledger.tool()
    ledger.tool(completion=True)


def test_actual_overrun_is_recorded_before_execution_stops(settings):
    ledger = Budget(settings.model_copy(update={"question_budget_usd": 0.2}))
    reservation = ledger.model(1, 1, reviewer=False)
    with pytest.raises(LimitReached, match="cost_budget"):
        ledger.settle_model(reservation, input_tokens=1_000_000, output_tokens=0, thinking_tokens=0)
    assert ledger.spent_usd == 2
    assert ledger.reserved_usd == 0
    assert ledger.input_tokens == 1_000_000


def test_query_reservation_cannot_be_released_as_model_usage(settings):
    ledger = Budget(settings)
    ledger.query()
    snapshot = ledger.snapshot()
    assert not ledger.settle_model(1, input_tokens=0, output_tokens=0, thinking_tokens=0)
    assert ledger.snapshot() == snapshot


@pytest.mark.parametrize("amount", [-1, float("nan"), float("inf")])
def test_invalid_costs_never_change_ledger(settings, amount):
    ledger = Budget(settings)
    with pytest.raises(ValueError):
        ledger.reserve(amount)
    assert ledger.reserved_usd == ledger.spent_usd == 0
