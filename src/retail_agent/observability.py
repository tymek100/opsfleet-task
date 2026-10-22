"""Content-free correlated events: never pass raw prompts or provider exceptions."""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from retail_agent.models import Scalar


@dataclass
class Trace:
    path: Path | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
    events: list[dict[str, Scalar]] = field(default_factory=lambda: list[dict[str, Scalar]]())

    def emit(self, event: str, **fields: Scalar) -> None:
        record: dict[str, Scalar] = {"trace_id": self.id, "event": event, "time": time.time()}
        record.update(fields)
        self.events.append(record)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record) + "\n")
            self.path.chmod(0o600)
