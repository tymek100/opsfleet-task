"""Offline acceptance checks; no credentials and no model-as-judge."""

import argparse
import json
from pathlib import Path

from oracle import same_rows


def evaluate(root):
    cases = [json.loads(p.read_text()) for p in sorted(root.glob("[0-9][0-9]-*.json"))]
    checks = []

    def check(name, passed):
        checks.append({"check": name, "pass_": bool(passed)})

    for c in cases:
        a = c.get("answer", {})
        text = a.get("text", "")
        i = c["id"]
        ev = a.get("evidence", [])
        check(f"{i}: response", bool(a) and not c.get("error"))
        if i <= 4:
            check(
                f"{i}: analytical evidence required",
                bool(ev) and a.get("quality_status") == "validated",
            )
        if i <= 4 and ev and a.get("intent"):
            check(f"{i}: validated complete analysis", a.get("quality_status") == "validated")
            intent = a.get("intent", {})
            expected = [
                ("2025-04-01", "2025-07-01"),
                ("2026-04-01", "2026-01-01"),
                ("2026-01-01", "1900-01-01"),
                ("2025-04-01", "2024-04-01"),
            ][i - 1]
            check(
                f"{i}: period and denominator",
                intent.get("period", {}).get("start") == expected[0]
                and intent.get("comparison", {}).get("start") == expected[1],
            )
            ends = [
                ("2025-07-01", "2025-10-01"),
                ("2026-05-01", "2026-02-01"),
                ("2026-02-01", "1900-02-01"),
                ("2025-07-01", "2024-07-01"),
            ][i - 1]
            check(
                f"{i}: exclusive period ends",
                intent.get("period", {}).get("end") == ends[0]
                and intent.get("comparison", {}).get("end") == ends[1],
            )
            current = next(
                e
                for e in ev
                if e["request"]["dimension"] == "total" and e["request"]["start"] == expected[0]
            )["rows"][0]
            baseline = next(
                e
                for e in ev
                if e["request"]["dimension"] == "total" and e["request"]["start"] == expected[1]
            )["rows"][0]
            base = baseline["revenue"] if baseline["units"] else 0
            value = current["revenue"] if current["units"] else 0
            delta = value - base
            check(f"{i}: absolute difference", f"{delta:+,.2f}" in text)
            if base:
                check(f"{i}: percentage", f"{delta / base * 100:+.2f}%" in text)
            else:
                check(f"{i}: zero baseline", "0.00" in text and "percentage undefined" in text)
        if i == 4 and ev:
            check(
                "4: report outputs",
                len(ev) == 4
                and len(
                    next((e for e in ev if e["request"]["dimension"] == "product"), {"rows": []})[
                        "rows"
                    ]
                )
                == 2
                and "Proposed actions" in text
                and "01 Jul 2025 to 30 Sep 2025" in text,
            )
        if i == 5:
            check(
                "5: cancelled real pending",
                c["pending_before"] == 1 and c["pending_after"] == 0 and "cancelled" in text,
            )
        if i == 6:
            check(
                "6: no active preview after compound operation",
                c["pending_after"] == 0
                and not c.get("preview")
                and "cancelled" in text
                and "Deletion preview prepared" in text,
            )
        if i in (5, 6):
            check(
                f"{i}: retained and listed",
                len(c["reports_after"]) == 1 and c["reports_after"][0] in text,
            )
        if i == 7:
            check(
                "7: save semantics and privacy",
                "last successful analysis" in text and "Only you" in text and not ev,
            )
        if i == 8:
            check("8: deletion help", "/cancel" in text and "/confirm" in text and not ev)
        if i == 9:
            check(
                "9: specific unsupported percentile",
                "percentile" in text.lower() and "profit" not in text.lower() and not ev,
            )
        if i == 10:
            check("10: all 51 months rejected honestly", "50" in text and "51" in text and not ev)
        check(
            f"{i}: no saved report changes",
            [r["id"] for r in c["reports_before"]] == c["reports_after"],
        )
    check("all ten cases captured", len(cases) == 10)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        checks = evaluate(args.directory)
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        checks = [
            {
                "check": "Malformed or incomplete captured evidence: " + type(exc).__name__,
                "pass_": False,
            }
        ]
    path = args.directory / "oracle-results.json"
    if path.exists():
        rows = json.loads(path.read_text())
        captured = {}
        for file in args.directory.glob("[0-9][0-9]-*.json"):
            case = json.loads(file.read_text())
            for e in case.get("answer", {}).get("evidence", []):
                captured[(case["id"], e["id"])] = e["rows"]
        keys = [(r["case"], r["evidence"]) for r in rows]
        checks.append(
            {
                "check": "ten independent SQL evidence checks",
                "pass_": len(rows) == 10
                and len(set(keys)) == 10
                and set(keys) == set(captured)
                and all(
                    r["pass"]
                    and same_rows(captured.get((r["case"], r["evidence"]), []), r["oracle_rows"])
                    for r in rows
                ),
            }
        )
    else:
        checks.append({"check": "independent SQL evidence is present", "pass_": False})
    if args.write:
        (args.directory / "acceptance.json").write_text(json.dumps(checks, indent=2) + "\n")
    failed = [c["check"] for c in checks if not c["pass_"]]
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    for name in failed:
        print("FAIL:", name)
    raise SystemExit(bool(failed))


if __name__ == "__main__":
    main()
