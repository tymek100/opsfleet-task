"""Opt-in live out-of-domain checks in fresh sessions and after retail analysis."""

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

from retail_agent.agent import Analyst
from retail_agent.bigquery import BigQueryExecutor
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS
from retail_agent.reports import ReportStore

QUESTIONS = [
    ("weather-en", "What is the weather today?"),
    ("age-en", "How old am I?"),
]


async def run(root):
    root.mkdir(parents=True, exist_ok=False)
    settings = Settings.load()
    settings.data_dir = root
    for name in ("google", "httpx"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    store = ReportStore(root / "isolated.sqlite3")
    executor = BigQueryExecutor(settings.google_cloud_project)
    results = []

    def create(name):
        return Analyst(settings, DEMO_USERS["alice"], executor, store, name)

    async def ask(agent, case, question, expect):
        before = agent.last_answer
        prior_intent = agent.intent.model_dump(mode="json") if agent.intent else None
        state = [
            (t, store.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
            for t in ("reports", "pending")
        ]
        result = {"id": case, "question": question, "expect": expect}
        print("START", case, flush=True)
        started = time.monotonic()
        try:
            answer = await agent.ask(question)
            result["answer"] = answer.model_dump(mode="json")
            events = [json.loads(line) for line in (root / "events.log").read_text().splitlines()]
            events = [e for e in events if e.get("trace_id") == answer.trace_id]
            result["routes"] = [e["route"] for e in events if e["event"] == "plan_proposed"]
            result["query_events"] = [e["event"] for e in events if e["event"].startswith("query_")]
            if expect == "refusal":
                assert result["routes"] == ["unsupported"], result["routes"]
                assert not answer.evidence and not result["query_events"], (
                    "Unexpected query or data answer"
                )
                assert agent.last_answer is before, "Last successful answer overwritten"
                assert (
                    agent.intent.model_dump(mode="json") if agent.intent else None
                ) == prior_intent
                assert state == [
                    (t, store.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
                    for t in ("reports", "pending")
                ]
            elif expect == "analysis":
                assert answer.quality_status == "validated" and answer.evidence
            else:
                assert answer.view and answer.quality_status == "validated"
                assert not result["query_events"]
                source = before.evidence[0]
                wanted = sorted(source.rows, key=lambda r: r["revenue"], reverse=True)[:2]
                assert [r["month"] for r in answer.view.rows] == [r["month"] for r in wanted]
                for row, expected in zip(answer.view.rows, wanted, strict=True):
                    assert row[f"{source.id}.revenue"] == expected["revenue"]
            result["passed"] = True
        except Exception as exc:
            result.update(passed=False, error=str(exc) or type(exc).__name__)
        result["seconds"] = round(time.monotonic() - started, 3)
        (root / f"{case}.json").write_text(json.dumps(result, indent=2))
        results.append({k: v for k, v in result.items() if k != "answer"})
        print(
            "END",
            case,
            result["passed"],
            result.get("error", result.get("answer", {}).get("text", "")),
            flush=True,
        )

    try:
        for name, question in QUESTIONS:
            await ask(create(name), "fresh-" + name, question, "refusal")
        follow = create("followups")
        await ask(follow, "baseline", "Show our monthly revenue in 2025.", "analysis")
        for name, question in QUESTIONS:
            await ask(follow, "follow-" + name, question, "refusal")
        await ask(
            follow,
            "return-to-analysis",
            "Back to the monthly results: show the two months with the highest revenue.",
            "resume",
        )
        (root / "summary.json").write_text(json.dumps(results, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output))
