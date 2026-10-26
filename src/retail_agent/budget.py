"""Reserve worst-case work before a provider call; all attempts share one turn."""

import time
from dataclasses import dataclass, field

from retail_agent.config import Settings
from retail_agent.models import AppError


@dataclass
class Budget:
    settings: Settings
    started: float = field(default_factory=time.monotonic)
    reserved_usd: float = 0
    model_calls: int = 0
    queries: int = 0

    def remaining(self) -> float:
        seconds = self.settings.turn_timeout_seconds - (time.monotonic() - self.started)
        if seconds <= 0:
            raise AppError(
                "This question reached its time limit. Try a smaller analysis.", code="deadline"
            )
        return seconds

    def reserve(self, dollars: float) -> None:
        self.remaining()
        if self.reserved_usd + dollars > self.settings.question_budget_usd:
            raise AppError(
                "This question reached its cost budget. Narrow the scope or period.",
                code="cost_limit",
            )
        self.reserved_usd += dollars

    def model(self, input_upper_bound: int, output_limit: int) -> None:
        if self.model_calls >= self.settings.max_model_calls:
            raise AppError(
                "Model-call limit reached. Please ask a smaller follow-up.", code="model_call_limit"
            )
        self.reserve(
            (
                input_upper_bound * self.settings.input_usd_per_million
                + output_limit * self.settings.output_usd_per_million
            )
            / 1_000_000
        )
        self.model_calls += 1

    def query(self) -> None:
        if self.queries >= self.settings.max_queries:
            raise AppError(
                "Query limit reached. Please ask a smaller follow-up.", code="query_count_limit"
            )
        self.reserve(self.settings.max_query_bytes / 2**40 * self.settings.bigquery_usd_per_tib)
        self.queries += 1
