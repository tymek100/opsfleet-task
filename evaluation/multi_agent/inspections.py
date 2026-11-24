"""Publish explicit assistant inspections separately from automatic Phoenix grades."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from phoenix.client import Client

from .publication import NAMES

REPORTS = (
    ("INVENTORY_REVIEW.md", "inventory", 40),
    ("DISTRIBUTION_REVIEW.md", "distribution", 40),
    ("COORDINATOR_REVIEW.md", "coordinator", 40),
    ("CANDIDATE_INVENTORY_REVIEW.md", "inventory", 14),
    ("CANDIDATE_DISTRIBUTION_REVIEW.md", "distribution", 10),
    ("CANDIDATE_COORDINATOR_REVIEW.md", "coordinator", 18),
    ("FINAL_DOMAIN_REVIEW.md", None, 8),
    ("FINAL_COORDINATOR_REVIEW.md", "coordinator", 10),
    ("LIVE_DOMAIN_REVIEW.md", None, 6),
    ("LIVE_COORDINATOR_REVIEW.md", "coordinator", 6),
)


def automatic_grade_digest(entries):
    values = [
        {"run": e.experiment_run_id, "name": e.name, "result": e.result, "error": e.error}
        for e in entries
        if " / Assistant inspection" not in e.name
    ]
    values.sort(key=lambda item: (item["run"], item["name"]))
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def parse_report(path, default_role=None):
    text = path.read_text()
    run = re.search(r"`(a2a-\d{8}T\d{6}Z-[0-9a-f]{8})`", text)
    if run is None:
        raise ValueError(f"Missing run identifier in {path}")
    header = None
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        lower = [cell.lower() for cell in cells]
        if "scenario" in lower and "turn" in lower:
            header = lower
            continue
        if not header or len(cells) < len(header):
            continue
        case = cells[header.index("scenario")]
        if not re.fullmatch(r"scenario-\d{2}", case):
            continue
        # Comparison tables contain both old and new labels; the last verdict
        # column is explicitly the inspected candidate, not its baseline.
        verdict_column = max(i for i, name in enumerate(header) if "verdict" in name)
        finding_column = next(i for i, name in enumerate(header) if "finding" in name)
        role = cells[header.index("agent")].lower() if "agent" in header else default_role
        status = cells[verdict_column]
        number = int(cells[header.index("turn")])
        if role not in NAMES or status not in {"PASS", "FAIL", "ERROR"} or number not in {1, 2}:
            raise ValueError(f"Invalid inspection row in {path}: {case}")
        rows.append(
            {
                "run_id": run[1],
                "role": role,
                "case_id": case,
                "turn": number,
                "status": status,
                "finding": " | ".join(cells[finding_column:]),
                "report": str(path),
                "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    keys = [(r["role"], r["case_id"], r["turn"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError(f"Duplicate inspection rows in {path}")
    return rows


def publish(*, phoenix_url="http://127.0.0.1:6006", dry_run=False):
    rows = []
    for filename, role, count in REPORTS:
        parsed = parse_report(Path(__file__).with_name(filename), role)
        if len(parsed) != count:
            raise ValueError(f"Expected {count} completed inspection rows in {filename}")
        rows.extend(parsed)
    client = Client(base_url=phoenix_url)
    experiments = {}
    publications = []
    for row in rows:
        run_path = Path(".artifacts/multi-agent") / row["run_id"]
        manifest = json.loads((run_path / "manifest.json").read_text())
        key = (row["run_id"], row["role"])
        if key not in experiments:
            experiment_id = parse_qs(urlparse(manifest["experiments"][row["role"]]).query)[
                "experimentId"
            ][0]
            experiment = client.experiments.get_experiment(experiment_id=experiment_id)
            dataset = client.datasets.get_dataset(
                dataset=NAMES[row["role"]],
                version_id=experiment["dataset_version_id"],
                timeout=30,
            )
            examples = {item["id"]: item["input"]["case_id"] for item in dataset.examples}
            mapped = {
                examples[item["dataset_example_id"]]: item for item in experiment["task_runs"]
            }
            experiments[key] = (
                experiment_id,
                mapped,
                automatic_grade_digest(experiment["evaluation_runs"]),
            )
        experiment_id, mapped, _ = experiments[key]
        remote = mapped[row["case_id"]]
        part = "initial" if row["turn"] == 1 else "follow_up"
        local_path = run_path / row["role"] / row["case_id"] / f"turn-{row['turn']}.json"
        local = json.loads(local_path.read_text())
        if remote["output"][part].get("markdown") != local.get("markdown"):
            raise ValueError(f"Phoenix answer differs from the inspected artifact: {local_path}")
        name = f"{'Initial' if row['turn'] == 1 else 'Follow-up'} / Assistant inspection"
        metadata = {
            "origin": "implementation assistant; post-hoc manual inspection",
            "human_reviewed": False,
            "sealed_holdout": False,
            "report": row["report"],
            "report_sha256": row["report_sha256"],
            "answer_artifact_sha256": hashlib.sha256(local_path.read_bytes()).hexdigest(),
            "qualification": "Separate from automated grades. Assistant-authored development review, not human calibration.",
        }
        if not dry_run:
            client.experiments.log_evaluation(
                experiment_run_id=remote["id"],
                name=name,
                label=row["status"],
                score=1.0 if row["status"] == "PASS" else 0.0 if row["status"] == "FAIL" else None,
                explanation=row["finding"],
                annotator_kind="LLM",
                metadata=metadata,
                timeout=20,
            )
        publications.append(
            {**row, "experiment_id": experiment_id, "experiment_run_id": remote["id"], "name": name}
        )
    verified = 0
    if not dry_run:
        for experiment_id in {item[0] for item in experiments.values()}:
            actual = client.experiments.get_experiment(experiment_id=experiment_id)
            original_digest = next(
                value[2] for value in experiments.values() if value[0] == experiment_id
            )
            if automatic_grade_digest(actual["evaluation_runs"]) != original_digest:
                raise ValueError("Automatic grades changed during assistant-label publication")
            for expected in (r for r in publications if r["experiment_id"] == experiment_id):
                matches = [
                    entry
                    for entry in actual["evaluation_runs"]
                    if entry.experiment_run_id == expected["experiment_run_id"]
                    and entry.name == expected["name"]
                    and isinstance(entry.result, dict)
                    and entry.result.get("label") == expected["status"]
                ]
                if len(matches) != 1:
                    raise ValueError(
                        f"Published inspection verification failed: {expected['case_id']}"
                    )
                verified += 1
    summary = {
        "published": not dry_run,
        "annotations": len(publications),
        "verified": verified,
        "automatic_grades_preserved": not dry_run,
        "counts": dict(Counter(r["status"] for r in rows)),
        "rows": publications,
    }
    path = Path(".artifacts/multi-agent") / (
        "assistant-inspections-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Assistant inspections: {len(publications)}; verified {verified}; {path}", flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phoenix-url", default="http://127.0.0.1:6006")
    parser.add_argument("--dry-run", action="store_true")
    publish(**vars(parser.parse_args()))
