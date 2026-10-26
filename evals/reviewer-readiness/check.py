"""Offline acceptance against captured intent, evidence, independent SQL and state."""

import argparse
import json
import math
from pathlib import Path

from oracle import same_rows


def evaluate(root):
    cases = {c["id"]: c for p in root.glob("[0-9][0-9]-*.json") if (c := json.loads(p.read_text()))}
    checks = []

    def check(name, ok):
        checks.append({"check": name, "pass": bool(ok)})

    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    expected = set(summary.get("scenario_ids", range(1, 11)))
    full = set(range(1, 11))
    check(
        "complete declared scenario set", expected in (full, full - {7}) and set(cases) == expected
    )
    for i in sorted(expected):
        c = cases[i]
        a = c.get("answer", {})
        check(
            f"{i}: expected outcome",
            c.get("code") == "privacy_input" if i == 7 else bool(a) and not c.get("error"),
        )
        if i <= 6:
            check(
                f"{i}: validated analytical evidence",
                a.get("quality_status") == "validated" and a.get("evidence"),
            )
        if i <= 8:
            check(
                f"{i}: no implicit save/preview", not c["reports_after"] and c["pending_after"] == 0
            )
    evidence = {i: cases[i]["answer"]["evidence"] for i in range(1, 7)}
    for i, start, end in [
        (1, "2025-04-01", "2025-07-01"),
        (2, "2025-04-01", "2025-07-01"),
        (3, "2025-05-01", "2025-06-01"),
        (4, "2025-07-01", "2025-10-01"),
        (6, "1901-02-01", "1901-03-01"),
    ]:
        check(
            f"{i}: exact date boundaries",
            all(e["request"]["start"] == start and e["request"]["end"] == end for e in evidence[i]),
        )
    check(
        "separate seven-product rankings",
        {(e["request"]["dimension"], e["request"]["rank_by"], len(e["rows"])) for e in evidence[1]}
        == {("product", "revenue", 7), ("product", "customers", 7)},
    )
    check(
        "follow-up has only total and monthly output",
        {e["request"]["dimension"] for e in evidence[2]} == {"total", "month"},
    )
    check(
        "all three follow-up months",
        any(len(e["rows"]) == 3 for e in evidence[2] if e["request"]["dimension"] == "month"),
    )
    check(
        "inactivity definition and snapshots",
        len(evidence[3]) == 1
        and evidence[3][0]["request"]["kind"] == "churn"
        and evidence[3][0]["request"]["inactivity_days"] == 90
        and len(evidence[3][0]["rows"]) == 2,
    )
    report = cases[4]["answer"]
    check(
        "report requested sections",
        {e["request"]["dimension"] for e in evidence[4]} == {"total", "month", "product"},
    )
    check(
        "three report products",
        any(len(e["rows"]) == 3 for e in evidence[4] if e["request"]["dimension"] == "product"),
    )
    check(
        "action period and caveats",
        report["intent"]["action_period"] == {"start": "2025-10-01", "end": "2026-01-01"}
        and "01 Oct 2025 to 31 Dec 2025" in report["text"]
        and any(label in report["text"] for label in ("Proposed actions", "Suggested next steps"))
        and any(
            label in report["text"] for label in ("not forecasts", "does not establish causes")
        ),
    )
    comparison = cases[5]["answer"]
    intent = comparison["intent"]
    check(
        "explicit reverse-time baseline",
        intent["period"] == {"start": "2024-10-01", "end": "2025-01-01"}
        and intent["comparison"] == {"start": "2025-04-01", "end": "2025-07-01"},
    )
    current = next(e for e in evidence[5] if e["request"]["start"] == "2024-10-01")["rows"][0][
        "revenue"
    ]
    baseline = next(e for e in evidence[5] if e["request"]["start"] == "2025-04-01")["rows"][0][
        "revenue"
    ]
    delta = current - baseline
    check(
        "comparison arithmetic",
        f"{delta:+,.2f}" in comparison["text"]
        and f"{delta / baseline * 100:+.2f}%" in comparison["text"],
    )
    check(
        "comparison roles visible",
        "Evaluated: Q4 2024" in comparison["text"] and "Baseline: Q2 2025" in comparison["text"],
    )
    empty = evidence[6][0]["rows"][0]
    check(
        "empty raw aggregate",
        empty["revenue"] is None and empty["orders"] == 0 and empty["customers"] == 0,
    )
    check(
        "access denial has no evidence",
        not cases[8]["answer"]["evidence"]
        and "cannot provide data outside" in cases[8]["answer"]["text"],
    )
    check(
        "save and preview are real state changes",
        cases[9]["reports_after"] == ["Autumn review"] and cases[9]["pending_after"] == 1,
    )
    check(
        "cancel preserves saved report",
        cases[10]["reports_after"] == ["Autumn review"]
        and cases[10]["pending_before"] == 1
        and cases[10]["pending_after"] == 0
        and "Autumn review" in cases[10]["answer"]["text"],
    )
    oracle = json.loads((root / "oracle-results.json").read_text())
    actual = {(i, e["id"]): e["rows"] for i, items in evidence.items() for e in items}
    check(
        "independent oracle covers all eleven evidence sets",
        len(oracle) == 11
        and {(r["case"], r["evidence"]) for r in oracle} == set(actual)
        and len(actual) == 11,
    )
    for r in oracle:
        captured = actual[(r["case"], r["evidence"])]
        ok = same_rows(captured, r["oracle_rows"])
        if r["case"] == 3 and ok:
            ok = all(
                math.isclose(a["inactivity_share"], b["inactivity_share"], abs_tol=1e-10)
                for a, b in zip(captured, r["oracle_rows"], strict=True)
            )
        check(f"SQL {r['case']}/{r['evidence']}", r["pass"] and ok)
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        checks = evaluate(args.directory)
    except (KeyError, TypeError, ValueError, OSError, StopIteration):
        checks = [{"check": "complete readable captures and oracle are required", "pass": False}]
    if args.write:
        (args.directory / "acceptance.json").write_text(json.dumps(checks, indent=2))
    print(f"{sum(c['pass'] for c in checks)}/{len(checks)} checks passed")
    for c in checks:
        if not c["pass"]:
            print("FAIL", c["check"])
    raise SystemExit(not all(c["pass"] for c in checks))
