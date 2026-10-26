"""Fresh reviewer scenarios. Opt-in live calls, isolated state, retained first attempts."""

import argparse
import asyncio
import io
import json
import logging
import time
from pathlib import Path

from rich.console import Console

from retail_agent.agent import Analyst
from retail_agent.bigquery import BigQueryExecutor
from retail_agent.config import Settings
from retail_agent.model import ModelPacer
from retail_agent.models import DEMO_USERS
from retail_agent.render import display_answer
from retail_agent.reports import ReportStore


async def run(root):
    settings = Settings.load()
    if not settings.google_cloud_project or not settings.gemini_api_key.get_secret_value():
        raise SystemExit("External Gemini and BigQuery credentials are required")
    root.mkdir(parents=True, exist_ok=False)
    settings.data_dir = root
    for name in ("google", "httpx"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    cases = json.loads(Path(__file__).with_name("cases.json").read_text())
    (root / "cases.json").write_text(json.dumps(cases, indent=2))
    store = ReportStore(root / "isolated.sqlite3")
    executor = BigQueryExecutor(settings.google_cloud_project)
    pacer = ModelPacer(settings.model_min_interval_seconds)
    sessions = {}
    try:
        for case in cases:
            session = case["session"]
            if session not in sessions:
                sessions[session] = Analyst(
                    settings, DEMO_USERS[case["user"]], executor, store, session
                )
                sessions[session].pacer = pacer
            result = dict(case)
            result["reports_before"] = [r.title for r in store.list(case["user"])]
            result["pending_before"] = store.db.execute("SELECT count(*) FROM pending").fetchone()[
                0
            ]
            started = time.monotonic()
            print("START", case["id"], case["name"], flush=True)
            try:
                answer = await sessions[session].ask(case["prompt"])
                result["answer"] = answer.model_dump(mode="json")
                for width in (80, 120):
                    console = Console(
                        file=io.StringIO(), record=True, width=width, color_system=None
                    )
                    display_answer(console, answer)
                    (root / f"{case['id']:02}-{case['name']}-{width}.txt").write_text(
                        console.export_text()
                    )
            except Exception as exc:
                result.update(error=str(exc), code=getattr(exc, "code", type(exc).__name__))
            result["seconds"] = round(time.monotonic() - started, 3)
            result["reports_after"] = [r.title for r in store.list(case["user"])]
            result["pending_after"] = store.db.execute("SELECT count(*) FROM pending").fetchone()[0]
            (root / f"{case['id']:02}-{case['name']}.json").write_text(json.dumps(result, indent=2))
            print("END", case["id"], result.get("code", "response"), result["seconds"], flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output))
