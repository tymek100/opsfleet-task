"""Prepare owner-only configuration; mount ADC read-only without copying it."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".artifacts/workflow"
COMPOSE = ROOT / "infra/workflow/compose.yaml"
KEYS = {
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "THINKING_LEVEL",
    "REVIEW_THINKING_LEVEL",
    "MAX_MODEL_CALLS",
    "MAX_OUTPUT_TOKENS",
    "REVIEW_OUTPUT_TOKENS",
    "QUESTION_BUDGET_USD",
    "TURN_TIMEOUT_SECONDS",
    "INPUT_USD_PER_MILLION",
    "OUTPUT_USD_PER_MILLION",
    "GOOGLE_CLOUD_PROJECT",
    "WAREHOUSE_SOURCE_DATASET",
    "BIGQUERY_USD_PER_TIB",
    "GOOGLE_MAPS_API_KEY",
    "MAPS_MCP_ENABLED",
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_TRACING",
    "FOUNDRY_AGENT_ID",
    "FOUNDRY_PORTAL_URL",
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
    "AZURE_MONITOR_ENTRA_AUTH",
    "AZURE_AUTH_MODE",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_OPENAI_BASE_URL",
    "AZURE_OPENAI_API_KEY",
    "TRACE_CONTENT_MODE",
}


def prepare(backend):
    if backend not in {"fixture", "bigquery"}:
        raise ValueError("Backend must be fixture or bigquery")
    if os.getuid() == 0:
        raise RuntimeError("Start this local stack as a non-root user")
    configured = {**dotenv_values(ROOT / ".env"), **os.environ}
    target = STATE / "secrets"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.chmod(0o700)
    path = target / "runtime.env"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(
            "".join(
                f"{k}={json.dumps(str(configured[k]))}\n" for k in sorted(KEYS) if configured.get(k)
            )
        )
    path.chmod(0o600)
    if backend == "bigquery":
        adc = Path(
            configured.get("GOOGLE_APPLICATION_CREDENTIALS")
            or Path.home() / ".config/gcloud/application_default_credentials.json"
        )
        if not adc.is_file() or not configured.get("GOOGLE_CLOUD_PROJECT"):
            raise RuntimeError(
                "Set GOOGLE_CLOUD_PROJECT and configure BigQuery Application Default Credentials."
            )
    else:
        adc = target / "empty-adc.json"
        fd = os.open(adc, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write("{}")
    profile = hashlib.sha256(
        json.dumps(
            [
                backend,
                configured.get(
                    "WAREHOUSE_SOURCE_DATASET", "bigquery-public-data.thelook_ecommerce"
                ),
            ]
        ).encode()
    ).hexdigest()[:16]
    (STATE / "compose.env").write_text(
        f"RETAIL_STACK_BACKEND={backend}\nRETAIL_DATA_PROFILE={backend}-{profile}\nLOCAL_UID={os.getuid()}\nLOCAL_GID={os.getgid()}\nWAREHOUSE_ADC_FILE={adc.resolve()}\n"
    )


def compose_args(*args):
    command = ["docker", "compose", "-f", str(COMPOSE)]
    if (STATE / "compose.env").exists():
        command += ["--env-file", str(STATE / "compose.env")]
    return [*command, *args]


def up(backend="bigquery", *, build=True):
    prepare(backend)
    subprocess.run(
        compose_args("up", "-d", "--wait", *(["--build"] if build else [])), cwd=ROOT, check=True
    )
    print(
        "Retail Insight: http://127.0.0.1:8080 — one LangGraph application, four selectable agents"
    )
