"""Provider timeouts must not remain armed while ADK executes a reviewer tool."""

import asyncio

from google.adk.models.llm_response import LlmResponse

from retail_agent.contracts import DEMO_USERS
from retail_agent.runtime import Analyst
from tests.support.models import ScriptedModel, finish, usage, verdict


async def test_tool_review_can_use_reserved_time_after_analyst_response(settings):
    async def slow_review(_request):
        await asyncio.sleep(0.65)
        yield LlmResponse(content=verdict(), partial=False, usage_metadata=usage())

    bounded = settings.model_copy(update={"turn_timeout_seconds": 2, "review_reserve_seconds": 1.6})
    app = Analyst(
        bounded,
        DEMO_USERS["alice"],
        model=ScriptedModel(script=[finish("Hello.")]),
        reviewer_model=ScriptedModel(script=[slow_review]),
    )
    try:
        result = await app.ask("Hello")
        assert result.status == "approved"
        assert result.elapsed_seconds >= 0.65
        assert result.elapsed_seconds < 2
    finally:
        app.reports.close()
