"""Replay a supplied analytical context against live Gemini; no new data queries permitted."""

import argparse
import asyncio
import io
import json
import logging
import time
from pathlib import Path

from rich.console import Console

from retail_agent.agent import Analyst
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, Answer
from retail_agent.render import display_answer
from retail_agent.reports import ReportStore

QUESTIONS = [
    ("second", "what was the second position from top?", [1]),
    ("last", "Which category was last in the displayed table?", [-1]),
    ("range", "Show positions two through four from that sorted table.", [1, 2, 3]),
    ("first", "Just show the first category from that reordered list.", [0]),
    ("outside", "What was at position ten in that displayed list?", []),
]


class NoQueries:
    def execute(self, *args, **kwargs):
        raise AssertionError("A positional follow-up must reuse the displayed result")


async def run(context, root, only):
    root.mkdir(parents=True, exist_ok=False)
    settings = Settings.load()
    settings.data_dir = root
    for name in ("google", "httpx"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    answers = [Answer.model_validate(a) for a in json.loads(context.read_text())]
    assert answers[-1].view
    store = ReportStore(root / "isolated.sqlite3")
    results = []
    try:
        for name, question, indexes in QUESTIONS:
            if only and name not in only:
                continue
            analyst = Analyst(settings, DEMO_USERS["alice"], NoQueries(), store, name)
            analyst.intent = answers[-1].intent
            analyst.last_answer = answers[-1].model_copy(deep=True)
            analyst.history = [
                {"question": q, "answer": a.model_dump_json()}
                for q, a in zip(
                    [
                        "Show our six highest-revenue product categories in 2025.",
                        "For these categories, add revenue per order and sort the displayed categories by that value, highest first.",
                    ],
                    answers,
                    strict=True,
                )
            ]
            result = {
                "id": name,
                "question": question,
                "context": "Replayed two previously captured user turns; real Gemini, no new BigQuery query.",
            }
            print("START", name, flush=True)
            start = time.monotonic()
            try:
                answer = await analyst.ask(question)
                result["answer"] = answer.model_dump(mode="json")
                expected = [answers[-1].view.rows[i]["category"] for i in indexes]
                assert answer.view and [r["category"] for r in answer.view.rows] == expected, (
                    "Wrong displayed positions"
                )
                assert answer.evidence == answers[-1].evidence
                assert answer.quality_status == "validated"
                result["passed"] = True
                for width in (80, 120):
                    console = Console(
                        file=io.StringIO(), record=True, width=width, color_system=None
                    )
                    display_answer(console, answer)
                    (root / f"{name}-{width}.txt").write_text(console.export_text())
            except Exception as exc:
                result.update(passed=False, error=str(exc) or type(exc).__name__)
            result["seconds"] = round(time.monotonic() - start, 3)
            results.append({k: v for k, v in result.items() if k != "answer"})
            (root / f"{name}.json").write_text(json.dumps(result, indent=2))
            print(
                "END",
                name,
                result["passed"],
                result.get("error", ""),
                result["seconds"],
                flush=True,
            )
        (root / "summary.json").write_text(json.dumps(results, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", nargs="+", choices=[q[0] for q in QUESTIONS])
    args = parser.parse_args()
    asyncio.run(run(args.context, args.output, args.only))
