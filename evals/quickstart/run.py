"""Live quick-start walkthrough with isolated report storage and row-level assertions."""

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
from retail_agent.models import DEMO_USERS
from retail_agent.render import display_answer
from retail_agent.reports import ReportStore

SCENARIOS = {
    "products": [
        "Show our top 5 products by revenue and, separately, by distinct customers in Q2 2025.",
        "Which products appear in both rankings?",
        "For those products, show revenue and distinct customers side by side.",
    ],
    "customers": [
        "Show our top 5 customers by revenue in 2025, using customer IDs.",
        "Add their order counts and average order value.",
        "Keep the three customers with the highest average order value among these five.",
    ],
    "months": [
        "Show our monthly revenue in 2025.",
        "Which three of those months generated the most revenue?",
        "Show those three months in chronological order instead.",
    ],
    "report": [
        "Prepare a Q2 2025 sales report with total revenue, monthly revenue, top 5 products and recommended actions for Q3 2025. Do not save it yet.",
        'Save it as "Q2 demo review".',
        "List my saved reports.",
    ],
}


async def run(root, selected=None):
    root.mkdir(parents=True, exist_ok=False)
    settings = Settings.load()
    settings.data_dir = root
    for name in ("google", "httpx"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    store = ReportStore(root / "isolated.sqlite3")
    executor = BigQueryExecutor(settings.google_cloud_project)
    results = []
    try:
        for scenario, questions in SCENARIOS.items():
            if selected and scenario != selected:
                continue
            agent = Analyst(settings, DEMO_USERS["alice"], executor, store, scenario)
            base = None
            for index, question in enumerate(questions):
                key = f"{scenario}-{index + 1}"
                print("START", key, question, flush=True)
                result = {"id": key, "question": question}
                start = time.monotonic()
                try:
                    answer = await agent.ask(question)
                    result["answer"] = answer.model_dump(mode="json")
                    if scenario != "report" or index == 0:
                        assert answer.quality_status == "validated", "Answer quality fallback"
                        assert "could not be validated" not in answer.text
                    if index == 0:
                        base = answer
                    if scenario == "products" and index:
                        a, b = base.evidence
                        expected = {r["product_id"] for r in a.rows} & {
                            r["product_id"] for r in b.rows
                        }
                        assert (
                            answer.view and {r["product_id"] for r in answer.view.rows} == expected
                        )
                        cols = answer.view.displayed_columns
                        if index == 1:
                            assert set(cols) == {"product_id", "product_name"}
                        else:
                            assert any(c.endswith(".revenue") for c in cols)
                            assert any(c.endswith(".customers") for c in cols)
                    if scenario == "customers" and index:
                        assert answer.view and answer.view.key == "user_id"
                        source = base.evidence[0]
                        rows = source.rows
                        if index == 2:
                            rows = sorted(
                                rows, key=lambda r: r["revenue"] / r["orders"], reverse=True
                            )[:3]
                        assert [r["user_id"] for r in answer.view.rows] == [
                            r["user_id"] for r in rows
                        ]
                        cols = answer.view.displayed_columns
                        assert any(c.endswith(".revenue") for c in cols)
                        assert any(c.endswith(".orders") for c in cols)
                        assert any(c.endswith(".revenue_per_order") for c in cols)
                        for row in answer.view.rows:
                            original = next(
                                r for r in source.rows if r["user_id"] == row["user_id"]
                            )
                            assert row[f"{source.id}.revenue_per_order"] == round(
                                original["revenue"] / original["orders"], 6
                            )
                    if scenario == "months" and index:
                        assert answer.view and answer.view.key == "month"
                        rows = sorted(
                            base.evidence[0].rows, key=lambda r: r["revenue"], reverse=True
                        )[:3]
                        if index == 2:
                            rows.sort(key=lambda r: r["month"])
                        assert [r["month"] for r in answer.view.rows] == [r["month"] for r in rows]
                        assert any(c.endswith(".revenue") for c in answer.view.displayed_columns)
                    if scenario == "report":
                        reports = store.list("alice")
                        assert len(reports) == (0 if index == 0 else 1)
                        if index == 0:
                            assert (
                                answer.intent.actions
                                and str(answer.intent.action_period.start) == "2025-07-01"
                            )
                        else:
                            assert reports[0].title == "Q2 demo review"
                            assert store.read("alice", reports[0].id).text == base.text
                            assert reports[0].id in answer.text
                    result["passed"] = True
                except Exception as exc:
                    result.update(passed=False, error=str(exc))
                result["seconds"] = round(time.monotonic() - start, 3)
                (root / f"{key}.json").write_text(json.dumps(result, indent=2))
                if "answer" in result:
                    for width in (80, 120):
                        console = Console(
                            file=io.StringIO(), record=True, width=width, color_system=None
                        )
                        display_answer(console, answer)
                        (root / f"{key}-{width}.txt").write_text(console.export_text())
                results.append({k: v for k, v in result.items() if k != "answer"})
                print(
                    "END",
                    key,
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=list(SCENARIOS))
    args = parser.parse_args()
    asyncio.run(run(args.output, args.scenario))
