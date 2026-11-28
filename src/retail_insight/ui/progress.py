"""Shared terminal waiting indicator, refreshed independently of agent events."""

from dataclasses import dataclass, field
from time import monotonic

from rich.text import Text


@dataclass(frozen=True)
class ThinkingStatus:
    started: float = field(default_factory=lambda: monotonic())

    def __rich__(self) -> Text:
        elapsed = max(0.0, monotonic() - self.started)
        dots = "." * (int(elapsed * 2) % 3 + 1)
        return Text(f"{int(elapsed)}s Thinking{dots:<3}")
