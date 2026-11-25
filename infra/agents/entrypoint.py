"""Load only explicitly mounted runtime configuration before starting an agent."""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values


def main() -> None:
    for setting in ("RETAIL_RUNTIME_ENV_FILE", "RETAIL_WAREHOUSE_ENV_FILE", "RETAIL_MAPS_ENV_FILE"):
        filename = os.environ.get(setting)
        if not filename:
            continue
        path = Path(filename)
        if not path.is_file():
            raise SystemExit(f"Required mounted configuration is missing: {setting}")
        for key, value in dotenv_values(path).items():
            if value is not None:
                os.environ.setdefault(key, value)
    os.execv(sys.executable, [sys.executable, "-m", "retail_insight.a2a.server", *sys.argv[1:]])


if __name__ == "__main__":
    main()
