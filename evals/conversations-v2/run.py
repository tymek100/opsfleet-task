"""Fifteen English conversation pairs; opt-in live calls with isolated library state."""

import argparse
import asyncio
import io
import json
import logging
import time
from pathlib import Path

from rich.console import Console

import retail_agent.agent as runtime
from retail_agent.bigquery import BigQueryExecutor
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS
from retail_agent.render import display_answer
from retail_agent.reports import ReportStore


def check(case, turn, answer, plan, base, before, after):
    cid = case["id"]
    if turn == 0 and cid in (13, 14, 15):
        assert plan.route == {13: "delete_preview", 14: "access_denied", 15: "unsupported"}[cid], (
            plan.route
        )
        assert not answer.evidence
        if cid == 13:
            assert after["pending"] == 1 and after["reports"] == before["reports"]
        return
    if turn == 1 and cid == 12:
        assert plan.route == "save" and len(after["reports"]) == len(before["reports"]) + 1
        assert after["reports"][-1]["title"] == "Winter review v2"
        return
    if turn == 1 and cid == 13:
        assert after["pending"] == 0 and after["reports"] == before["reports"]
        assert "Winter review v2" in answer.text and "cancelled" in answer.text.lower()
        return
    assert answer.quality_status == "validated", answer.quality_status
    assert answer.evidence
    if cid == 7:
        intent = answer.intent
        current = next(e for e in answer.evidence if e.request.start == intent.period.start).rows[
            0
        ]["revenue"]
        baseline = next(
            e for e in answer.evidence if e.request.start == intent.comparison.start
        ).rows[0]["revenue"]
        assert f"{current - baseline:+,.2f}" in answer.text
        assert f"{(current / baseline - 1) * 100:+.2f}%" in answer.text
    if turn == 0:
        intent = answer.intent
        assert intent and [str(intent.period.start), str(intent.period.end)] == case["period"]
        if cid == 12:
            assert intent.actions and str(intent.action_period.start) == "2026-01-01"
            assert {e.request.dimension.value for e in answer.evidence} == {
                "total",
                "month",
                "product",
            }
            assert before == after, "Draft saved implicitly"
        else:
            assert all(e.request.dimension.value == case["dimension"] for e in answer.evidence)
        if cid not in (7, 10, 12):
            assert answer.evidence[0].request.rank_by == case["rank"]
        if cid == 8:
            assert intent.completed_only
        if cid == 9:
            assert set(intent.product_ids) == {8252, 23740}
            assert {r["product_id"] for r in answer.evidence[0].rows} == {8252, 23740}
        if cid == 10:
            assert intent.inactivity_days == 90
        if cid == 7:
            assert str(intent.comparison.start) == "2025-07-01"
            assert set(intent.comparison_metrics) == {"revenue_change", "revenue_change_pct"}
        if "limit" in case:
            assert answer.evidence[0].request.limit == case["limit"]
        return
    if cid in (1, 2, 3, 4, 5, 6, 11):
        assert answer.view and plan.view, "Expected operations on existing results"
        assert answer.evidence == base.evidence
        source = base.evidence[0]
        rows = source.rows
        view = answer.view
        key = {
            1: "product_id",
            2: "user_id",
            3: "month",
            4: "category",
            5: "state",
            6: "brand",
            11: "product_id",
        }[cid]
        selectors = {
            1: lambda: rows[2:],
            2: lambda: [r for r in rows if r["orders"] >= 2],
            3: lambda: [r for r in rows if r["revenue"] < 2500],
            4: lambda: sorted(rows, key=lambda r: r["revenue"] / r["orders"], reverse=True),
            5: lambda: rows,
            6: lambda: sorted(rows, key=lambda r: r["brand"]),
            11: lambda: [],
        }
        expected = selectors[cid]()
        assert [r[key] for r in view.rows] == [r[key] for r in expected], (
            "Incorrect selected entities or order"
        )
        cols = view.displayed_columns
        if cid in (2, 11):
            assert plan.view.output == "count", "Expected count-only result"
            assert str(len(expected)) in answer.text
            if len(expected) == 1:
                assert (
                    "1 customer matches" in answer.text
                    if cid == 2
                    else "1 product matches" in answer.text
                ), "Use a singular noun and verb for a count of one"
        elif cid == 1:
            assert f"{source.id}.units" in cols
        elif cid == 4:
            assert f"{source.id}.revenue_per_order" in cols and f"{source.id}.revenue" in cols
            assert plan.view.sort_by == f"{source.id}.revenue_per_order" and plan.view.descending
        elif cid == 5:
            assert f"{source.id}.revenue" in cols and f"{source.id}.customers" in cols
        elif cid == 6:
            assert set(cols) == {"brand", f"{source.id}.revenue"}
        else:
            assert f"{source.id}.revenue" in cols
        for r in view.rows:
            original = next(x for x in rows if x[key] == r[key])
            for metric in ("revenue", "units", "orders", "customers"):
                assert r[f"{source.id}.{metric}"] == original[metric]
        assert before == after
    else:
        intent = answer.intent
        assert intent and plan.route == "analysis"
        if cid == 7:
            assert (
                str(intent.period.start) == "2025-07-01"
                and str(intent.comparison.start) == "2025-10-01"
            )
            assert set(intent.comparison_metrics) == {"revenue_change", "revenue_change_pct"}
        if cid == 8:
            assert not intent.completed_only and intent.period == base.intent.period
            assert answer.evidence[0].request.limit == 5
        if cid == 9:
            assert (
                set(intent.product_ids) == {8252, 23740}
                and str(intent.period.start) == "2025-10-01"
            )
        if cid == 10:
            assert intent.inactivity_days == 60 and intent.period == base.intent.period
        if cid == 14:
            assert str(intent.period.start) == "2025-04-01" and all(
                e.scope == "Calvin Klein" for e in answer.evidence
            )
        if cid == 15:
            assert (
                str(intent.period.start) == "2025-01-01" and str(intent.period.end) == "2025-04-01"
            )


async def run(root, selected):
    root.mkdir(parents=True, exist_ok=False)
    settings = Settings.load()
    settings.data_dir = root
    for name in ("google", "httpx"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    store = ReportStore(root / "isolated.sqlite3")
    executor = BigQueryExecutor(settings.google_cloud_project)
    cases = json.loads(Path(__file__).with_name("cases.json").read_text())
    original = runtime.propose_plan
    plans = []

    async def capture(*args, **kwargs):
        plan = await original(*args, **kwargs)
        plans.append(plan)
        return plan

    runtime.propose_plan = capture
    results = []

    def state(owner):
        return {
            "reports": [{"id": r.id, "title": r.title} for r in store.list(owner)],
            "pending": store.db.execute("SELECT count(*) FROM pending").fetchone()[0],
        }

    try:
        for case in cases:
            if selected and case["id"] not in selected:
                continue
            agent = runtime.Analyst(
                settings, DEMO_USERS[case["user"]], executor, store, f"pair-{case['id']}"
            )
            base = None
            for turn, question in enumerate(case["questions"]):
                key = f"{case['id']:02}-{turn + 1}"
                result = {
                    "id": key,
                    "case": case["id"],
                    "turn": turn,
                    "question": question,
                    "user": case["user"],
                }
                print("START", key, question, flush=True)
                start = time.monotonic()
                before = state(case["user"])
                plans.clear()
                try:
                    answer = await agent.ask(question)
                    result.update(
                        answer=answer.model_dump(mode="json"),
                        plan=plans[-1].model_dump(mode="json"),
                        before=before,
                        after=state(case["user"]),
                    )
                    check(case, turn, answer, plans[-1], base, before, result["after"])
                    result["passed"] = True
                    if turn == 0:
                        base = answer
                except Exception as exc:
                    result.update(
                        passed=False,
                        error=str(exc) or type(exc).__name__,
                        error_type=type(exc).__name__,
                    )
                    if turn == 0 and "answer" in result:
                        base = answer
                result["seconds"] = round(time.monotonic() - start, 3)
                (root / f"{key}.json").write_text(json.dumps(result, indent=2))
                if "answer" in result:
                    for width in (80, 120):
                        console = Console(
                            file=io.StringIO(), record=True, width=width, color_system=None
                        )
                        display_answer(console, answer)
                        (root / f"{key}-{width}.txt").write_text(console.export_text())
                results.append(
                    {
                        k: v
                        for k, v in result.items()
                        if k not in ("answer", "plan", "before", "after")
                    }
                )
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
        runtime.propose_plan = original
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, nargs="+")
    args = parser.parse_args()
    asyncio.run(run(args.output, args.cases))
