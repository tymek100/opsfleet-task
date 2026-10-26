"""Opt-in live follow-ups; independent set/row assertions against fresh source rankings."""

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

QUESTIONS = [
    "Which products appear in both rankings?",
    "For those products, show revenue and distinct customers side by side.",
    "Add their original position in each ranking and average order value.",
    "Which products from the original revenue top 5 are absent from the original customer top 5?",
    "How many products are in that last subset? Just give me the count.",
    "Now list the opposite: products in the original customer top 5 but not the revenue top 5.",
    "Combine the two original top-five lists into one list of unique products, showing names and IDs only.",
    "From the original revenue ranking, keep only products with revenue above 200 and show their revenue.",
    "Order those remaining products by revenue from lowest to highest, keeping the same columns.",
    "For those same products, show revenue in Q3 2025 instead.",
]


async def run(root):
    settings = Settings.load()
    root.mkdir(parents=True, exist_ok=False)
    settings.data_dir = root
    for name in ("google", "httpx"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    store = ReportStore(root / "isolated.sqlite3")
    agent = Analyst(
        settings,
        DEMO_USERS["alice"],
        BigQueryExecutor(settings.google_cloud_project),
        store,
        "followups",
    )
    results = []
    prompts = [
        "Show our top 5 products by revenue and, separately, by number of distinct customers in Q2 2025.",
        *QUESTIONS,
    ]
    try:
        base = None
        for i, prompt in enumerate(prompts):
            print("START", i, prompt, flush=True)
            start = time.monotonic()
            result = {"id": i, "question": prompt}
            try:
                answer = await agent.ask(prompt)
                result["answer"] = answer.model_dump(mode="json")
                if i == 0:
                    base = answer
                    assert len(base.evidence) == 2
                    revenue = next(e for e in base.evidence if e.request.rank_by == "revenue")
                    customers = next(e for e in base.evidence if e.request.rank_by == "customers")
                    a = {r["product_id"] for r in revenue.rows}
                    b = {r["product_id"] for r in customers.rows}
                    filtered = {r["product_id"] for r in revenue.rows if r["revenue"] > 200}
                elif i <= 9:
                    assert answer.view is not None, (
                        "Expected a derived view, not repeated source tables"
                    )
                    expected = {
                        1: a & b,
                        2: a & b,
                        3: a & b,
                        4: a - b,
                        5: a - b,
                        6: b - a,
                        7: a | b,
                        8: filtered,
                        9: filtered,
                    }[i]
                    assert {r["product_id"] for r in answer.view.rows} == expected, (
                        "Wrong entity subset"
                    )
                    cols = answer.view.displayed_columns
                    if i in (1, 7):
                        assert set(cols) == {"product_id", "product_name"}, cols
                    if i == 2:
                        assert any(c.endswith(".revenue") for c in cols) and any(
                            c.endswith(".customers") for c in cols
                        ), cols
                    if i == 3:
                        assert any(c.endswith(".revenue") for c in cols) and any(
                            c.endswith(".customers") for c in cols
                        ), cols
                        assert (
                            f"{revenue.id}.rank" in cols
                            and f"{customers.id}.rank" in cols
                            and any(c.endswith(".revenue_per_order") for c in cols)
                        ), cols
                    if i == 5:
                        assert (
                            f"**{len(expected)} products match" in answer.text
                            and "| Product" not in answer.text
                        )
                    if i == 9:
                        amounts = [r[f"{revenue.id}.revenue"] for r in answer.view.rows]
                        assert amounts == sorted(amounts)
                    # Independent row oracle: all carried source metrics and original ranks must match.
                    for row in answer.view.rows:
                        for e in base.evidence:
                            original = next(
                                (
                                    (j, r)
                                    for j, r in enumerate(e.rows)
                                    if r["product_id"] == row["product_id"]
                                ),
                                None,
                            )
                            for metric in (
                                "revenue",
                                "customers",
                                "orders",
                                "units",
                                "rank",
                                "revenue_per_order",
                            ):
                                key = f"{e.id}.{metric}"
                                if key not in row:
                                    continue
                                if original is None:
                                    assert row[key] is None, (key, row)
                                else:
                                    j, r = original
                                    expected_value = (
                                        j + 1
                                        if metric == "rank"
                                        else (
                                            round(r["revenue"] / r["orders"], 6)
                                            if r["orders"]
                                            else None
                                        )
                                        if metric == "revenue_per_order"
                                        else r[metric]
                                    )
                                    assert row[key] == expected_value, (
                                        key,
                                        row[key],
                                        expected_value,
                                    )
                else:
                    assert answer.view is None and answer.intent
                    assert set(answer.intent.product_ids) == filtered
                    assert (
                        str(answer.intent.period.start) == "2025-07-01"
                        and str(answer.intent.period.end) == "2025-10-01"
                    )
                    assert all(set(e.request.product_ids) == filtered for e in answer.evidence)
                assert answer.quality_status == "validated", "Unexpected figures-only fallback"
                assert "could not be validated" not in answer.text
                result["passed"] = True
            except Exception as exc:
                result.update(passed=False, error=str(exc), error_type=type(exc).__name__)
            result["seconds"] = round(time.monotonic() - start, 3)
            (root / f"{i:02}.json").write_text(json.dumps(result, indent=2))
            if "answer" in result:
                for width in (80, 120):
                    console = Console(
                        file=io.StringIO(), record=True, width=width, color_system=None
                    )
                    display_answer(console, answer)
                    (root / f"{i:02}-{width}.txt").write_text(console.export_text())
            results.append({k: v for k, v in result.items() if k != "answer"})
            print(
                "END", i, result["passed"], result.get("error", ""), result["seconds"], flush=True
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
