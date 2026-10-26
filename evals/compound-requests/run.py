"""Compare pasted multi-step requests with separate turns using live Gemini/BigQuery."""

import argparse
import asyncio
import json
from pathlib import Path

from retail_agent.agent import Analyst
from retail_agent.bigquery import BigQueryExecutor
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS
from retail_agent.reports import ReportStore

QUESTIONS = [
    "Show our top 5 customers by revenue in 2025, using customer IDs.",
    "Add their order counts and average order value.",
    "Keep the three customers with the highest average order value among these five.",
]


async def run(root: Path, only: str | None = None) -> None:
    root.mkdir(parents=True, exist_ok=False)
    settings = Settings.load()
    settings.data_dir = root
    store = ReportStore(root / "isolated.sqlite3")
    summary = []
    try:
        for name, questions, dimension, rank, size, key, descending in [
            ("pasted", ["\n".join(QUESTIONS)], "customer", "revenue", 5, "user_id", True),
            ("separate", QUESTIONS, "customer", "revenue", 5, "user_id", True),
            (
                "products",
                [
                    "For Q3 2025, first find our top 8 products by units sold. Include revenue, orders and revenue per order, then keep only the 3 with the lowest revenue per order within those eight."
                ],
                "product",
                "units",
                8,
                "product_id",
                False,
            ),
        ]:
            if only and name != only:
                continue
            print("START", name, flush=True)
            analyst = Analyst(
                settings,
                DEMO_USERS["alice"],
                BigQueryExecutor(settings.google_cloud_project),
                store,
                name,
            )
            record = {"questions": questions, "answers": []}
            try:
                for question in questions:
                    answer = await analyst.ask(question)
                    record["answers"].append(answer.model_dump(mode="json"))
                assert answer.view, "No final selected view"
                assert len(answer.evidence) == 1, "Unexpected extra population"
                source = answer.evidence[0]
                assert source.request.dimension == dimension and source.request.rank_by == rank
                assert source.request.limit == size and len(source.rows) == size
                expected = sorted(
                    source.rows, key=lambda row: row["revenue"] / row["orders"], reverse=descending
                )[:3]
                assert [row[key] for row in answer.view.rows] == [row[key] for row in expected]
                assert "E1.orders" in answer.view.displayed_columns
                assert "E1.revenue_per_order" in answer.view.displayed_columns
                assert answer.quality_status == "validated" and not answer.warnings
                assert not store.list("alice")
                record["passed"] = True
            except Exception as exc:
                record.update(passed=False, error=str(exc) or type(exc).__name__)
            (root / f"{name}.json").write_text(json.dumps(record, indent=2))
            summary.append({k: v for k, v in record.items() if k != "answers"})
            print("END", name, record["passed"], record.get("error", ""), flush=True)
        (root / "summary.json").write_text(json.dumps(summary, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", choices=["pasted", "separate", "products"])
    args = parser.parse_args()
    asyncio.run(run(args.output, args.only))
