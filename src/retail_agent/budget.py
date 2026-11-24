"""One conservative admission ledger for every model call, query and retry."""

import math
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
    spent_usd: float = 0
    model_calls: int = 0
    queries: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    last_model_at: float = 0
    _reservations: dict[int, float] = field(default_factory=dict, init=False, repr=False)
    _model_reservations: set[int] = field(default_factory=set, init=False, repr=False)
    _next_reservation: int = field(default=0, init=False, repr=False)

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

    @property
    def accounted_usd(self) -> float:
        """Reported usage at configured rates plus costs still held conservatively."""
        return self.spent_usd + self.reserved_usd

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.settings.question_budget_usd - self.accounted_usd)

    @property
    def work_available_usd(self) -> float:
        return max(0.0, self.remaining_usd - self.review_reserve)

    def reserve(self, amount: float, *, keep_review: bool = True) -> int:
        self.remaining()
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("A reservation must be a finite nonnegative amount.")
        future = self.review_reserve if keep_review else 0
        if self.accounted_usd + amount + future > self.settings.question_budget_usd:
            raise LimitReached("cost_budget")
        self._next_reservation += 1
        self._reservations[self._next_reservation] = amount
        self.reserved_usd += amount
        return self._next_reservation

    def model(self, input_bytes: int, output_limit: int, *, reviewer: bool) -> int:
        self.work_remaining(reviewer=reviewer)
        if any(type(count) is not int or count < 0 for count in (input_bytes, output_limit)):
            raise ValueError("Model limits must be nonnegative integers.")
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
        reservation = self.reserve(
            (
                input_bytes * self.settings.input_usd_per_million
                + output_limit * self.settings.output_usd_per_million
            )
            / 1e6,
            keep_review=not reviewer,
        )
        self._model_reservations.add(reservation)
        self.model_calls += 1
        return reservation

    def settle_model(
        self,
        reservation: int,
        *,
        input_tokens: int,
        output_tokens: int,
        thinking_tokens: int,
    ) -> bool:
        """Replace one completed model attempt's hold with reported token usage once.

        Unknown or invalid usage leaves the full hold intact. Cached input is priced
        at the configured full input rate; no unconfigured discount is assumed.
        Settlement is allowed after a deadline because already incurred usage still
        belongs in the ledger.
        """
        counts = (input_tokens, output_tokens, thinking_tokens)
        if (
            type(reservation) is not int
            or reservation not in self._model_reservations
            or any(type(count) is not int or count < 0 for count in counts)
        ):
            return False
        amount = (
            input_tokens * self.settings.input_usd_per_million
            + (output_tokens + thinking_tokens) * self.settings.output_usd_per_million
        ) / 1e6
        self._model_reservations.remove(reservation)
        self._reservations.pop(reservation)
        self.reserved_usd = sum(self._reservations.values())
        self.spent_usd += amount
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.thinking_tokens += thinking_tokens
        # Never hide an unexpectedly expensive response by clamping its usage.
        if self.accounted_usd > self.settings.question_budget_usd:
            raise LimitReached("cost_budget")
        return True

    def query(self) -> None:
        self.work_remaining()
        if self.queries >= self.settings.max_queries:
            raise LimitReached("queries")
        self.reserve(self.settings.max_query_bytes / 2**40 * self.settings.bigquery_usd_per_tib)
        self.queries += 1

    def settle_external(self, reservation: int, accounted_usd: float) -> bool:
        """Settle a delegated allowance once; unknown usage must keep its reservation."""
        if (
            reservation not in self._reservations
            or reservation in self._model_reservations
            or not math.isfinite(accounted_usd)
            or accounted_usd < 0
        ):
            return False
        self._reservations.pop(reservation)
        self.reserved_usd = sum(self._reservations.values())
        self.spent_usd += accounted_usd
        if self.accounted_usd > self.settings.question_budget_usd:
            raise LimitReached("cost_budget")
        return True

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
            "spent_usd": round(self.spent_usd, 6),
            "accounted_usd": round(self.accounted_usd, 6),
            "remaining_usd": round(self.remaining_usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
        }
