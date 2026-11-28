"""Retail specialization: a prompt, three tools, and the inherited agent loop."""

from datetime import UTC, datetime
from pathlib import Path

from retail_insight.config import Settings
from retail_insight.core.loop import AgentLoop, Model
from retail_insight.core.model import GeminiModel
from retail_insight.tools.bigquery import BigQueryTools
from retail_insight.tools.skills import skill_tool


class RetailAgent(AgentLoop):
    def __init__(self, settings: Settings, *, model: Model | None = None, warehouse=None):
        self.warehouse = warehouse or BigQueryTools(settings)
        prompt = Path(__file__).with_name("prompt.md").read_text()
        super().__init__(
            model=model or GeminiModel(settings),
            instruction=prompt + f"\nToday's UTC date: {datetime.now(UTC):%Y-%m-%d}.",
            tools=[*self.warehouse.tools(), skill_tool()],
            max_model_calls=settings.max_model_calls,
            timeout_seconds=settings.turn_timeout_seconds,
        )

    async def close(self):
        try:
            await super().close()
        finally:
            self.warehouse.close()
