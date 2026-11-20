"""Replay known candidate defects and a correct control through the real reviewer.

Run explicitly with:
    uv run --locked python scripts/calibrate_reviewer.py --live
    uv run --locked python scripts/calibrate_reviewer.py --live --suite ranking_grounding

This is regression calibration, not held-out evaluation. It performs no warehouse
queries, invokes no analyst, and never changes or saves reports. Four candidate
reviews share one USD 1 (or lower configured) admission budget, one deadline and
at most four provider calls including retries. A failed schema/retry can consume
that allowance; skipped cases are reported honestly. Approval does not prove truth.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import logging
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from retail_agent.budget import Budget, LimitReached
from retail_agent.config import Settings, repository_root
from retail_agent.provider import ProviderUnavailable, make_gemini
from retail_agent.reviewer import evaluate
from retail_agent.skills import SkillCatalog

ROOT = repository_root()
CASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "monthly_distinct_total",
        "capture": "monthly_table-1.json",
        "expected_decisions": ["revise", "stop"],
        "known_issue": (
            "The candidate adds monthly distinct customers (1+2+3) and labels 6 as "
            "an overall unique-customer total. The fixture has 5 distinct customers; "
            "monthly aggregate evidence does not establish a distinct union total."
        ),
    },
    {
        "id": "inactivity_eligibility_without_purchases",
        "capture": "false_premise-1.json",
        "expected_decisions": ["revise", "stop"],
        "known_issue": (
            "The requested month-end comparison is correct, but the added narrative "
            "claims that no purchases in May/June means no new customers became eligible. "
            "Eligibility changes with age: E1 rises from 1 eligible on May 1 to 5 on June 1. "
            "The prose also contains the malformed label 'cutoff February 0'."
        ),
    },
    {
        "id": "invented_currency",
        "capture": "monthly_table-1.json",
        "source_sibling": "fixture-regressions-02",
        "expected_decisions": ["revise", "stop"],
        "known_issue": (
            "The candidate displays dollar symbols while the evidence and the candidate's "
            "own note state that currency is unspecified. It must not invent currency units."
        ),
    },
    {
        "id": "correct_concise_aov_control",
        "capture": "prose_aov-1.json",
        "expected_decisions": ["approve"],
        "known_issue": None,
    },
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(source_dir: Path, suite: str = "core") -> list[dict[str, Any]]:
    """Reconstruct reviewer inputs without leaking expected labels into the prompt."""
    fixture_path = ROOT / "evals/rewrite/ranking_grounding_cases.json"
    fixture = json.loads(fixture_path.read_text()) if suite == "ranking_grounding" else None
    if suite not in ("core", "ranking_grounding"):
        raise ValueError(f"Unknown calibration suite: {suite}")
    cases = []
    for spec in fixture["cases"] if fixture else CASE_SPECS:
        case_directory = (
            source_dir.parent / spec["source_sibling"] if "source_sibling" in spec else source_dir
        )
        path = ROOT / fixture["source_capture"] if fixture else case_directory / spec["capture"]
        capture = json.loads(path.read_text())
        result = capture["result"]
        answer = result["answer"]
        candidate = spec["candidate_markdown"] if fixture else answer["markdown"]
        available = {artifact["id"]: artifact for artifact in result["evidence"]}
        evidence = [available[key] for key in answer["evidence_ids"]]
        payload = {
            "question": fixture["question"] if fixture else capture["prompt"],
            "scope": evidence[0]["scope"] if evidence else "Calvin Klein",
            "conversation": [
                {
                    "question": capture["prompt"],
                    "answer_id": answer["id"],
                    "markdown": answer["markdown"],
                    "evidence_ids": answer["evidence_ids"],
                }
            ]
            if fixture
            else [],
            "candidate": {"markdown": candidate, "outcome": answer["outcome"]},
            "evidence": evidence,
            "other_results_manifest": [
                {
                    "id": key,
                    "purpose": item.get("purpose", ""),
                    "columns": item.get("columns", []),
                    "stored_rows": len(item["rows"]),
                    "truncated": item.get("truncated", False),
                }
                for key, item in available.items()
            ],
            "retrieved_methods": [],
            "pending_save": None,
            "save_target": None,
        }
        cases.append(
            {
                **spec,
                "source_path": str(path),
                "source_sha256": sha256(path),
                "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
                **({"case_fixture_sha256": sha256(fixture_path)} if fixture else {}),
                "payload": payload,
            }
        )
    return cases


async def calibrate(
    source_dir: Path, output: Path, timeout: float, suite: str = "core"
) -> dict[str, Any]:
    cases = load_cases(source_dir, suite)
    settings = Settings.load()
    settings.backend = "fixture"
    settings.question_budget_usd = min(settings.question_budget_usd, 1.0)
    settings.turn_timeout_seconds = min(settings.turn_timeout_seconds, timeout)
    settings.max_model_calls = 4
    for name in ("google.adk", "google_genai", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    prompt_path = ROOT / "src/retail_agent/prompts/reviewer.md"
    document: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "evaluation_type": "known-regression reviewer calibration; not a held-out benchmark",
        "suite": suite,
        "data": (
            "Previously captured public TheLook ranking evidence, a user-reported defective "
            "follow-up and authored regression controls; no SQL is executed."
            if suite == "ranking_grounding"
            else "Previously captured synthetic fixture evidence; no SQL is executed."
        ),
        "model": settings.gemini_model,
        "review_thinking_level": settings.review_thinking_level,
        "reviewer_prompt_sha256": sha256(prompt_path),
        "reviewer_source_sha256": sha256(ROOT / "src/retail_agent/reviewer.py"),
        "review_skill": SkillCatalog().list(role="reviewer"),
        "packages": {
            package: importlib.metadata.version(package)
            for package in ("google-adk", "google-genai")
        },
        "limits": {
            "shared_deadline_seconds": settings.turn_timeout_seconds,
            "shared_budget_usd": settings.question_budget_usd,
            "maximum_provider_calls_including_retries": settings.max_model_calls,
            "maximum_candidate_reviews": len(cases),
        },
        "label_policy": (
            "Expected decisions and known defects are output-only annotations; "
            "they are never included in reviewer inputs."
        ),
        "cases": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="retail-review-calibration-") as temporary:
        settings.data_dir = Path(temporary)
        model = make_gemini(settings)
        budget = Budget(settings)
        for case in cases:
            started = time.monotonic()
            events: list[dict[str, Any]] = []

            def emit(
                event: str,
                *,
                _events: list[dict[str, Any]] = events,
                _started: float = started,
                **fields: Any,
            ) -> None:
                _events.append(
                    {
                        "event": event,
                        "elapsed_seconds": round(time.monotonic() - _started, 3),
                        **fields,
                    }
                )

            record = {key: value for key, value in case.items() if key != "payload"}
            record["events"] = events
            record["candidate_markdown"] = case["payload"]["candidate"]["markdown"]
            record["question"] = case["payload"]["question"]
            try:
                async with asyncio.timeout(budget.remaining()):
                    review = await evaluate(case["payload"], model, budget, settings, emit)
                record["status"] = "reviewed"
                record["review"] = review.model_dump()
                record["expected_decision_matched"] = review.decision in case["expected_decisions"]
            except (LimitReached, TimeoutError, ProviderUnavailable) as exc:
                record["status"] = "not_completed"
                record["error_type"] = type(exc).__name__
                record["limit_code"] = exc.code if isinstance(exc, LimitReached) else None
                record["expected_decision_matched"] = False
            except Exception as exc:
                record["status"] = "not_completed"
                record["error_type"] = type(exc).__name__
                record["expected_decision_matched"] = False
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            document["cases"].append(record)
            document["shared_usage"] = budget.snapshot()
            output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
            decision = record.get("review", {}).get("decision", record["status"])
            print(
                f"{case['id']}: {decision}; expected decision matched={record['expected_decision_matched']}"
            )
    document["finished_at"] = datetime.now(UTC).isoformat()
    document["limits_of_evidence"] = (
        "Four selected calibration cases cannot estimate reliability. Inspect the issues: "
        "rejecting a flawed candidate for an unrelated stylistic reason does not establish "
        "that the reviewer detected its known analytical defect. No claim is made that "
        "a stop decision is the most helpful recovery for a fixable answer."
    )
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Explicitly allow the real reviewer API calls."
    )
    parser.add_argument(
        "--suite",
        choices=("core", "ranking_grounding"),
        default="core",
        help="Replay the original calibration cases or ranking-interpretation regressions.",
    )
    parser.add_argument(
        "--source-dir", type=Path, default=ROOT / "evals/rewrite/runs/fixture-smoke-01"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evals/rewrite/runs/reviewer-calibration-01.json"
    )
    parser.add_argument(
        "--timeout", type=float, default=90, help="Shared deadline in seconds (1-120)."
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Use --live to explicitly allow real reviewer calls. No model was invoked.")
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between 1 and 120 seconds.")
    document = asyncio.run(calibrate(args.source_dir, args.output, args.timeout, args.suite))
    print(f"Recorded calibration observations: {args.output}")
    if not all(case["expected_decision_matched"] for case in document["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
