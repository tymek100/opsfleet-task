"""Opt-in real-model smoke observations with isolated report storage.

This records complete answers and evidence for human review. Runtime approval is
recorded as an observation; it is never converted into a quality pass rate.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import importlib.metadata
import json
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from retail_agent.config import Settings
from retail_agent.contracts import DEMO_USERS
from retail_agent.runtime import Analyst
from retail_agent.skills import SkillCatalog

FIXTURE_SHA256 = "b9d69b87067b2fa0ea3332ad6775a52b435537f58af001c69f1ae4043425aa55"
CASES = {
    "rankings": [
        "Show our top five products by revenue and, separately, by distinct customers in Q1 2026."
    ],
    "compact_rankings": [
        "Show our top five products by revenue and, separately, by distinct customers in Q1 2026. "
        "Use two compact tables."
    ],
    "rankings_with_details": [
        "Show our top five products by revenue and, separately, by distinct customers in Q1 2026. "
        "Include product IDs in both tables and explain the sales exclusions and tie-breaking."
    ],
    "ranking_followup": [
        "Show our top five products by revenue and, separately, by distinct customers in Q1 2026. "
        "Use two compact tables.",
        "Which products appear in both rankings? Explain what this suggests about revenue "
        "versus customer reach in one short paragraph, without a table.",
    ],
    "quarterly_category_followup": [
        "Compare our Q1 2026 performance with Q4 2025. Show qualifying revenue, distinct "
        "customers, distinct orders, and average order value, including percentage changes.",
        "Identify the three product categories contributing most to the revenue change. "
        "Show the remaining categories as “Other” so contributions reconcile to the total change.",
    ],
    "skill_reference": [
        "Use the revenue-driver-analysis skill and its measurement guide to explain how you "
        "would distinguish selling-price and quantity effects in revenue changes. "
        "Answer in one short paragraph without querying or claiming current business figures."
    ],
    "prose_aov": [
        "What was our average order value in Q1 2026? Answer in one short paragraph without a table."
    ],
    "monthly_table": [
        "Show January, February and March 2026 revenue in a table, followed by one brief observation."
    ],
    "novel_metric": [
        "Which category earned the most revenue per active selling day in Q1 2026? "
        "Count only UTC dates with a qualifying sale for each category and show how you calculated the winner."
    ],
    "false_premise": ["Why did our 90-day inactivity rate spike from May to June 2026?"],
    "empty_denominator": [
        "What fraction of customers first acquired in April 2026 bought again in May?"
    ],
    "golden_method": [
        "Consult a relevant Golden example, then calculate our Q1 2026 repeat-customer share "
        "from current authorized data. Explain the result briefly."
    ],
    "report_save": [
        "Write a short Q1 2026 performance report and suggest two measurable actions for Q2. Do not save it yet.",
        "Save that exact report as Q1 2026 Review.",
    ],
}

# Independently enumerated from the frozen synthetic rows, not computed by agent SQL.
EXPECTED = {
    "rankings": {
        "revenue_ranking": [["Alpha top", 200.0], ["Alpha jeans", 175.0]],
        "distinct_customer_ranking": [["Alpha top", 4], ["Alpha jeans", 1]],
        "sold_products": 2,
        "interpretation": "Only two products qualify; a correct top five must disclose the short list.",
    },
    "ranking_followup": {
        "revenue_ranking": [["Alpha top", 200.0], ["Alpha jeans", 175.0]],
        "distinct_customer_ranking": [["Alpha top", 4], ["Alpha jeans", 1]],
        "overlap": ["Alpha top", "Alpha jeans"],
        "interpretation": (
            "Both sold products appear in both lists. Rankings alone do not establish "
            "unit prices, unit volumes, motives or brand-wide revenue concentration."
        ),
    },
    "quarterly_category_followup": {
        "Q4_2025": {"revenue": 0.0, "customers": 0, "orders": 0, "average_order_value": None},
        "Q1_2026": {"revenue": 375.0, "customers": 5, "orders": 6, "average_order_value": 62.5},
        "category_revenue_changes": {"Tops": 200.0, "Jeans": 175.0},
        "total_revenue_change": 375.0,
        "interpretation": (
            "The fixture has no qualifying Q4 purchases, so percentage changes from zero and "
            "the Q4 AOV are undefined. Only two categories have qualifying sales; do not "
            "invent a third contributing category. Category contributions sum to 375."
        ),
    },
    "skill_reference": {
        "interpretation": (
            "A method-only answer should distinguish realized unit selling prices from revenue "
            "per customer and quantity from distinct customers; it should not invent business facts."
        ),
    },
    "prose_aov": {"revenue": 375.0, "orders": 6, "average_order_value": 62.5},
    "monthly_table": {"January": 125.0, "February": 100.0, "March": 150.0},
    "novel_metric": {
        "winner": "Tops",
        "revenue": 200.0,
        "active_days": 2,
        "revenue_per_active_day": 100.0,
        "runner_up": {"category": "Jeans", "revenue": 175.0, "active_days": 2, "rate": 87.5},
    },
    "false_premise": {
        "May_end": {"eligible": 5, "inactive": 5, "percent": 100.0},
        "June_end": {"eligible": 5, "inactive": 5, "percent": 100.0},
        "percentage_point_change": 0,
        "interpretation": "Under the documented eligible-before-90-day-cutoff definition, no spike exists.",
    },
    "empty_denominator": {
        "April_acquisitions": 0,
        "next_month_repeat_rate": None,
        "interpretation": "No eligible cohort; the rate is undefined, not zero percent.",
    },
    "golden_method": {"customers": 5, "repeat_customers": 1, "repeat_percent": 20.0},
    "report_save": {"revenue": 375.0, "orders": 6, "items": 7, "customers": 5},
}
EXPECTED["compact_rankings"] = EXPECTED["rankings"]
EXPECTED["rankings_with_details"] = EXPECTED["rankings"]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def _has_markdown_table(markdown: str) -> bool:
    return bool(re.search(r"(?m)^\s*\|?\s*:?-{3,}:?\s*\|(?:\s*:?-{3,}:?\s*\|?)+\s*$", markdown))


def _numbers(text: str) -> set[float]:
    # Presence checks intentionally do not claim to validate numerical meaning.
    normalized = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    return {
        float(value) for value in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?!\w|\.\d)", normalized)
    }


def _check(name: str, result: bool | None, description: str) -> dict:
    return {
        "name": name,
        "observation": "matched"
        if result is True
        else "not_matched"
        if result is False
        else "not_checked",
        "description": description,
    }


def observations(
    case: str,
    turn_index: int,
    payload: dict,
    fixture_oracle: bool,
    library_before: list,
    library_after: list,
    stored: list,
    first_answer: dict | None,
) -> list[dict]:
    answer = payload.get("answer") or {}
    markdown = answer.get("markdown", "")
    tools = [
        event.get("tool")
        for event in payload.get("trace", [])
        if event.get("event") == "tool_start"
    ]
    checks = [
        _check(
            "reviewed_answer_present",
            bool(answer.get("approved")),
            "Runtime approval observed; this alone does not establish correctness or readability.",
        ),
    ]
    if case == "prose_aov" or (case == "ranking_followup" and turn_index > 0):
        checks.append(
            _check(
                "no_markdown_table",
                bool(markdown) and not _has_markdown_table(markdown),
                "Checks the explicit no-table request only; paragraph quality needs review.",
            )
        )
    if case == "monthly_table":
        checks.append(
            _check(
                "markdown_table_present",
                _has_markdown_table(markdown),
                "A Markdown table is present; its content still needs numerical review.",
            )
        )
    if case == "golden_method":
        checks.append(
            _check(
                "retrieval_and_fresh_query_observed",
                all(name in tools for name in ("list_golden", "read_golden", "query_data")),
                "This prompt explicitly requests a Golden method. Tool presence does not prove that its adaptation is correct.",
            )
        )
    if case == "skill_reference":
        checks.append(
            _check(
                "skill_and_reference_read_without_query",
                all(name in tools for name in ("load_skill", "load_skill_resource"))
                and payload.get("usage", {}).get("queries") == 0,
                "The explicitly requested skill/reference were read without a warehouse query; interpretation still needs manual review.",
            )
        )
    if case == "report_save":
        if turn_index == 0:
            checks.append(
                _check(
                    "no_implicit_save",
                    len(library_after) == len(library_before) == 0,
                    "Actual isolated report-store state remained empty after report generation.",
                )
            )
        else:
            checks.append(
                _check(
                    "one_report_saved",
                    len(library_after) == 1,
                    "Actual isolated owner library contains exactly one saved report.",
                )
            )
            checks.append(
                _check(
                    "exact_original_markdown_saved",
                    bool(first_answer)
                    and len(stored) == 1
                    and stored[0].get("markdown") == first_answer.get("markdown"),
                    "Stored Markdown is compared with the first turn's exact approved answer, not the save acknowledgement.",
                )
            )
            checks.append(
                _check(
                    "original_evidence_ids_saved",
                    bool(first_answer)
                    and len(stored) == 1
                    and {item.get("id") for item in stored[0].get("evidence", [])}
                    == set(first_answer.get("evidence_ids", [])),
                    "Stored evidence IDs are compared with the original approved answer's references.",
                )
            )
    elif library_after:
        checks.append(
            _check(
                "no_unrequested_report_mutation",
                False,
                "A report appeared without an explicit save request.",
            )
        )
    if fixture_oracle and turn_index == 0:
        numbers = _numbers(markdown)
        required_numbers = {
            "rankings": {200.0, 175.0},
            "prose_aov": {62.5},
            "monthly_table": {125.0, 100.0, 150.0},
            "novel_metric": {100.0},
            "false_premise": {100.0},
            "golden_method": {20.0},
            "report_save": {375.0},
        }.get(case)
        if required_numbers is not None:
            checks.append(
                _check(
                    "fixture_number_presence_smoke",
                    required_numbers <= numbers,
                    f"Expected numeric tokens {sorted(required_numbers)} occur in the answer. This is a weak smoke check, not a semantic numerical grade; inspect the independently enumerated facts and evidence.",
                )
            )
        if case == "empty_denominator":
            checks.append(
                _check(
                    "undefined_rate_language",
                    bool(
                        re.search(
                            r"undefined|not defined|cannot (?:be )?calculat|no (?:eligible |qualifying )?(?:customers|cohort)|no April",
                            markdown,
                            re.I,
                        )
                    ),
                    "Looks for undefined/empty-cohort language; manual review must reject an unsupported zero-percent rate.",
                )
            )
    return checks


def _safe_settings(settings: Settings) -> dict:
    names = [
        "gemini_model",
        "thinking_level",
        "review_thinking_level",
        "backend",
        "golden_bootstrap",
        "turn_timeout_seconds",
        "question_budget_usd",
        "max_model_calls",
        "max_tool_calls",
        "max_queries",
        "max_query_bytes",
        "max_output_tokens",
        "review_output_tokens",
        "max_answer_reviews",
        "max_context_bytes",
        "max_review_bytes",
        "review_overhead_bytes",
        "review_reserve_seconds",
        "input_usd_per_million",
        "output_usd_per_million",
        "bigquery_usd_per_tib",
        "model_min_interval_seconds",
    ]
    return {name: getattr(settings, name) for name in names}


def write_markdown(output: Path, run: dict) -> None:
    meta = run["metadata"]
    lines = [
        "# Replacement-agent prompt observations",
        "",
        f"Started: {meta['started_at']}. Data backend: **{meta['backend']}**. "
        f"Model: **{meta['settings']['gemini_model']}**. Identity: **{meta['user']}** ({meta['scope']}).",
        "",
        "These are real model smoke trials. Runtime approval and numeric-token presence are observations, "
        "not a quality score. The full answers and evidence need the manual review recorded below. "
        "This is not a held-out benchmark or a production reliability estimate.",
        "",
        f"Golden bootstrap enabled: `{meta['settings']['golden_bootstrap']}`. "
        "Enabled bootstrap examples are synthetic, unapproved demonstration methods. "
        "Report storage is temporary and isolated from the user's library.",
        "",
        "## Run configuration",
        "",
        "```json",
        json.dumps(meta, indent=2),
        "```",
        "",
        "## Observed turns",
        "",
        "Model USD uses reported token usage at configured rates. Held USD covers outstanding or unknown model attempts and conservative query reservations. Both are per prompt, not per conversation.",
        "",
        "| Case / turn | Runtime status | Seconds | Model calls | Queries | Model USD | Held USD | Reviews |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for case in run["cases"]:
        for turn in case["turns"]:
            payload = turn["result"]
            usage = payload.get("usage", {})
            reviews = (
                ", ".join(
                    event.get("decision", "?")
                    for event in payload.get("trace", [])
                    if event.get("event") == "review_end"
                )
                or "none"
            )
            lines.append(
                f"| {case['id']} / {turn['index'] + 1} | {payload['status']} | "
                f"{payload.get('elapsed_seconds', 0):.3f} | {usage.get('model_calls', 0)} | "
                f"{usage.get('queries', 0)} | {usage.get('spent_usd', 0):.6f} | "
                f"{usage.get('reserved_usd', 0):.6f} | {reviews} |"
            )
    for case in run["cases"]:
        lines.extend(["", f"## {case['id']}", ""])
        if case.get("independent_expected_facts"):
            lines.extend(
                [
                    "Independent expected facts for the frozen Calvin Klein fixture:",
                    "",
                    "```json",
                    json.dumps(case["independent_expected_facts"], indent=2),
                    "```",
                    "",
                ]
            )
        for turn in case["turns"]:
            payload = turn["result"]
            tools = [
                event.get("tool")
                for event in payload.get("trace", [])
                if event.get("event") == "tool_start"
            ]
            lines.extend(
                [
                    f"### Turn {turn['index'] + 1}",
                    "",
                    "**Prompt**",
                    "",
                    turn["prompt"],
                    "",
                    f"Observed tool calls: {' → '.join(tools) or 'none'}.",
                    "",
                    f"Runtime status: `{payload['status']}`. Elapsed: {payload.get('elapsed_seconds', 0):.3f} seconds.",
                    "",
                    "**Full published answer**",
                    "",
                ]
            )
            answer = payload.get("answer")
            if answer:
                lines.extend([answer["markdown"], ""])
                if answer.get("receipts"):
                    lines.extend(
                        [
                            "Application operation receipts:",
                            "",
                            "```json",
                            json.dumps(answer["receipts"], indent=2),
                            "```",
                            "",
                        ]
                    )
            else:
                lines.extend([payload.get("message") or "No approved answer was published.", ""])
            lines.extend(["**Narrow automated observations**", ""])
            for check in turn["observations"]:
                lines.append(
                    f"- `{check['name']}`: **{check['observation']}**. {check['description']}"
                )
            lines.extend(
                [
                    "",
                    f"Raw result, SQL/evidence, review events and report snapshots: [{turn['file']}]({turn['file']}).",
                    "",
                ]
            )
        lines.extend(
            [
                "**Manual assessment**",
                "",
                case.get(
                    "manual_assessment",
                    "Pending: inspect correctness, completeness, presentation, evaluator behavior and tool adaptation. "
                    "Record failures and changes before calling this case successful.",
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Limits of this run",
            "",
            "- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.",
            "- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.",
            "- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.",
            "- USD accounting separates reported model usage priced at configured rates from outstanding conservative reservations; neither is a verified provider invoice. Query reservations remain conservative.",
            "- Each unrelated case starts a new analyst conversation; turns within a case share its context. No real user reports are read or modified.",
            "",
        ]
    )
    (output / "observations.md").write_text("\n".join(lines))


async def run_cases(args: argparse.Namespace) -> int:
    settings = Settings.load()
    overrides: dict[str, Any] = {"backend": args.backend, "golden_bootstrap": args.golden_bootstrap}
    if args.model:
        overrides["gemini_model"] = args.model
    if args.timeout is not None:
        overrides["turn_timeout_seconds"] = args.timeout
    if args.max_model_calls is not None:
        overrides["max_model_calls"] = args.max_model_calls
    settings = Settings(**{**settings.model_dump(), **overrides})
    if not settings.gemini_api_key.get_secret_value():
        raise ValueError("GEMINI_API_KEY is required for these real-model trials.")
    identity = DEMO_USERS[args.user]
    labels = args.case or list(CASES)
    if "golden_method" in labels and not args.golden_bootstrap:
        raise ValueError("The golden_method smoke case requires explicit --golden-bootstrap.")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "Output directory must be new or empty; existing observations will not be overwritten."
        )
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    fixture_digest = (
        hashlib.sha256(settings.fixture_path.read_bytes()).hexdigest()
        if args.backend == "fixture"
        else None
    )
    oracle_active = (
        args.backend == "fixture" and args.user == "alice" and fixture_digest == FIXTURE_SHA256
    )
    metadata = {
        "started_at": datetime.now(UTC).isoformat(),
        "backend": args.backend,
        "user": args.user,
        "scope": identity.scope,
        "settings": _safe_settings(settings),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("google-adk", "google-genai", "sqlglot", "duckdb")
        },
        "fixture_sha256": fixture_digest,
        "independent_fixture_oracle_active": oracle_active,
        "golden_corpus_sha256": hashlib.sha256(settings.golden_path.read_bytes()).hexdigest(),
        "evaluation_type": "real-model smoke observations; manual quality review pending",
        "selected_cases": labels,
        "runtime_skills": {
            role: SkillCatalog().list(role=role) for role in ("analyst", "reviewer")
        },
        "maximum_turns": sum(len(CASES[label]) for label in labels),
        "storage": "TemporaryDirectory per run; no user library reads/imports/mutations",
    }
    run: dict[str, Any] = {"metadata": metadata, "cases": []}
    _write_json(output / "run.json", run)
    runtime_failures = 0
    with tempfile.TemporaryDirectory(prefix="retail-rewrite-eval-") as temp:
        for label in labels:
            case_settings = settings.model_copy(update={"data_dir": Path(temp) / label})

            def progress(event: dict, case_label: str = label) -> None:
                if event["event"] in {
                    "tool_start",
                    "review_start",
                    "review_end",
                    "failure",
                    "limit_reached",
                }:
                    detail = event.get("tool") or event.get("decision") or event.get("code") or ""
                    print(
                        f"[{case_label} +{event.get('elapsed', 0):.1f}s] {event['event']} {detail}",
                        flush=True,
                    )

            analyst = Analyst(case_settings, identity, progress=progress)
            case_record = {
                "id": label,
                "turns": [],
                "independent_expected_facts": EXPECTED[label] if oracle_active else None,
            }
            run["cases"].append(case_record)
            first_answer = None
            try:
                for index, prompt in enumerate(CASES[label]):
                    print(f"Running {label} turn {index + 1}/{len(CASES[label])}", flush=True)
                    before = analyst.reports.search(identity.user_id)
                    result = await analyst.ask(prompt)
                    payload = dataclasses.asdict(result)
                    after = analyst.reports.search(identity.user_id)
                    stored = [analyst.reports.read(identity.user_id, item["id"]) for item in after]
                    if payload["status"] != "approved":
                        runtime_failures += 1
                    record = {
                        "index": index,
                        "prompt": prompt,
                        "prompt_sha256": {
                            name: hashlib.sha256(
                                (
                                    Path(__file__).resolve().parents[1]
                                    / "src"
                                    / "retail_agent"
                                    / "prompts"
                                    / name
                                ).read_bytes()
                            ).hexdigest()
                            for name in ("analyst.md", "reviewer.md")
                        },
                        "result": payload,
                        "library_before": before,
                        "library_after": after,
                        "stored_reports": stored,
                        "observations": observations(
                            label,
                            index,
                            payload,
                            oracle_active,
                            before,
                            after,
                            stored,
                            first_answer,
                        ),
                        "file": f"{label}-{index + 1}.json",
                    }
                    if index == 0:
                        first_answer = payload.get("answer")
                    case_record["turns"].append(record)
                    _write_json(output / record["file"], record)
                    _write_json(output / "run.json", run)
                    write_markdown(output, run)
                    print(
                        f"Recorded {label}: {payload['status']} in {payload['elapsed_seconds']:.3f}s",
                        flush=True,
                    )
            finally:
                analyst.reports.close()
    run["metadata"]["finished_at"] = datetime.now(UTC).isoformat()
    run["metadata"]["runtime_incomplete_or_failed_turns"] = runtime_failures
    _write_json(output / "run.json", run)
    write_markdown(output, run)
    print(
        f"Wrote {output / 'observations.md'}; manual quality assessment remains pending.",
        flush=True,
    )
    return 1 if runtime_failures else 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--live",
        action="store_true",
        help="Explicitly allow real model calls and selected warehouse calls.",
    )
    result.add_argument(
        "--list-cases",
        action="store_true",
        help="Print English prompts without credentials or model calls.",
    )
    result.add_argument("--backend", choices=("fixture", "bigquery"), default="fixture")
    result.add_argument(
        "--output",
        type=Path,
        default=Path("evals/rewrite/runs") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
    )
    result.add_argument(
        "--case",
        action="append",
        choices=tuple(CASES),
        help="Repeat to select cases; defaults to all listed cases.",
    )
    result.add_argument("--user", choices=tuple(DEMO_USERS), default="alice")
    result.add_argument(
        "--golden-bootstrap",
        action="store_true",
        help="Explicitly enable synthetic, unapproved Golden methods.",
    )
    result.add_argument("--model", help="Override the configured Gemini model.")
    result.add_argument(
        "--timeout", type=float, help="Override the per-turn shared deadline in seconds."
    )
    result.add_argument(
        "--max-model-calls", type=int, help="Override the shared actor/reviewer call limit."
    )
    return result


def main() -> None:
    cli = parser()
    args = cli.parse_args()
    if args.list_cases:
        print(json.dumps(CASES, indent=2))
        return
    if not args.live:
        cli.error(
            "Use --live to authorize real model calls, or --list-cases to inspect prompts offline."
        )
    try:
        code = asyncio.run(run_cases(args))
    except ValueError as exc:
        cli.error(str(exc))
    except KeyboardInterrupt:
        print(
            "Evaluation interrupted. Completed turn artifacts remain in the output directory.",
            file=sys.stderr,
        )
        raise SystemExit(130) from None
    else:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
