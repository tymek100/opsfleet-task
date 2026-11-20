"""Completed model calls release unused holds without weakening shared admission."""

from types import SimpleNamespace

import pytest

import retail_agent.budget as budget_module
from retail_agent.budget import Budget, LimitReached
from retail_agent.config import Settings


def ledger(**overrides) -> Budget:
    # No .env, provider, network, or credential discovery is used by these tests.
    return Budget(Settings.model_construct(**overrides))


def test_six_short_calls_release_their_maximum_output_and_input_reservations():
    budget = ledger()
    for _ in range(6):
        reservation = budget.model(60_000, 4096, reviewer=False)
        assert budget.reserved_usd == pytest.approx(0.169152)
        assert budget.settle_model(
            reservation, input_tokens=6000, output_tokens=200, thinking_tokens=50
        )
        assert budget.reserved_usd == 0
    assert budget.spent_usd == pytest.approx(0.09)
    assert budget.input_tokens == 36_000
    assert budget.output_tokens == 1200
    assert budget.thinking_tokens == 300
    # Permanently accumulating the six maximum estimates exhausted the former ledger.
    assert 6 * 0.169152 + budget.review_reserve > budget.settings.question_budget_usd
    budget.model(60_000, 4096, reviewer=False)
    assert budget.model_calls == 7
    assert budget.accounted_usd + budget.review_reserve < budget.settings.question_budget_usd


def test_settlement_releases_only_its_own_hold_and_is_idempotent():
    budget = ledger()
    first = budget.model(10_000, 4096, reviewer=False)
    second = budget.model(20_000, 4096, reviewer=False)
    budget.query()
    other_reservations = (
        20_000 * budget.settings.input_usd_per_million / 1e6
        + 4096 * budget.settings.output_usd_per_million / 1e6
        + budget.settings.max_query_bytes / 2**40 * budget.settings.bigquery_usd_per_tib
    )
    assert budget.settle_model(first, input_tokens=100, output_tokens=20, thinking_tokens=5)
    assert budget.reserved_usd == pytest.approx(other_reservations)
    assert budget.spent_usd == pytest.approx(0.0005)
    before = budget.snapshot()
    assert not budget.settle_model(first, input_tokens=100, output_tokens=20, thinking_tokens=5)
    assert budget.snapshot() == before
    assert budget.settle_model(second, input_tokens=200, output_tokens=30, thinking_tokens=0)
    query_hold = budget.settings.max_query_bytes / 2**40 * budget.settings.bigquery_usd_per_tib
    assert budget.reserved_usd == pytest.approx(query_hold)
    assert budget.spent_usd == pytest.approx(0.00126)


@pytest.mark.parametrize("bad_count", [None, -1, 1.5, True, "20"])
@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "thinking_tokens"])
def test_invalid_usage_keeps_the_full_reservation(bad_count, field):
    budget = ledger()
    reservation = budget.model(10_000, 4096, reviewer=False)
    counts = {"input_tokens": 100, "output_tokens": 20, "thinking_tokens": 0}
    counts[field] = bad_count
    before = budget.snapshot()
    assert not budget.settle_model(reservation, **counts)
    assert budget.snapshot() == before


def test_non_model_and_unknown_reservations_cannot_release_money():
    budget = ledger()
    generic = budget.reserve(0.05)
    before = budget.snapshot()
    for reservation in (generic, 999):
        assert not budget.settle_model(
            reservation, input_tokens=0, output_tokens=0, thinking_tokens=0
        )
        assert budget.snapshot() == before


def test_admission_counts_settled_usage_pending_calls_and_review_allowance():
    budget = ledger()
    first = budget.model(60_000, 4096, reviewer=False)
    budget.model(60_000, 4096, reviewer=False)
    budget.settle_model(first, input_tokens=6000, output_tokens=200, thinking_tokens=50)
    expected_available = 1 - 0.015 - 0.169152 - budget.review_reserve
    assert budget.work_available_usd == pytest.approx(expected_available)
    before = budget.snapshot()
    with pytest.raises(LimitReached) as caught:
        budget.reserve(expected_available + 0.001)
    assert caught.value.code == "cost_budget"
    assert budget.snapshot() == before
    budget.model(1000, 2048, reviewer=True)
    assert budget.accounted_usd <= 1


def test_usage_exceeding_the_reservation_is_recorded_in_full():
    budget = ledger()
    reservation = budget.model(100, 100, reviewer=False)
    assert budget.settle_model(
        reservation, input_tokens=10_000, output_tokens=1000, thinking_tokens=100
    )
    assert budget.spent_usd == pytest.approx(0.0332)
    assert budget.reserved_usd == 0


def test_unexpected_usage_over_the_cap_is_recorded_and_stops_further_admission():
    budget = ledger(question_budget_usd=0.2)
    reservation = budget.model(100, 100, reviewer=False)
    with pytest.raises(LimitReached) as caught:
        budget.settle_model(
            reservation, input_tokens=200_000, output_tokens=100_000, thinking_tokens=1000
        )
    assert caught.value.code == "cost_budget"
    assert budget.spent_usd == pytest.approx(1.612)
    assert budget.reserved_usd == 0
    assert budget.remaining_usd == 0
    assert budget.input_tokens == 200_000 and budget.thinking_tokens == 1000
    with pytest.raises(LimitReached) as caught:
        budget.reserve(0, keep_review=False)
    assert caught.value.code == "cost_budget"
    assert not budget.settle_model(
        reservation, input_tokens=200_000, output_tokens=100_000, thinking_tokens=1000
    )


def test_follow_up_budget_is_independent_of_the_prior_questions_usage():
    first = ledger()
    reservation = first.model(60_000, 4096, reviewer=False)
    first.settle_model(reservation, input_tokens=6000, output_tokens=200, thinking_tokens=50)
    first.model(60_000, 4096, reviewer=False)
    follow_up = Budget(first.settings)
    assert follow_up.remaining_usd == 1
    assert follow_up.spent_usd == follow_up.reserved_usd == 0
    assert follow_up.model_calls == follow_up.input_tokens == 0
    assert first.accounted_usd == pytest.approx(0.184152)


def test_completed_usage_can_be_settled_after_the_question_deadline(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(budget_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    budget = Budget(Settings.model_construct(), started=now[0])
    reservation = budget.model(1000, 1000, reviewer=False)
    now[0] += 121
    assert budget.settle_model(reservation, input_tokens=100, output_tokens=20, thinking_tokens=0)
    assert budget.spent_usd == pytest.approx(0.00044)
    assert budget.reserved_usd == 0
    with pytest.raises(LimitReached) as caught:
        budget.model(1000, 1000, reviewer=False)
    assert caught.value.code == "deadline"
