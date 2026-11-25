"""Review admission includes actual role instructions without dropping evidence."""

import json

import pytest

from retail_insight.agents.registry import create_agent
from retail_insight.contracts import WORKSPACE_IDENTITY
from retail_insight.review.reviewer import evaluate
from tests.support.models import ScriptedModel, verdict


@pytest.mark.parametrize("context_limit", [150_000, 70_000])
async def test_large_review_bundle_uses_actual_prompt_size_or_returns_actionable_revision(
    settings, context_limit
):
    settings = settings.model_copy(update={"max_context_bytes": context_limit})
    reviewer = ScriptedModel(script=[verdict()])
    app = create_agent(
        "coordinator",
        settings,
        WORKSPACE_IDENTITY,
        model=ScriptedModel(),
        reviewer_model=reviewer,
    )
    payload = {
        "question": "Summarize these observations.",
        "candidate": {"markdown": "A supported summary.", "outcome": "answer"},
        "evidence": [{"id": "E1", "rows": [{"description": "x" * 54_000 + "END_OF_EVIDENCE"}]}],
    }
    budget = app.new_budget()
    try:
        assert len(json.dumps(payload).encode()) < settings.max_review_bytes
        assert budget.review_prompt_bytes > settings.review_overhead_bytes
        assert budget.review_input_limit <= context_limit
        expected_reserve = (
            budget.review_input_limit * settings.input_usd_per_million
            + settings.review_output_tokens * settings.output_usd_per_million
        ) / 1e6
        assert budget.review_reserve == pytest.approx(expected_reserve)
        review = await evaluate(
            payload,
            reviewer,
            budget,
            settings,
            lambda *args, **kwargs: None,
            review_skill=app.skills.review_skill(),
        )
        if context_limit == 150_000:
            assert review.decision == "approve"
            request = reviewer.requests[0]
            assert len(json.dumps(request).encode()) > (
                settings.max_review_bytes + settings.review_overhead_bytes
            )
            received = json.loads(request["contents"][0]["parts"][0]["text"])
            assert received == payload
        else:
            assert review.decision == "revise"
            assert review.issues[0].category == "evidence_bundle_too_large"
            assert not reviewer.requests
            assert budget.model_calls == 0
    finally:
        app.reports.close()
