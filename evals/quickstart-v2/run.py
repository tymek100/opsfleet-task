"""Seven exact documented conversations; live services, independent subset checks, isolated reports."""

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
from retail_agent.quality import required_facts
from retail_agent.render import display_answer, render_answer
from retail_agent.reports import ReportStore

CASES = json.loads(Path(__file__).with_name("cases.json").read_text())


class CountingExecutor:
    def __init__(self, project):
        self.delegate = BigQueryExecutor(project)
        self.calls = 0

    def execute(self, *args):
        self.calls += 1
        return self.delegate.execute(*args)


def check_initial(name, answer):
    assert answer.intent and answer.evidence
    expected = {
        "products": [
            ("product", "revenue", 5, ["revenue"]),
            ("product", "customers", 5, ["customers"]),
        ],
        "customers": [("customer", "revenue", 5, ["revenue"])],
        "months": [("month", "revenue", 12, ["revenue", "orders", "customers"])],
        "categories": [
            ("category", "revenue", 8, ["revenue", "orders", "customers", "revenue_per_order"])
        ],
        "report": [
            ("total", "revenue", 1, ["revenue"]),
            ("month", "revenue", 3, ["revenue"]),
            ("product", "revenue", 5, ["revenue"]),
        ],
    }.get(name, [])
    facts = set(required_facts(answer.intent, answer.evidence))
    for dimension, rank, count, measures in expected:
        source = next(
            e
            for e in answer.evidence
            if e.request.dimension == dimension and e.request.rank_by == rank
        )
        assert len(source.rows) == count, (name, dimension, "row count")
        assert all(f"{source.id}.r{i}.{m}" in facts for i in range(count) for m in measures), (
            name,
            "missing columns",
        )
    if name == "quarters":
        assert {"revenue_change", "revenue_change_pct"} <= set(answer.intent.comparison_metrics)


def check(name, index, answer, base, previous, store, calls, trace_events):
    if index == 0:
        check_initial(name, answer)
    text = render_answer(answer).replace("\\", "")
    assert not answer.warnings, answer.warnings
    assert not any(
        s in text
        for s in ("could not generate", "could not be validated", "unavailable", "Please clarify")
    ), text
    explanation = index == 2 and name in {"categories", "quarters", "inactivity"}
    if explanation:
        assert any(e["event"] == "commentary_accepted" for e in trace_events), (
            "No accepted LLM explanation"
        )
        assert calls == 0, "Explanation queried the database"
        assert "\n\n" not in answer.text.strip(), "Explanation should be one connected paragraph"
    elif name != "report" or index == 0:
        assert answer.quality_status == "validated", answer.text
    if name in {"products", "customers", "months", "categories"} and index:
        assert calls == 0, "Subset follow-up queried a different population"
        if not explanation:
            assert answer.view
            if name == "products":
                expected = {r["product_id"] for r in base.evidence[0].rows} & {
                    r["product_id"] for r in base.evidence[1].rows
                }
                assert {r["product_id"] for r in answer.view.rows} == expected
                if index == 2:
                    assert any(c.endswith(".revenue") for c in answer.view.displayed_columns)
                    assert any(c.endswith(".customers") for c in answer.view.displayed_columns)
            elif name == "customers":
                rows = base.evidence[0].rows
                if index == 2:
                    rows = sorted(rows, key=lambda r: r["revenue"] / r["orders"], reverse=True)[:3]
                assert [r["user_id"] for r in answer.view.rows] == [r["user_id"] for r in rows]
                for m in ("revenue", "orders", "revenue_per_order"):
                    assert any(c.endswith("." + m) for c in answer.view.displayed_columns)
            elif name == "months":
                rows = sorted(base.evidence[0].rows, key=lambda r: r["revenue"], reverse=True)[:3]
                if index == 2:
                    rows.sort(key=lambda r: r["month"])
                assert [r["month"] for r in answer.view.rows] == [r["month"] for r in rows]
                assert any(c.endswith(".orders") for c in answer.view.displayed_columns)
            elif name == "categories":
                best = max(base.evidence[0].rows, key=lambda r: r["revenue"] / r["orders"])
                assert (
                    len(answer.view.rows) == 1
                    and answer.view.rows[0]["category"] == best["category"]
                )
                assert (
                    f"{best['revenue'] / best['orders']:,.2f}" in text
                    and str(best["orders"]) in text
                )
        if name == "categories" and explanation:
            best = max(base.evidence[0].rows, key=lambda r: r["revenue"] / r["orders"])
            assert f"{best['revenue']:,.2f}" in text and str(best["orders"]) in text
    if name == "quarters":
        if not explanation:
            assert str(answer.intent.period.start) == "2026-01-01"
            assert str(answer.intent.comparison.start) == "2025-10-01"
        if index == 1:
            assert "90" in text and "92" in text
        if explanation:
            current = next(
                e.rows[0]["revenue"]
                for e in previous.evidence
                if str(e.request.start) == "2026-01-01"
            )
            old = next(
                e.rows[0]["revenue"]
                for e in previous.evidence
                if str(e.request.start) == "2025-10-01"
            )
            assert f"{abs((current - old) / old * 100):.2f}" in text
    if name == "inactivity" and not explanation:
        assert answer.intent.inactivity_days == (90 if index == 0 else 60)
        assert str(answer.intent.period.start) == "2025-10-01"
        assert str(answer.intent.period.end) == "2026-01-01"
        assert all(
            e.request.inactivity_days == answer.intent.inactivity_days for e in answer.evidence
        )
        assert all(
            "eligible_customers" in row and "inactive_customers" in row
            for e in answer.evidence
            for row in e.rows
        )
    reports = store.list("alice")
    if name == "report":
        assert len(reports) == (0 if index == 0 else 1)
        if index == 0:
            assert str(answer.intent.action_period.start) == "2025-07-01"
            assert "Proposed target" not in text
        else:
            assert reports[0].title == "Q2 demo review"
            assert store.read("alice", reports[0].id) == base
            if index == 2:
                assert "Q2 demo review" in text
    else:
        assert not reports


async def run(root, only):
    root.mkdir(parents=True, exist_ok=False)
    settings = Settings.load()
    settings.data_dir = root
    for logger in ("google", "httpx"):
        logging.getLogger(logger).setLevel(logging.CRITICAL)
    results = []
    for case in CASES:
        name = case["id"]
        if only and name not in only:
            continue
        store = ReportStore(root / f"{name}.sqlite3")
        executor = CountingExecutor(settings.google_cloud_project)
        analyst = Analyst(settings, DEMO_USERS["alice"], executor, store, name)
        base = previous = None
        try:
            for index, question in enumerate(case["questions"]):
                key = f"{name}-{index + 1}"
                print("START", key, flush=True)
                record = {"id": key, "question": question}
                start = time.monotonic()
                before = executor.calls
                try:
                    answer = await analyst.ask(question)
                    record["answer"] = answer.model_dump(mode="json")
                    events = [
                        json.loads(line) for line in (root / "events.log").read_text().splitlines()
                    ]
                    events = [e for e in events if e["trace_id"] == answer.trace_id]
                    check(
                        name, index, answer, base, previous, store, executor.calls - before, events
                    )
                    if index == 0:
                        base = answer
                    previous = answer
                    record["passed"] = True
                    for width in (80, 120):
                        console = Console(
                            file=io.StringIO(), record=True, width=width, color_system=None
                        )
                        display_answer(console, answer)
                        (root / f"{key}-{width}.txt").write_text(console.export_text())
                except Exception as exc:
                    record.update(passed=False, error=str(exc) or type(exc).__name__)
                record["seconds"] = round(time.monotonic() - start, 3)
                record["queries"] = executor.calls - before
                (root / f"{key}.json").write_text(json.dumps(record, indent=2))
                results.append({k: v for k, v in record.items() if k != "answer"})
                print(
                    "END",
                    key,
                    record["passed"],
                    record.get("error", ""),
                    record["seconds"],
                    flush=True,
                )
                if not record["passed"]:
                    break
        finally:
            store.close()
    (root / "summary.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", nargs="+", choices=[c["id"] for c in CASES])
    args = parser.parse_args()
    asyncio.run(run(args.output, args.only))
