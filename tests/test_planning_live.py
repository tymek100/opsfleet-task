"""Semantic interpretation regression evals; explicitly opt in to provider charges."""

import json
from datetime import date
from pathlib import Path
from typing import cast

import pytest
from google import genai
from google.genai import types

from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.model import BoundedGemini
from retail_agent.models import DEMO_USERS, Intent
from retail_agent.observability import Trace
from retail_agent.planning import propose_plan

CASES = cast(
    list[dict[str, object]],
    json.loads((Path(__file__).parent / "fixtures" / "planning-evals.json").read_text()),
)


def assert_subset(actual: object, expected: object) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, value in cast(dict[str, object], expected).items():
            assert key in actual
            assert_subset(cast(dict[str, object], actual)[key], value)
    else:
        assert actual == expected


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[str(c["id"]) for c in CASES])
async def test_live_semantic_plan(case: dict[str, object], tmp_path: Path) -> None:
    settings = Settings.load()
    assert settings.gemini_api_key.get_secret_value(), "Live planning eval requires credentials"
    client = genai.Client(
        api_key=settings.gemini_api_key.get_secret_value(),
        http_options=types.HttpOptions(
            timeout=45_000, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    budget = Budget(settings)
    trace = Trace(tmp_path / "planning.log")
    model = BoundedGemini(model=settings.gemini_model, client=client).bind(budget, trace)
    try:
        plan = await propose_plan(
            str(case["question"]),
            Intent.model_validate(case["previous"]) if "previous" in case else None,
            [],
            DEMO_USERS[str(case["user"])],
            date(2026, 10, 25),
            model,
            budget,
            trace,
        )
        (tmp_path / "plan.json").write_text(plan.model_dump_json(indent=2))
        assert_subset(plan.model_dump(mode="json"), case["expected"])
        if "requirements" in case:
            assert plan.intent
            actual = sorted(
                (r.dimension.value, r.metric, r.minimum_rows) for r in plan.intent.requirements
            )
            expected = sorted(
                tuple(row) for row in cast(list[list[str | int]], case["requirements"])
            )
            assert actual == expected
    finally:
        await client.aio.aclose()
        client.close()
