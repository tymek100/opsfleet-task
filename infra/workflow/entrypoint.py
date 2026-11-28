"""Load only the explicit read-only configuration mount."""

import os
import sys

from dotenv import dotenv_values

for key, value in dotenv_values(os.environ["RETAIL_RUNTIME_ENV_FILE"]).items():
    if value is not None:
        os.environ.setdefault(key, value)
os.execv(sys.executable, [sys.executable, "-m", "retail_insight.interfaces.gui"])
