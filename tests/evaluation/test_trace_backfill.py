"""Display repair preserves original execution evidence and rejects drift or ambiguity."""

import json
import sqlite3

import pytest

from evaluation.reporting.trace_backfill import (
    EDITABLE,
    apply_plan,
    build_plan,
    digest,
    encode,
    fingerprint,
    verify_sources,
)
from evaluation.runners.artifacts import write_json
from evaluation.runners.manual import Scenario


@pytest.fixture
def captured_database(tmp_path):
    database = tmp_path / "phoenix.sqlite"
    scenario = Scenario(
        id="scenario-01",
        prompt="Show Q1 revenue.",
        follow_up="Explain the change.",
        intent="Comparison",
        checks=["Both: Ground the answer in observed data."],
    )
    canonical = tmp_path / "canonical.json"
    write_json(canonical, [scenario.model_dump(mode="json")])
    artifacts = tmp_path / "manual"
    run = artifacts / "manual-recheck-test"
    write_json(run / "scenarios.json", [scenario.model_dump(mode="json")])
    write_json(
        run / "manifest.json",
        {
            "phase": "recheck",
            "scenario_sha256": digest(run / "scenarios.json"),
        },
    )
    hashes = {}
    for number, prompt in enumerate((scenario.prompt, scenario.follow_up), 1):
        path = run / f"cases/scenario-01/turn-{number}.json"
        write_json(
            path,
            {
                "step_id": f"turn-{number}",
                "prompt": prompt,
                "markdown": "Revenue: 100." if number == 1 else None,
                "status": "approved" if number == 1 else "unavailable",
                "span_id": str(number) * 16,
                "trace_id": str(number) * 32,
                "trace": [] if number == 1 else [{"event": "provider_failure", "code": 402}],
            },
        )
        hashes[str(path.relative_to(run))] = digest(path)
    write_json(
        run / "progress.json",
        {
            "turn_hashes": hashes,
            "finished_at": "2026-11-22T00:00:06+00:00",
        },
    )
    write_json(
        run / "judge_calls.json",
        [
            {
                "step_id": "scenario-01",
                "kind": "trajectory",
                "status": "ERROR",
                "provider_code": 402,
                "retail.prompt_sha256": "judge-version",
            }
        ],
    )
    with sqlite3.connect(database) as connection:
        connection.executescript("""
        CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE traces(id INTEGER PRIMARY KEY, project_rowid INTEGER REFERENCES projects(id), trace_id TEXT);
        CREATE TABLE spans(id INTEGER PRIMARY KEY, trace_rowid INTEGER REFERENCES traces(id),
          span_id TEXT UNIQUE, parent_id TEXT, name TEXT, start_time TEXT, end_time TEXT,
          attributes TEXT, events TEXT, status_code TEXT, status_message TEXT,
          cumulative_error_count INTEGER);
        CREATE TABLE span_annotations(id INTEGER PRIMARY KEY, span_rowid INTEGER REFERENCES spans(id), label TEXT);
        CREATE TABLE span_costs(id INTEGER PRIMARY KEY, trace_rowid INTEGER, total_cost REAL);
        INSERT INTO projects VALUES(1, 'retail-conversations-20');
        INSERT INTO span_costs VALUES(1, 1, 0.125);
        """)
        for number in (1, 2, 3):
            connection.execute("INSERT INTO traces VALUES(?,1,?)", (number, str(number) * 32))
            attributes = (
                {"retail": {"prompt_sha256": "judge-version"}}
                if number == 3
                else {"session": {"id": "original-session"}}
            )
            connection.execute(
                "INSERT INTO spans VALUES(?,?,?,NULL,?,?,?,?,?,?,?,?)",
                (
                    number,
                    number,
                    str(number) * 16,
                    "retail.judge" if number == 3 else "retail.prompt",
                    f"2026-11-22 00:00:0{number * 2 - 2}",
                    f"2026-11-22 00:00:0{number * 2 - 1}",
                    encode(attributes),
                    '[{"name":"original-evidence"}]',
                    "UNSET",
                    "",
                    0,
                ),
            )
            connection.execute(
                "INSERT INTO span_annotations VALUES(?,?,?)", (number, number, "Existing review")
            )
    return database, artifacts, canonical, run


def rows(database, table):
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY id')]


def test_repair_has_readable_values_correct_failures_and_preserves_evidence(
    captured_database, tmp_path
):
    database, artifacts, canonical, _ = captured_database
    original = rows(database, "spans")
    annotations, costs = rows(database, "span_annotations"), rows(database, "span_costs")
    plan = build_plan(database, artifacts, canonical)
    assert plan["coverage"] == {"retail.prompt": 2, "retail.judge": 1, "OK": 1, "ERROR": 2}
    verify_sources(plan)
    receipt = apply_plan(database, plan, tmp_path / "backup.sqlite")
    assert receipt["updated_spans"] == 3
    changed = rows(database, "spans")
    for before, after in zip(original, changed, strict=True):
        assert {k: v for k, v in before.items() if k not in EDITABLE} == {
            k: v for k, v in after.items() if k not in EDITABLE
        }
    first = json.loads(changed[0]["attributes"])
    assert first["input"]["value"] == "Show Q1 revenue."
    assert first["output"]["value"] == "Revenue: 100."
    assert first["metadata"]["case_id"] == "scenario-01"
    assert "See model spans" in first["metadata"]["historical_cost_capture"]
    assert changed[0]["status_code"] == "OK"
    second, judge = (json.loads(row["attributes"]) for row in changed[1:])
    assert "No answer generated" in second["output"]["value"]
    assert second["retail"]["provider_code"] == 402
    assert "No judgment was produced" in judge["output"]["value"]
    assert [row["cumulative_error_count"] for row in changed] == [0, 1, 1]
    assert rows(database, "span_annotations") == annotations
    assert rows(database, "span_costs") == costs
    assert rows(tmp_path / "backup.sqlite", "spans") == original
    assert build_plan(database, artifacts, canonical)["edits"] == []


def test_modified_capture_is_rejected(captured_database):
    database, artifacts, canonical, run = captured_database
    path = run / "cases/scenario-01/turn-1.json"
    data = json.loads(path.read_text())
    data["markdown"] = "Invented revised answer."
    write_json(path, data)
    with pytest.raises(ValueError, match="Changed or unregistered"):
        build_plan(database, artifacts, canonical)


def test_database_drift_rejected_before_any_update(captured_database, tmp_path):
    database, artifacts, canonical, _ = captured_database
    plan = build_plan(database, artifacts, canonical)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE span_annotations SET label='New human review' WHERE id=1")
    original = rows(database, "spans")
    with pytest.raises(ValueError, match="Database changed"):
        apply_plan(database, plan, tmp_path / "backup.sqlite")
    assert rows(database, "spans") == original
    assert not (tmp_path / "backup.sqlite").exists()


def test_protected_edit_rolls_back_earlier_valid_updates(captured_database, tmp_path):
    database, artifacts, canonical, _ = captured_database
    plan = build_plan(database, artifacts, canonical)
    with sqlite3.connect(database) as connection:
        original = fingerprint(connection)
    plan["edits"][1]["after"]["events"] = "[]"
    with pytest.raises(ValueError, match="protected"):
        apply_plan(database, plan, tmp_path / "backup.sqlite")
    with sqlite3.connect(database) as connection:
        assert fingerprint(connection) == original


def test_ambiguous_judge_call_is_not_guessed(captured_database):
    database, artifacts, canonical, run = captured_database
    calls = json.loads((run / "judge_calls.json").read_text())
    write_json(run / "judge_calls.json", calls * 2)
    with pytest.raises(ValueError, match="uniquely attribute"):
        build_plan(database, artifacts, canonical)


def test_sources_must_remain_unchanged_after_plan(captured_database):
    database, artifacts, canonical, run = captured_database
    plan = build_plan(database, artifacts, canonical)
    (run / "judge_calls.json").write_text("[]")
    with pytest.raises(ValueError, match="Source changed"):
        verify_sources(plan)
