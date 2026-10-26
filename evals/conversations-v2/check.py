"""Re-evaluate immutable captured responses with the current acceptance assertions."""

import argparse
import json
from pathlib import Path

from run import check

from retail_agent.models import Answer
from retail_agent.planning import TurnPlan


def evaluate(root, selected=None):
    cases = {c["id"]: c for c in json.loads(Path(__file__).with_name("cases.json").read_text())}
    expected_ids = {f"{cid:02}-{turn}" for cid in (selected or cases) for turn in (1, 2)}
    results = []
    for path in sorted(root.glob("[0-9][0-9]-[12].json")):
        capture = json.loads(path.read_text())
        result = {"id": capture["id"]}
        if capture["id"] not in expected_ids:
            results.append(
                {"id": capture["id"], "passed": False, "error": "Unexpected captured turn"}
            )
            continue
        try:
            assert "answer" in capture, capture.get("error", "No response")
            answer = Answer.model_validate(capture["answer"])
            plan = TurnPlan.model_validate(capture["plan"])
            base = None
            if capture["turn"]:
                first = json.loads((root / f"{capture['case']:02}-1.json").read_text())
                if "answer" in first:
                    base = Answer.model_validate(first["answer"])
            check(
                cases[capture["case"]],
                capture["turn"],
                answer,
                plan,
                base,
                capture["before"],
                capture["after"],
            )
            result["passed"] = True
        except Exception as exc:
            result.update(passed=False, error=str(exc) or type(exc).__name__)
        results.append(result)
    seen = {r["id"] for r in results}
    results.extend(
        {"id": key, "passed": False, "error": "Missing captured turn"}
        for key in sorted(expected_ids - seen)
    )
    (root / "acceptance.json").write_text(json.dumps(results, indent=2))
    print(f"{sum(r['passed'] for r in results)}/{len(results)} captured responses passed")
    for r in results:
        if not r["passed"]:
            print(r)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--cases", type=int, nargs="+")
    args = parser.parse_args()
    outcomes = evaluate(args.results, args.cases)
    raise SystemExit(not all(item["passed"] for item in outcomes))
