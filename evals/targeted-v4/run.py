"""Opt-in live replay of the published ten cases in an isolated report library."""

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
from retail_agent.models import DEMO_USERS, Analysis, Answer, Evidence
from retail_agent.render import display_answer, render_preview
from retail_agent.reports import ReportStore

HERE = Path(__file__).resolve().parent


def seed(store):
    """Synthetic persistence fixture only; never used as analytical evidence."""
    answer = Answer(
        text="Synthetic saved-report fixture, not live analysis.",
        trace_id="fixture-seed",
        evidence=[
            Evidence(
                id="E1",
                request=Analysis.model_validate({"start": "2025-01-01", "end": "2025-02-01"}),
                scope="Levi's",
                definitions="synthetic fixture",
                rows=[{"revenue": 1.0}],
                job_id="fixture",
                sql_hash="fixture",
                bytes_processed=0,
                queried_at="2026-10-25T00:00:00Z",
            )
        ],
    )
    store.save("bob", "fresh-cancel", "Keep me - seeded fixture", answer)
    store.preview("bob", "fresh-cancel", "Keep me")


async def run(root):
    settings = Settings.load()
    if not settings.google_cloud_project or not settings.gemini_api_key.get_secret_value():
        raise SystemExit("Set external GOOGLE_CLOUD_PROJECT and GEMINI_API_KEY first.")
    root.mkdir(parents=True, exist_ok=False)  # Never overwrite another run or the real library.
    settings.data_dir = root
    logging.getLogger("google").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    cases = json.loads((HERE / "cases.json").read_text())
    (root / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    fields = [
        "gemini_model",
        "thinking_level",
        "max_output_tokens",
        "commentary_enabled",
        "question_budget_usd",
        "turn_timeout_seconds",
        "max_model_calls",
        "model_min_interval_seconds",
        "max_queries",
    ]
    (root / "settings.json").write_text(
        json.dumps({k: getattr(settings, k) for k in fields}, indent=2) + "\n"
    )
    store = ReportStore(root / "isolated.sqlite3")
    executor = BigQueryExecutor(settings.google_cloud_project)
    pacer = ModelPacer(settings.model_min_interval_seconds)
    sessions = {}
    try:
        for c in cases:
            i, name, user, conv, prompt = c["id"], c["name"], c["user"], c["session"], c["prompt"]
            if i == 5:
                seed(store)  # Fresh TTL immediately before the cancellation scenario.
            if conv not in sessions:
                sessions[conv] = Analyst(
                    settings, DEMO_USERS[user], executor, store, "fresh-" + conv
                )
                sessions[conv].pacer = pacer
            analyst = sessions[conv]
            result = {
                "id": i,
                "name": name,
                "user": user,
                "conversation": analyst.conversation,
                "prompt": prompt,
                "expected": c["expected"],
                "reports_before": [vars(r) for r in store.list(user)],
                "pending_before": store.db.execute("SELECT count(*) FROM pending").fetchone()[0],
            }
            started = time.monotonic()
            print("START", i, name, flush=True)
            try:
                answer = await analyst.ask(prompt)
                result["answer"] = answer.model_dump(mode="json")
                for width in (80, 120):
                    console = Console(
                        file=io.StringIO(), width=width, record=True, color_system=None
                    )
                    display_answer(console, answer)
                    if analyst.preview:
                        console.print(render_preview(analyst.preview), markup=False)
                    (root / f"{i:02}-{name}-{width}.txt").write_text(console.export_text())
                if analyst.preview:
                    result["preview"] = {"count": len(analyst.preview.reports)}
            except Exception as exc:
                result.update(error=str(exc), error_type=type(exc).__name__)
            result.update(
                reports_after=[r.id for r in store.list(user)],
                pending_after=store.db.execute("SELECT count(*) FROM pending").fetchone()[0],
                seconds=round(time.monotonic() - started, 2),
            )
            (root / f"{i:02}-{name}.json").write_text(
                json.dumps(result, indent=2, default=str) + "\n"
            )
            print("END", i, name, result.get("error", "response captured"), flush=True)
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", required=True, help="Explicitly enable paid external calls"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New output directory; must not exist"
    )
    args = parser.parse_args()
    asyncio.run(run(args.output))


if __name__ == "__main__":
    main()
