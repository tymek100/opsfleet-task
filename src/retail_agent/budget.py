"""One conservative admission ledger for every model call, query and retry."""

import time
from dataclasses import dataclass, field

from retail_agent.config import Settings


class LimitReached(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass
class Budget:
    settings: Settings
    started: float = field(default_factory=time.monotonic)
    reserved_usd: float = 0
    model_calls: int = 0
    queries: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    last_model_at: float = 0

    def remaining(self) -> float:
        remaining = self.settings.turn_timeout_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise LimitReached("deadline")
        return remaining

    def work_remaining(self, *, reviewer: bool = False) -> float:
        seconds = self.remaining() - (0 if reviewer else self.settings.review_reserve_seconds)
        if seconds <= 0:
            raise LimitReached("completion_time_reserve")
        return seconds

    @property
    def review_reserve(self) -> float:
        return (
            (self.settings.max_review_bytes + self.settings.review_overhead_bytes)
            * self.settings.input_usd_per_million
            + self.settings.review_output_tokens * self.settings.output_usd_per_million
        ) / 1e6

    def reserve(self, amount: float, *, keep_review: bool = True) -> None:
        self.remaining()
        future = self.review_reserve if keep_review else 0
        if self.reserved_usd + amount + future > self.settings.question_budget_usd:
            raise LimitReached("cost_budget")
        self.reserved_usd += amount

    def model(self, input_bytes: int, output_limit: int, *, reviewer: bool) -> None:
        self.work_remaining(reviewer=reviewer)
        limit = self.settings.max_model_calls - (0 if reviewer else 1)
        if self.model_calls >= limit:
            raise LimitReached("model_calls")
        if input_bytes > self.settings.max_context_bytes:
            raise LimitReached("context_size")
        if (
            reviewer
            and input_bytes > self.settings.max_review_bytes + self.settings.review_overhead_bytes
        ):
            raise LimitReached("review_context_size")
        # UTF-8 bytes are a conservative token ceiling; rates are configurable admission rates.
        self.reserve(
            (
                input_bytes * self.settings.input_usd_per_million
                + output_limit * self.settings.output_usd_per_million
            )
            / 1e6,
            keep_review=not reviewer,
        )
        self.model_calls += 1

    def query(self) -> None:
        self.work_remaining()
        if self.queries >= self.settings.max_queries:
            raise LimitReached("queries")
        self.reserve(self.settings.max_query_bytes / 2**40 * self.settings.bigquery_usd_per_tib)
        self.queries += 1

    def tool(self, *, completion: bool = False) -> None:
        self.remaining()
        limit = self.settings.max_tool_calls - (0 if completion else 1)
        if self.tool_calls >= limit:
            raise LimitReached("tools")
        self.tool_calls += 1

    def snapshot(self) -> dict:
        return {
            "model_calls": self.model_calls,
            "queries": self.queries,
            "tool_calls": self.tool_calls,
            "reserved_usd": round(self.reserved_usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
        }
