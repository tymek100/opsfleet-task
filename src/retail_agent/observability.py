"""Content-free correlated events: never pass raw prompts or provider exceptions."""

import json
import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from retail_agent.models import AppError, Scalar


@dataclass
class Trace:
    path: Path | None = None
    degraded: bool = False
    id: str = field(default_factory=lambda: uuid4().hex)
    events: list[dict[str, Scalar]] = field(default_factory=lambda: list[dict[str, Scalar]]())

    def emit(self, event: str, **fields: Scalar) -> None:
        record: dict[str, Scalar] = {"trace_id": self.id, "event": event, "time": time.time()}
        record.update(fields)
        self.events.append(record)
        if self.path and not self.degraded:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record) + "\n")
                self.path.chmod(0o600)
            except OSError:
                # Auxiliary diagnostics must not take down chat. Mutation audit remains
                # transactional in SQLite and is never silently discarded here.
                self.degraded = True
                self.events.append(
                    {"trace_id": self.id, "event": "diagnostics_unavailable", "time": time.time()}
                )


class ControlledErrorFilter(logging.Filter):
    """The CLI handles AppError; avoid ADK printing the same error with a traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.exc_info and isinstance(record.exc_info[1], AppError))


@contextmanager
def quiet_controlled_adk_errors() -> Generator[None]:
    # ADK 2.12 uses google_adk.*, not google.*. Filter at the emitting loggers;
    # ancestor logger filters do not apply to propagated child records.
    loggers = [
        logging.getLogger(name)
        for name in (
            "google_adk.google.adk.workflow._node_runner",
            "google_adk.google.adk.runners",
        )
    ]
    filter_ = ControlledErrorFilter()
    for logger in loggers:
        logger.addFilter(filter_)
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeFilter(filter_)
