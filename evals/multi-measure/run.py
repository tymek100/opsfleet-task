"""Live English multi-measure checks: explicit expected output contracts, isolated storage."""

import asyncio
import io
import json
import logging
from pathlib import Path

from rich.console import Console

from retail_agent.agent import Analyst
from retail_agent.bigquery import BigQueryExecutor
from retail_agent.config import Settings
from retail_agent.intent import completion_issues
from retail_agent.models import DEMO_USERS
from retail_agent.quality import required_facts
from retail_agent.render import display_answer
from retail_agent.reports import ReportStore

CASES = [
    (
        "original",
        "Show our top 20 products by revenue in 2025. Include product ID, product name, revenue, number of orders, units sold, distinct customers, and revenue per order. Also show a monthly breakdown of revenue, orders, and distinct customers for the full year.",
        [
            ("product", "revenue", 20, ["orders", "units", "customers", "revenue_per_order"]),
            ("month", "revenue", 12, ["orders", "customers"]),
        ],
    ),
    (
        "customers",
        "For Q2 2025, list our top 8 customers by total spend, with their customer IDs, spend, orders, units purchased and average order value. Also give quarter totals for revenue, orders and distinct customers.",
        [
            ("customer", "revenue", 8, ["orders", "units", "revenue_per_order"]),
            ("total", "revenue", 1, ["orders", "customers"]),
        ],
    ),
    (
        "categories",
        "Show the 6 highest-revenue categories in 2025, with revenue, units, distinct customers and revenue per unit. Separately show monthly revenue and units for 2025.",
        [
            ("category", "revenue", 6, ["units", "customers", "revenue_per_unit"]),
            ("month", "revenue", 12, ["units"]),
        ],
    ),
    (
        "dual",
        "For Q3 2025, show two separate top-5 product rankings: one by units sold, with units and revenue; another by distinct customers, with customers, revenue and orders.",
        [("product", "units", 5, ["revenue"]), ("product", "customers", 5, ["revenue", "orders"])],
    ),
    (
        "completed",
        "Using only completed orders and items in Q4 2025, show monthly revenue, orders, distinct customers and revenue per order, plus the top 7 products by revenue with revenue, orders and units per order.",
        [
            ("month", "revenue", 3, ["orders", "customers", "revenue_per_order"]),
            ("product", "revenue", 7, ["orders", "units_per_order"]),
        ],
    ),
    (
        "orders",
        "For the first half of 2025, rank our top 9 products by number of orders. Include orders, revenue, units sold and revenue per unit. Also show total revenue, orders and units for that half-year.",
        [
            ("product", "orders", 9, ["revenue", "units", "revenue_per_unit"]),
            ("total", "revenue", 1, ["orders", "units"]),
        ],
    ),
]


async def run(root: Path, only: str | None = None):
    root.mkdir(parents=True, exist_ok=False)
    settings = Settings.load()
    settings.data_dir = root
    for name in ("google", "httpx"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    store = ReportStore(root / "isolated.sqlite3")
    results = []
    try:
        for name, question, expected in CASES:
            if only and name != only:
                continue
            print("START", name, flush=True)
            record = {"question": question, "expected": expected}
            try:
                agent = Analyst(
                    settings,
                    DEMO_USERS["alice"],
                    BigQueryExecutor(settings.google_cloud_project),
                    store,
                    name,
                )
                answer = await agent.ask(question)
                record["answer"] = answer.model_dump(mode="json")
                assert answer.intent and answer.quality_status == "validated"
                facts = required_facts(answer.intent, answer.evidence)
                assert not completion_issues(answer.intent, answer.evidence, facts)
                for dimension, rank, count, measures in expected:
                    matching = [
                        e
                        for e in answer.evidence
                        if e.request.dimension == dimension and e.request.rank_by == rank
                    ]
                    assert len(matching) == 1, (dimension, rank, "wrong population")
                    e = matching[0]
                    assert len(e.rows) == count, (dimension, "wrong row count")
                    required = {rank, *measures}
                    for i in range(count):
                        assert all(f"{e.id}.r{i}.{m}" in facts for m in required), (
                            dimension,
                            required,
                            "missing measure",
                        )
                    # Independently recompute requested ratios from raw aggregate columns.
                    for row in e.rows:
                        for metric, numerator, denominator in [
                            ("revenue_per_order", "revenue", "orders"),
                            ("revenue_per_unit", "revenue", "units"),
                            ("units_per_order", "units", "orders"),
                        ]:
                            if metric in required and row[denominator]:
                                assert f"{row[numerator] / row[denominator]:,.2f}" in answer.text
                if name == "completed":
                    assert all(e.request.completed_only for e in answer.evidence)
                assert not store.list("alice")
                record["passed"] = True
                for width in (80, 120):
                    console = Console(
                        file=io.StringIO(), record=True, width=width, color_system=None
                    )
                    display_answer(console, answer)
                    (root / f"{name}-{width}.txt").write_text(console.export_text())
            except Exception as exc:
                record.update(passed=False, error=str(exc) or type(exc).__name__)
            (root / f"{name}.json").write_text(json.dumps(record, indent=2))
            results.append({"id": name, "passed": record["passed"], "error": record.get("error")})
            print("END", results[-1], flush=True)
        (root / "summary.json").write_text(json.dumps(results, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", choices=[case[0] for case in CASES])
    args = parser.parse_args()
    asyncio.run(run(args.output, args.only))
