"""Microsoft Foundry Responses adapter for our compiled custom LangGraph."""

import asyncio
import os

from langsmith import tracing_context

from retail_insight.config import Settings
from retail_insight.observability.tracing import configure_from_env
from retail_insight.runtime.team import AgentTeam
from retail_insight.runtime.workflow import build_workflow


def request_owner():
    """Trust only the platform request context, never graph input or a role prompt."""
    from azure.ai.agentserver.core import get_request_context

    context = get_request_context()
    if context and context.user_id:
        return "foundry:" + context.user_id
    if os.getenv("FOUNDRY_PROJECT_ENDPOINT"):
        raise ValueError("Foundry request has no authenticated user context")
    return "local-foundry"


async def main():
    from langchain_azure_ai.agents.hosting import FoundryCheckpointSaver, ResponsesHostServer

    settings = Settings.load()
    team = AgentTeam(settings)
    tracing = configure_from_env()
    try:
        # Foundry State Store persists approved contexts alongside graph messages.
        # The adapter supplies the conversation thread; clients cannot inject our state.
        async with FoundryCheckpointSaver() as checkpointer:
            graph = build_workflow(
                settings, team=team, checkpointer=checkpointer, owner_resolver=request_owner
            )
            with tracing_context(enabled=False):
                await ResponsesHostServer(graph).run_async(port=int(os.getenv("PORT", "8088")))
    finally:
        team.close()
        if tracing:
            tracing.close()


if __name__ == "__main__":
    asyncio.run(main())
