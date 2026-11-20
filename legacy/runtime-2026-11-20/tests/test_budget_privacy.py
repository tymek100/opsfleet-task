import time

import pytest

from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.models import AppError
from retail_agent.privacy import safe_text, validate_question


def test_cost_reserved_before_provider(settings: Settings) -> None:
    settings.question_budget_usd = 0.001
    budget = Budget(settings)
    with pytest.raises(AppError, match="cost budget"):
        budget.model(1000, 4096)
    assert budget.model_calls == 0


def test_deadline_and_query_count(settings: Settings) -> None:
    budget = Budget(settings, started=time.monotonic() - 500)
    with pytest.raises(AppError, match="time limit"):
        budget.query()
    budget = Budget(settings)
    settings.max_queries = 1
    budget.query()
    with pytest.raises(AppError, match="Query limit"):
        budget.query()


@pytest.mark.parametrize(
    "text",
    [
        "email canary@example.test",
        "address is 42 Oak Road",
        "Coordinates 51.12345, 17.12345",
        "my name is Jane Canary",
    ],
)
def test_text_defense(text: str) -> None:
    assert "[redacted]" in safe_text(text)
    with pytest.raises(AppError):
        validate_question(text)
