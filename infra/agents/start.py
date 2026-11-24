"""Prepare isolated local credentials and run the existing Phoenix and agent Compose projects."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".artifacts/agents"
COMPOSE = ROOT / "infra/agents/compose.yaml"
PHOENIX_COMPOSE = ROOT / "infra/phoenix/compose.yaml"
MODEL_KEYS = {
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
}
WAREHOUSE_KEYS = {"GOOGLE_CLOUD_PROJECT", "WAREHOUSE_SOURCE_DATASET", "BIGQUERY_USD_PER_TIB"}
MAPS_KEYS = {"GOOGLE_MAPS_API_KEY", "MAPS_API_KEY", "GOOGLE_MAPS_MCP_URL", "MAPS_MCP_ENABLED"}


def write_private(path: Path, text: str) -> None:
    """Parent is owner-only; files must be readable by the non-root container UID."""
    path.write_text(text)
    path.chmod(0o644)


def prepare(backend: str, evaluation_fixtures: bool = False) -> None:
    if evaluation_fixtures and backend != "fixture":
        raise RuntimeError("Evaluation fixtures require --backend fixture.")
    if evaluation_fixtures:
        for filename in ("fixture.json", "retail_fixture.sql"):
            if not (ROOT / "evaluation/multi_agent" / filename).is_file():
                raise RuntimeError(f"Evaluation warehouse fixture is missing: {filename}")
    STATE.mkdir(parents=True, exist_ok=True)
    secret_dir = STATE / "secrets"
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    secret_dir.chmod(0o700)
    configured = {**dotenv_values(ROOT / ".env"), **os.environ}
    if not configured.get("GEMINI_API_KEY"):
        raise RuntimeError("Set GEMINI_API_KEY in .env before starting the live agents.")
    for filename, names in (
        ("model.env", MODEL_KEYS),
        ("warehouse.env", WAREHOUSE_KEYS),
        ("maps.env", MAPS_KEYS),
    ):
        text = "".join(
            f"{key}={json.dumps(str(configured[key]))}\n"
            for key in sorted(names)
            if configured.get(key)
        )
        write_private(secret_dir / filename, text)
    for filename in ("a2a_signing_key", "a2a_demo_token"):
        path = secret_dir / filename
        if not path.exists():
            write_private(path, secrets.token_urlsafe(48) + "\n")

    adc_target = secret_dir / "warehouse_adc.json"
    if backend == "bigquery":
        adc = Path(
            configured.get("GOOGLE_APPLICATION_CREDENTIALS")
            or Path.home() / ".config/gcloud/application_default_credentials.json"
        )
        if not adc.is_file():
            raise RuntimeError(
                "BigQuery needs Application Default Credentials. Run gcloud auth "
                "application-default login or set GOOGLE_APPLICATION_CREDENTIALS."
            )
        if not configured.get("GOOGLE_CLOUD_PROJECT"):
            raise RuntimeError("BigQuery requires GOOGLE_CLOUD_PROJECT in .env.")
        shutil.copyfile(adc, adc_target)
        adc_target.chmod(0o644)
    else:
        write_private(adc_target, "{}\n")

    catalog = json.loads((ROOT / "infra/agents/catalog.json").read_text())
    inspector = {
        "specVersion": "1.0",
        "host": {"displayName": "Retail Insight Agents"},
        "entries": [
            {
                "identifier": f"urn:retail-insight:agent:{role}",
                "displayName": item["name"],
                "type": "application/a2a-agent-card+json",
                "url": item["card_url"],
            }
            for role, item in catalog.items()
        ],
    }
    (STATE / "inspector-catalog.json").write_text(json.dumps(inspector, indent=2) + "\n")
    source_profile = {
        "backend": backend,
        "source_dataset": configured.get(
            "WAREHOUSE_SOURCE_DATASET", "bigquery-public-data.thelook_ecommerce"
        ),
    }
    if backend == "fixture":
        paths = (
            (
                ROOT / "evaluation/multi_agent/fixture.json",
                ROOT / "evaluation/multi_agent/retail_fixture.sql",
            )
            if evaluation_fixtures
            else (
                ROOT / "src/retail_agents/domains/fixtures.json",
                ROOT / "knowledge/fixtures/retail_seed_v1.sql",
            )
        )
        source_profile["fixture_hashes"] = [
            hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        ]
    profile_id = (
        backend
        + "-"
        + hashlib.sha256(json.dumps(source_profile, sort_keys=True).encode()).hexdigest()[:20]
    )
    (STATE / "compose.env").write_text(
        f"RETAIL_STACK_BACKEND={backend}\nRETAIL_STACK_DATA_PROFILE={profile_id}\n"
    )
    (STATE / "profile.json").write_text(
        json.dumps({"evaluation_fixtures": evaluation_fixtures, "data_profile": profile_id})
    )


def compose_args(*args: str) -> list[str]:
    prefix = ["docker", "compose", "-f", str(COMPOSE)]
    profile = STATE / "profile.json"
    if profile.is_file() and json.loads(profile.read_text()).get("evaluation_fixtures"):
        prefix += ["-f", str(ROOT / "infra/agents/compose.evaluation.yaml")]
    if (STATE / "compose.env").exists():
        prefix += ["--env-file", str(STATE / "compose.env")]
    return [*prefix, *args]


def up(backend: str = "fixture", build: bool = True, evaluation_fixtures: bool = False) -> None:
    prepare(backend, evaluation_fixtures=evaluation_fixtures)
    subprocess.run(
        ["docker", "compose", "-f", str(PHOENIX_COMPOSE), "up", "-d"],
        cwd=ROOT,
        check=True,
    )
    args = ["up", "-d", "--wait", "--wait-timeout", "180"]
    if build:
        args.append("--build")
    subprocess.run(compose_args(*args), cwd=ROOT, check=True)
    revision = os.environ.get("RETAIL_STACK_REVISION", "local")
    images = {
        "retail": f"retail-analyst:{revision}",
        "inventory": f"retail-inventory:{revision}",
        "distribution": f"retail-distribution:{revision}",
        "coordinator": f"retail-coordinator:{revision}",
    }
    inspected = json.loads(
        subprocess.check_output(
            ["docker", "image", "inspect", *images.values()], cwd=ROOT, text=True
        )
    )
    image_manifest = {
        "images": {
            role: {"tag": images[role], "image_id": image["Id"]}
            for role, image in zip(images, inspected, strict=True)
        },
        "backend": backend,
        "evaluation_fixtures": evaluation_fixtures,
        "data_profile": json.loads((STATE / "profile.json").read_text())["data_profile"],
        "catalog_sha256": hashlib.sha256(
            (ROOT / "infra/agents/catalog.json").read_bytes()
        ).hexdigest(),
    }
    (STATE / "images.json").write_text(json.dumps(image_manifest, indent=2) + "\n")
    print("Agent stack ready. Phoenix: http://127.0.0.1:6006")
    print("Inspector: http://127.0.0.1:8080 (open its tokenized URL from the logs below).")
    print(
        "For agent authentication, use Bearer plus the local token printed by retail-stack token."
    )
    subprocess.run(compose_args("logs", "--tail", "12", "inspector"), cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["fixture", "bigquery"], default="fixture")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--evaluation-fixtures", action="store_true")
    options = parser.parse_args()
    if options.prepare_only:
        prepare(options.backend, evaluation_fixtures=options.evaluation_fixtures)
    else:
        up(
            options.backend,
            build=not options.no_build,
            evaluation_fixtures=options.evaluation_fixtures,
        )


if __name__ == "__main__":
    main()
