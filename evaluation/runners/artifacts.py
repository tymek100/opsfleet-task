"""Frozen inputs and append-only grading versions, independent of Phoenix."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from evaluation.models import Case
from evaluation.results import RunManifest
from retail_insight.config import Settings, repository_root


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")
    temporary.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text())


def identifier(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"


def _git(*args: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=repository_root(), stderr=subprocess.DEVNULL, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return b"unknown"


def prepare_run(
    root: Path,
    cases: list[Case],
    settings: Settings,
    *,
    suite: str,
    repetitions: int,
    max_cost_usd: float,
    deadline_seconds: float,
) -> tuple[Path, RunManifest]:
    from evaluation.data import fixture_path

    directory = root / identifier("run")
    directory.mkdir(parents=True, exist_ok=False)
    hashes = {}
    fixtures = {}
    for case in cases:
        path = directory / "cases" / f"{case.id}.json"
        write_json(path, case)
        hashes[case.id] = digest(path)
        fixture = fixture_path(case)
        for source in (fixture, fixture.with_suffix(".json")):
            frozen = directory / "fixtures" / source.name
            frozen.parent.mkdir(exist_ok=True)
            if frozen.exists() and digest(frozen) != digest(source):
                raise ValueError("Fixture filename collision")
            frozen.write_bytes(source.read_bytes())
            fixtures[source.name] = digest(source)
    repo = repository_root()
    paths = [
        *repo.glob("src/retail_insight/**/*.py"),
        *repo.glob("src/retail_insight/**/*.md"),
    ]
    safe_settings = settings.model_dump(
        mode="json",
        exclude={
            "gemini_api_key",
            "google_cloud_project",
            "data_dir",
            "fixture_path",
        },
    )
    manifest = RunManifest(
        id=directory.name,
        created_at=datetime.now(UTC).isoformat(),
        suite=suite,
        case_ids=[case.id for case in cases],
        repetitions=repetitions,
        dataset_sha256=hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        cases_sha256=hashes,
        fixture_hashes=fixtures,
        git_commit=_git("rev-parse", "HEAD").decode().strip(),
        git_diff_sha256=hashlib.sha256(_git("diff", "HEAD")).hexdigest(),
        lockfile_sha256=digest(repo / "uv.lock"),
        runtime_hashes={str(path.relative_to(repo)): digest(path) for path in sorted(paths)},
        harness_hashes={
            str(path.relative_to(repo)): digest(path)
            for path in sorted(
                [*repo.glob("evaluation/runners/*.py"), *repo.glob("evaluation/*.py")]
            )
        },
        model=settings.gemini_model,
        settings=safe_settings,
        max_cost_usd=max_cost_usd,
        deadline_seconds=deadline_seconds,
        human_reviewed=all(c.provenance.human_reviewed for c in cases),
        planned_trials=len(cases) * repetitions,
    )
    write_json(directory / "manifest.json", manifest)
    return directory, manifest


def frozen_cases(directory: Path) -> list[Case]:
    manifest = RunManifest.model_validate(read_json(directory / "manifest.json"))
    cases = []
    for name, expected in manifest.fixture_hashes.items():
        if digest(directory / "fixtures" / name) != expected:
            raise ValueError(f"Frozen fixture has been modified: {name}")
    for key in manifest.case_ids:
        path = directory / "cases" / f"{key}.json"
        if digest(path) != manifest.cases_sha256[key]:
            raise ValueError(f"Frozen case has been modified: {key}")
        cases.append(Case.model_validate(read_json(path)))
    return cases
