"""Isolated paired judge controls; never imported by the baseline runner."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from evaluation.graders.judge import PROMPT_PATH, GeminiJudge
from evaluation.models import TurnReference
from evaluation.settings import EvaluationSettings
from retail_agent.config import Settings

from .grading import grade
from .semantic_contracts import independent_totals, semantic_criteria

DEFAULT_BASELINE = Path(".artifacts/multi-agent/a2a-20261124T191812Z-f59d6715")

# Each repair changes observed incorrect clauses; neither variant's expected label reaches the judge.
CONTROLS = (
    {
        "id": "unknown-cost-direction",
        "role": "inventory",
        "scenario": "scenario-05",
        "turn": 2,
        "repairs": [
            (
                "Treating missing costs as zero would arbitrarily understate the total inventory cost basis:",
                "Treating missing costs as zero assumes an unverified value and could understate the total inventory cost basis; the direction is not established by missing values alone:",
            )
        ],
    },
    {
        "id": "snapshot-not-complete-history",
        "role": "inventory",
        "scenario": "scenario-09",
        "turn": 2,
        "repairs": [
            ("**No Inventory History**", "**No Rows in the Available Snapshot**"),
            (
                "has 0 total inventory records in the database (`E3`). It is not an item that was stocked and subsequently depleted; rather, no inventory units have ever been recorded for it.",
                "has 0 inventory records in the available snapshot (`E3`). This does not establish whether it was ever stocked or depleted, because complete historical coverage is not guaranteed.",
            ),
        ],
    },
    {
        "id": "global-total-and-stock-rule",
        "role": "distribution",
        "scenario": "scenario-02",
        "turn": 1,
        "repairs": [
            ("brand total of 26 unsold units", "brand total of 32 modeled unsold units"),
            (
                "inventory created on or before the cutoff without qualifying sales before that cutoff",
                "inventory created on or before the cutoff with sold_at either null or strictly after the cutoff",
            ),
        ],
    },
    {
        "id": "stocked-products-not-catalog",
        "role": "distribution",
        "scenario": "scenario-04",
        "turn": 2,
        "repairs": [
            (
                "individual products are simultaneously stocked in multiple distribution centers",
                "individual product IDs appear in modeled stock at multiple recorded centers",
            ),
            ("only **6 unique products** in total", "**6 distinct stocked products**"),
            ("all 6 catalog products", "all 6 stocked products"),
            (
                "physical inventory units (`inventory_id`) represent unique physical items",
                "distinct inventory records (`inventory_id`) represent unique modeled units",
            ),
        ],
    },
    {
        "id": "recorded-ids-not-facilities",
        "role": "distribution",
        "scenario": "scenario-14",
        "turn": 1,
        "repairs": [
            (
                "and 5 distribution centers",
                "and four recognized distribution centers plus an Unknown attribution group",
            )
        ],
    },
    {
        "id": "modeled-not-actual-holdings",
        "role": "inventory",
        "scenario": "scenario-07",
        "turn": 2,
        "repairs": [
            (
                "understate the inventory actually held at the cutoff date",
                "understate modeled unsold inventory at the cutoff date",
            ),
        ],
    },
    {
        "id": "aging-not-turnover-or-cause",
        "role": "distribution",
        "scenario": "scenario-10",
        "turn": 2,
        "repairs": [
            (
                "**Stock age (inventory dwell time)** measures the duration unsold inventory sits in a distribution center from receipt/creation (`created_at`) until an evaluation cutoff or sale. High stock age reflects slow inventory turnover, overstocking, or obsolescence—not fulfillment performance.",
                "**Modeled stock age** measures elapsed time from recorded creation (`created_at`) to the chosen cutoff. High age alone measures neither inventory turnover nor fulfillment performance and does not establish overstocking or obsolescence; those remain hypotheses requiring separate evidence.",
            ),
            (
                "conflates items that have never been ordered with overdue customer orders",
                "conflates modeled unsold inventory with overdue customer orders",
            ),
        ],
    },
    {
        "id": "stock-rule-with-correct-totals",
        "role": "distribution",
        "scenario": "scenario-02",
        "turn": 2,
        "repairs": [
            (
                "inventory created on or before the cutoff without qualifying sales before that cutoff",
                "inventory created on or before the cutoff with sold_at either null or strictly after the cutoff",
            ),
        ],
    },
)


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_reference(frozen, totals):
    result = TurnReference.model_validate(copy.deepcopy(frozen))
    result.criteria.extend(semantic_criteria(totals))
    return result


def build_controls(baseline):
    scenarios = read(baseline / "scenarios.json")
    references = read(baseline / "references.json")
    snapshot = read(baseline / "snapshot.json")
    result = []
    for specification in CONTROLS:
        role, case_id, number = (
            specification["role"],
            specification["scenario"],
            specification["turn"],
        )
        case = next(c for c in scenarios[role] if c["id"] == case_id)
        source = baseline / role / case_id / f"turn-{number}.json"
        bad = read(source)
        fixed = copy.deepcopy(bad)
        for before, after in specification["repairs"]:
            if fixed["markdown"].count(before) != 1:
                raise ValueError(f"Repair no longer matches exactly once: {specification['id']}")
            fixed["markdown"] = fixed["markdown"].replace(before, after, 1)
        prior = []
        if number == 2:
            previous = read(baseline / role / case_id / "turn-1.json")
            prior = [{"question": case["question"], "answer": previous.get("markdown")}]
        totals = independent_totals(snapshot, case["identity"], bad["as_of"])
        ref = candidate_reference(references[role][case_id][f"turn-{number}"], totals)
        result.append(
            {
                "id": specification["id"],
                "role": role,
                "scenario": case_id,
                "turn": number,
                "question": case["question"] if number == 1 else case["follow_up"],
                "source": str(source),
                "source_sha256": digest(source),
                "reference": ref,
                "prior": prior,
                "variants": {"observed_bad": bad, "minimal_repair": fixed},
            }
        )
    return result


async def run(baseline, *, max_cost_usd=2.0, deadline_seconds=600, prepare_only=False, only=None):
    if not all(math.isfinite(v) and v > 0 for v in (max_cost_usd, deadline_seconds)):
        raise ValueError("Positive finite cost and deadline limits are required")
    controls = build_controls(baseline)
    if only:
        selected = set(only.split(","))
        if selected - {c["id"] for c in controls}:
            raise ValueError("Unknown candidate control ID")
        controls = [c for c in controls if c["id"] in selected]
    started = time.monotonic()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (
        Path(".artifacts/multi-agent") / f"calibration-candidate-{stamp}-{uuid.uuid4().hex[:8]}"
    )
    settings = Settings.load()
    config = EvaluationSettings(
        judge_model=settings.gemini_model,
        input_usd_per_million=settings.input_usd_per_million,
        output_usd_per_million=settings.output_usd_per_million,
    )
    grading_sources = [
        path
        for name in ("grading.py", "partitions.py", "reference_context.py")
        if (path := Path(__file__).with_name(name)).exists()
    ]
    manifest = {
        "kind": "paired-judge-candidate-development-controls",
        "baseline": str(baseline),
        "baseline_files": {
            name: digest(baseline / name)
            for name in ("snapshot.json", "references.json", "scenarios.json")
        },
        "candidate_module_sha256": digest(Path(__file__)),
        "semantic_contracts_sha256": digest(Path(__file__).with_name("semantic_contracts.py")),
        "answer_grading_module_sha256": digest(Path(__file__).with_name("grading.py")),
        "answer_grading_sources_sha256": {path.name: digest(path) for path in grading_sources},
        "unchanged_judge_prompt_sha256": digest(PROMPT_PATH),
        "model": config.judge_model,
        "control_pairs": len(controls),
        "max_cost_usd": max_cost_usd,
        "deadline_seconds": deadline_seconds,
        "human_reviewed": False,
        "sealed_holdout": False,
        "phoenix_publication": False,
        "status": "prepared" if prepare_only else "running",
        "qualification": "Observed development failures with assistant-authored minimal repairs. Passing these controls alone does not establish general judge calibration.",
    }
    write(output / "manifest.json", manifest)
    (output / "calibration_candidate.py").write_text(Path(__file__).read_text())
    (output / "semantic_contracts.py").write_text(
        Path(__file__).with_name("semantic_contracts.py").read_text()
    )
    for path in grading_sources:
        (output / path.name).write_text(path.read_text())
    for control in controls:
        folder = output / control["id"]
        write(folder / "reference.json", control["reference"].model_dump(mode="json"))
        write(
            folder / "source.json",
            {k: v for k, v in control.items() if k not in {"reference", "variants"}},
        )
        for name, raw in control["variants"].items():
            write(folder / f"{name}.json", raw)
    print(f"Candidate controls: {output}", flush=True)
    if prepare_only:
        return output, 0
    key = settings.gemini_api_key.get_secret_value()
    if not key:
        raise ValueError("GEMINI_API_KEY is required to run actual judge controls")
    results, spent = [], 0.0
    for index, control in enumerate(controls):
        # Alternate pair ordering to avoid always putting the negative example first.
        names = ["observed_bad", "minimal_repair"]
        if index % 2:
            names.reverse()
        for name in names:
            expected = "FAIL" if name == "observed_bad" else "PASS"
            remaining = deadline_seconds - (time.monotonic() - started)
            judge = None
            record = {"control_id": control["id"], "variant": name, "expected": expected}
            try:
                if remaining <= 0 or spent >= max_cost_usd:
                    raise ValueError("Candidate run budget exhausted; no judgment assumed")
                judge = GeminiJudge(
                    key, config, max_cost_usd=max_cost_usd - spent, deadline_seconds=remaining
                )
                result = await grade(
                    control["variants"][name],
                    control["question"],
                    control["turn"],
                    control["reference"],
                    judge,
                    control["prior"],
                )
                record.update(observed=result["status"], matches=result["status"] == expected)
                write(output / control["id"] / f"{name}-grade.json", result)
            except ValueError as exc:
                record.update(observed="ERROR", matches=False, error=str(exc))
            finally:
                if judge is not None:
                    spent += judge.accounted_usd
                    write(output / control["id"] / f"{name}-judge.json", judge.calls)
                    await judge.close()
            results.append(record)
            write(output / "results.json", results)
            print(f"{control['id']}/{name}: {record['observed']} (expected {expected})", flush=True)
    summary = {
        "results": results,
        "matched_controls": sum(r["matches"] for r in results),
        "total_controls": len(results),
        "bad_answers_rejected": sum(
            r["expected"] == "FAIL" and r["observed"] == "FAIL" for r in results
        ),
        "repaired_answers_accepted": sum(
            r["expected"] == "PASS" and r["observed"] == "PASS" for r in results
        ),
        "errors": sum(r["observed"] in {"ERROR", "UNJUDGEABLE"} for r in results),
        "accounted_usd": spent,
        "elapsed_seconds": time.monotonic() - started,
        "qualification": manifest["qualification"],
        "not_directly_controlled": [
            "cutoff-vs-visibility",
            "null-sale-vs-shipment",
        ],
    }
    write(output / "summary.json", summary)
    manifest.update(status="completed", accounted_usd=spent)
    write(output / "manifest.json", manifest)
    return output, 0 if all(r["matches"] for r in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--max-cost-usd", type=float, default=2)
    parser.add_argument("--deadline-seconds", type=float, default=600)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--only", help="Comma-separated control IDs for an explicit focused rerun")
    arguments = parser.parse_args()
    _, code = asyncio.run(run(**vars(arguments)))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
