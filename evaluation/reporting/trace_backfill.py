"""Verified, offline display-only repair for immutable Phoenix 22 SQLite spans.

Phoenix's public ingestion API rejects existing span IDs. This maintenance tool
therefore prepares a reviewable plan from a consistent database copy and captured
artifacts. Apply only while the Phoenix service is stopped. No rows are deleted,
no spans are reimported, and source execution events remain byte-for-byte intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

PROJECT = "retail-conversations-20"
PLAN_VERSION = "phoenix-22-span-display-v1"
EDITABLE = {"attributes", "status_code", "status_message", "cumulative_error_count"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(connection: sqlite3.Connection) -> str:
    """Hash logical table contents without emitting secrets or relying on SQLite page layout."""
    result = hashlib.sha256()
    tables = connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    for name, schema in tables:
        result.update(repr((name, schema)).encode())
        quoted = '"' + name.replace('"', '""') + '"'
        rows = sorted(
            (tuple(row) for row in connection.execute(f"SELECT * FROM {quoted}")), key=repr
        )
        for row in rows:
            result.update(repr(row).encode())
    return result.hexdigest()


def flatten(value: dict, prefix="") -> dict:
    result = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict) and name != "metadata":
            result.update(flatten(item, name))
        else:
            result[name] = item
    return result


def merge_attributes(original: dict, additions: dict) -> dict:
    """Match Phoenix OTLP's nested attribute representation without rewriting existing keys."""
    result = json.loads(encode(original))
    for key, value in additions.items():
        if key == "metadata":
            incoming = json.loads(value) if isinstance(value, str) else value
            existing = result.get(key, {})
            if isinstance(existing, str):
                existing = json.loads(existing)
            if not isinstance(existing, dict) or not isinstance(incoming, dict):
                raise ValueError("Cannot merge non-object span metadata")
            result[key] = {**existing, **incoming}
            continue
        parts = key.split(".")
        target = result
        for part in parts[:-1]:
            current = target.setdefault(part, {})
            if not isinstance(current, dict):
                raise ValueError("Conflicting nested span attribute")
            target = current
        target[parts[-1]] = value
    return result


def timestamp(value: str) -> datetime:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return instant.replace(tzinfo=UTC) if instant.tzinfo is None else instant.astimezone(UTC)


def verified_captures(root: Path, canonical: Path, source_hashes: dict, span_ids: set[str]) -> dict:
    from evaluation.runners.manual import load_scenarios

    definitions = {case.id: case.model_dump(mode="json") for case in load_scenarios(canonical)}
    source_hashes[str(canonical.resolve())] = digest(canonical)
    records = {}
    for state_path in sorted(root.glob("*/progress.json")):
        run = state_path.parent
        manifest_path, scenarios_path = run / "manifest.json", run / "scenarios.json"
        if not manifest_path.exists() or not scenarios_path.exists():
            continue
        observed = [json.loads(path.read_text()) for path in run.glob("cases/*/turn-*.json")]
        if not any(turn.get("span_id") in span_ids for turn in observed):
            continue
        manifest = json.loads(manifest_path.read_text())
        if digest(scenarios_path) != manifest.get("scenario_sha256"):
            raise ValueError(f"Scenario capture changed: {run.name}")
        state = json.loads(state_path.read_text())
        scenarios = json.loads(scenarios_path.read_text())
        for path in (manifest_path, scenarios_path, state_path):
            source_hashes[str(path.resolve())] = digest(path)
        for scenario in scenarios:
            if scenario != definitions.get(scenario["id"]):
                raise ValueError(f"Unknown or changed scenario: {scenario['id']}")
            for number, question in enumerate((scenario["prompt"], scenario["follow_up"]), 1):
                relative = f"cases/{scenario['id']}/turn-{number}.json"
                path = run / relative
                expected = state.get("turn_hashes", {}).get(relative)
                if not path.exists() and expected is None:
                    continue
                if not expected or digest(path) != expected:
                    raise ValueError(f"Changed or unregistered turn capture: {run.name}/{relative}")
                turn = json.loads(path.read_text())
                source_hashes[str(path.resolve())] = expected
                if turn["prompt"] != question or turn["step_id"] != f"turn-{number}":
                    raise ValueError("Captured question or turn order changed")
                span_id = turn.get("span_id")
                if not span_id:
                    continue
                if span_id in records:
                    raise ValueError("A span has multiple captured source records")
                records[span_id] = {
                    "turn": turn,
                    "run": run,
                    "manifest": manifest,
                    "state": state,
                    "scenario": scenario,
                    "number": number,
                }
    return records


def prompt_source(record: dict) -> tuple[list[dict], dict]:
    turn = record["turn"]
    return [
        {"event": "prompt_input", "question": turn["prompt"]},
        {
            "event": "turn_result",
            "result": {
                "status": turn["status"],
                "answer": {"markdown": turn["markdown"]}
                if turn.get("markdown") is not None
                else None,
                "trace": turn.get("trace", []),
            },
        },
    ], {
        "retail.run_id": record["run"].name,
        "retail.case_id": record["scenario"]["id"],
        "retail.step_id": turn["step_id"],
        "retail.phase": record["manifest"]["phase"],
    }


def judge_source(row: dict, roots: list[dict], captures: dict, source_hashes: dict):
    """Resolve only a unique recorded trajectory call inside its conversation's time window."""
    candidates = []
    attributes = flatten(json.loads(row["attributes"]))
    for prompt in roots:
        record = captures.get(prompt["span_id"])
        if record is None or record["number"] != 2:
            continue
        run, scenario = record["run"], record["scenario"]
        later = [
            timestamp(other["start_time"])
            for other in roots
            if other["span_id"] in captures
            and captures[other["span_id"]]["run"] == run
            and timestamp(other["start_time"]) > timestamp(prompt["end_time"])
        ]
        bound = min(later) if later else timestamp(record["state"]["finished_at"])
        if (
            not timestamp(prompt["end_time"])
            <= timestamp(row["start_time"])
            <= timestamp(row["end_time"])
            <= bound
        ):
            continue
        path = run / "judge_calls.json"
        if not path.exists():
            continue
        source_hashes[str(path.resolve())] = digest(path)
        calls = json.loads(path.read_text())
        matched = [
            call
            for call in calls
            if call.get("step_id") == scenario["id"]
            and call.get("kind") == "trajectory"
            and call.get("retail.prompt_sha256") == attributes.get("retail.prompt_sha256")
        ]
        if len(matched) == 1:
            candidates.append((record, matched[0]))
    if len(candidates) != 1:
        raise ValueError(
            f"Cannot uniquely attribute judge span {row['span_id']} to a captured call"
        )
    record, call = candidates[0]
    if call.get("status") != "ERROR" or not isinstance(call.get("provider_code"), int):
        raise ValueError("Historical judge repair requires an explicitly captured provider error")
    scenario = record["scenario"]
    return [
        {
            "event": "judge_input",
            "kind": "trajectory",
            "question": f"Evaluate tool use for {scenario['id']}.\nInitial question: {scenario['prompt']}\nFollow-up: {scenario['follow_up']}",
        },
        {
            "event": "judge_result",
            "kind": "trajectory",
            "status": "ERROR",
            "provider_code": call["provider_code"],
            "error_stage": "provider",
            "summary": f"Evaluation unavailable: model provider returned HTTP {call['provider_code']}. No judgment was produced.",
        },
    ], {
        "retail.run_id": record["run"].name,
        "retail.case_id": scenario["id"],
        "retail.step_id": "conversation",
        "retail.phase": record["manifest"]["phase"],
        "retail.judge_kind": "trajectory",
    }


def build_plan(database: Path, artifacts: Path, canonical: Path) -> dict:
    from retail_agent import observability

    sources = {
        str(path.resolve()): digest(path) for path in (Path(__file__), Path(observability.__file__))
    }
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        before = fingerprint(connection)
        roots = [
            dict(row)
            for row in connection.execute(
                "SELECT s.*, t.trace_id FROM spans s JOIN traces t ON t.id=s.trace_rowid "
                "JOIN projects p ON p.id=t.project_rowid WHERE p.name=? AND s.parent_id IS NULL "
                "AND s.name IN ('retail.prompt','retail.judge') ORDER BY s.id",
                (PROJECT,),
            )
        ]
        if not roots:
            raise ValueError("No curated conversation roots found")
        captures = verified_captures(artifacts, canonical, sources, {r["span_id"] for r in roots})
        edits, counts = [], Counter()
        for row in roots:
            if row["name"] == "retail.prompt":
                record = captures.get(row["span_id"])
                if not record or record["turn"]["trace_id"] != row["trace_id"]:
                    raise ValueError(f"Missing exact captured identity for span {row['span_id']}")
                events, context = prompt_source(record)
            else:
                events, context = judge_source(row, roots, captures, sources)
            original = json.loads(row["attributes"])
            display = observability.display_fields(
                row["name"], events, {**flatten(original), **context}
            )
            metadata = json.loads(display["attributes"]["metadata"])
            cost_count = connection.execute(
                "SELECT COUNT(*) FROM span_costs WHERE trace_rowid=? AND total_cost IS NOT NULL",
                (row["trace_rowid"],),
            ).fetchone()[0]
            metadata["historical_cost_capture"] = (
                "See model spans for reported costs; no costs are duplicated on this prompt root."
                if cost_count
                else "No reported model cost is available for this trace; reservations are not billed spend."
            )
            display["attributes"]["metadata"] = encode(metadata)
            amended = merge_attributes(original, {**context, **display["attributes"]})
            status = display["status_code"]
            if status == "UNSET" or row["status_code"] not in {"UNSET", status}:
                raise ValueError(
                    "Captured execution status cannot safely replace the stored status"
                )
            values = {
                "attributes": encode(amended),
                "status_code": status,
                "status_message": display["status_message"] or "",
                "cumulative_error_count": row["cumulative_error_count"]
                + int(status == "ERROR")
                - int(row["status_code"] == "ERROR"),
            }
            counts[row["name"]] += 1
            counts[status] += 1
            if any(row[key] != value for key, value in values.items()):
                edits.append(
                    {
                        "id": row["id"],
                        "span_id": row["span_id"],
                        "trace_id": row["trace_id"],
                        "before": {key: row[key] for key in EDITABLE},
                        "after": values,
                    }
                )
        if fingerprint(connection) != before:
            raise ValueError("Database changed while preparing the repair plan")
    return {
        "version": PLAN_VERSION,
        "project": PROJECT,
        "database_fingerprint": before,
        "source_hashes": sources,
        "coverage": dict(counts),
        "edits": edits,
        "preserves": [
            "span/trace IDs",
            "parents",
            "names",
            "timestamps",
            "events",
            "tokens",
            "cost tables",
            "annotations",
            "datasets",
            "experiments",
        ],
    }


def verify_sources(plan: dict) -> None:
    for name, expected in plan["source_hashes"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Source changed after plan creation: {name}")


def apply_plan(database: Path, plan: dict, backup: Path) -> dict:
    """Apply with the service stopped; create a full backup, then atomically check and update."""
    if plan.get("version") != PLAN_VERSION or plan.get("project") != PROJECT:
        raise ValueError("Unsupported trace repair plan")
    if backup.exists() or database.resolve() == backup.resolve():
        raise ValueError("Use a new backup path distinct from the database")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        if fingerprint(connection) != plan["database_fingerprint"]:
            raise ValueError("Database changed after plan creation; regenerate the plan")
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup) as target:
            connection.backup(target)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            if fingerprint(connection) != plan["database_fingerprint"]:
                raise ValueError("Database changed before the update transaction")
            for edit in plan["edits"]:
                if set(edit["before"]) != EDITABLE or set(edit["after"]) != EDITABLE:
                    raise ValueError("Plan attempts to modify a protected span field")
                row = connection.execute("SELECT * FROM spans WHERE id=?", (edit["id"],)).fetchone()
                if (
                    not row
                    or row["span_id"] != edit["span_id"]
                    or any(row[key] != value for key, value in edit["before"].items())
                ):
                    raise ValueError("Span changed before update")
                after = edit["after"]
                connection.execute(
                    "UPDATE spans SET attributes=?, status_code=?, status_message=?, cumulative_error_count=? WHERE id=?",
                    (
                        after["attributes"],
                        after["status_code"],
                        after["status_message"],
                        after["cumulative_error_count"],
                        edit["id"],
                    ),
                )
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Foreign-key integrity check failed")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        after = fingerprint(connection)
    return {
        "updated_spans": len(plan["edits"]),
        "before": plan["database_fingerprint"],
        "after": after,
        "backup_sha256": digest(backup),
        "backup": str(backup),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--artifacts", type=Path, default=Path(".artifacts/manual"))
    parser.add_argument(
        "--canonical", type=Path, default=Path("evaluation/scenarios/manual_20.json")
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--offline-confirmed", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.apply:
        if not args.offline_confirmed or args.backup is None:
            parser.error(
                "Apply requires a stopped Phoenix service, --offline-confirmed and a new --backup path"
            )
        result = apply_plan(args.database, json.loads(args.plan.read_text()), args.backup)
    else:
        plan = build_plan(args.database, args.artifacts, args.canonical)
        verify_sources(plan)
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        args.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
        result = {
            "plan": str(args.plan),
            "updated_spans": len(plan["edits"]),
            "coverage": plan["coverage"],
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
