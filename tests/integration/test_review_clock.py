"""The analyst and reviewer share trusted time independently of warehouse dates."""

import json
from datetime import UTC, datetime, timedelta, timezone

from retail_insight.agents.retail.agent import RetailAnalyst as Analyst
from retail_insight.contracts import DEMO_USERS
from tests.support.models import ScriptedModel, calls, finish, verdict


async def test_injected_clock_reaches_analyst_and_reviewer_despite_future_evidence(settings):
    # Cross a UTC date boundary to verify normalization, not just string forwarding.
    fixed = datetime(2026, 4, 1, 0, 30, 45, tzinfo=timezone(timedelta(hours=2)))
    expected = fixed.astimezone(UTC)
    records = []
    model = ScriptedModel(
        script=[
            calls(
                (
                    "query_data",
                    {
                        "sql": (
                            "SELECT TIMESTAMP('2040-01-01T00:00:00+00:00') AS purchased_at "
                            "FROM sales LIMIT 1"
                        ),
                        "purpose": "Inspect a synthetic future-dated observation",
                    },
                )
            ),
            finish("The recorded purchase is after the current reporting date [E1].", ["E1"]),
        ]
    )
    reviewer = ScriptedModel(script=[verdict()])
    app = Analyst(
        settings,
        DEMO_USERS["alice"],
        clock=lambda: fixed,
        observer=records.append,
        observation_mode="synthetic",
        model=model,
        reviewer_model=reviewer,
    )
    try:
        result = await app.ask("Check whether the observation is dated after now.")
        assert result.status == "approved"
        initial = json.loads(model.requests[0]["contents"][0]["parts"][0]["text"])
        review = json.loads(reviewer.requests[0]["contents"][0]["parts"][0]["text"])
        captured = next(item["context"] for item in records if item["event"] == "initial_context")
        assert captured == initial
        assert "2040-01-01" in json.dumps(review["evidence"])
        assert review["evidence"][0]["queried_at"] == expected.isoformat()
        for context in (initial, review):
            assert context["now_utc"] == expected.isoformat()
            assert context["today_utc"] == expected.date().isoformat()
        assert reviewer.requests[0]["registered_tools"] == []
    finally:
        app.reports.close()
