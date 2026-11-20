"""Content fingerprints for reproducible diagnostics; no subprocesses or secrets."""

import hashlib
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def source_version() -> str:
    try:
        files = sorted(Path(__file__).parent.glob("*.py"))
        return hashlib.sha256(
            b"".join(p.name.encode() + p.read_bytes() for p in files)
        ).hexdigest()[:16]
    except OSError:
        return "unavailable"


def versions(instruction: str, model: str) -> dict[str, str]:
    return {
        "source": source_version(),
        "prompt": hashlib.sha256(instruction.encode()).hexdigest()[:16],
        "model": model,
        "runtime": "single-loop-review-v1",
        "compiler": "scoped-sql-v2",
    }
