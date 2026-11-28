"""Publish explicit assistant inspections separately from automatic Phoenix grades."""

import hashlib
import json
import re

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
