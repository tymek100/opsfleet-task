"""Read-only skill snapshots parsed by ADK and disclosed through bounded tools.

The bundled directory is application configuration, never a model-supplied path.
Only Markdown instructions and reference files are accepted. The tool adapters
apply the existing turn budget and trace policy around these methods.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from google.adk.skills import load_skill_from_dir

from retail_insight.runtime.privacy import screen

Role = Literal["analyst", "reviewer"]
MAX_SKILL_BYTES = 16_000
MAX_RESOURCE_BYTES = 8_000
MAX_CATALOG_BYTES = 120_000
MAX_SKILLS = 32
MAX_RESOURCES = 8
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class SkillError(ValueError):
    """Safe application error; never disclose an arbitrary host path."""

    code = "invalid_skill"


@dataclass(frozen=True)
class _Skill:
    name: str
    description: str
    version: str
    audience: Role
    sha256: str
    instructions: str
    resources: dict[str, str]

    def metadata(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "sha256": self.sha256,
        }


def _files(directory: Path) -> dict[str, str]:
    """Validate before ADK's loader recursively reads the trusted directory."""
    content = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise SkillError("Skill directories cannot contain symbolic links.")
        relative = path.relative_to(directory).as_posix()
        if path.is_dir():
            if relative != "references":
                raise SkillError("Only a references directory is supported in a runtime skill.")
            continue
        if not path.is_file():
            raise SkillError("Runtime skills contain ordinary Markdown files only.")
        reference = len(path.relative_to(directory).parts) == 2 and relative.startswith(
            "references/"
        )
        if relative != "SKILL.md" and not (reference and path.suffix == ".md"):
            raise SkillError("Runtime skills support SKILL.md and Markdown references only.")
        maximum = MAX_SKILL_BYTES if relative == "SKILL.md" else MAX_RESOURCE_BYTES
        if path.stat().st_size > maximum:
            raise SkillError("A runtime skill file exceeds its byte limit.")
        try:
            value = path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise SkillError("Runtime skill files must be UTF-8 text.") from exc
        if len(value.encode()) > maximum:
            raise SkillError("A runtime skill file exceeds its byte limit.")
        try:
            if screen(value) != value:
                raise SkillError("Runtime skill files cannot contain control characters.")
        except ValueError as exc:
            raise SkillError("Runtime skill content failed its text boundary check.") from exc
        content[relative] = value
        if len(content) > MAX_RESOURCES + 1:
            raise SkillError("A runtime skill contains too many reference files.")
    if "SKILL.md" not in content:
        raise SkillError("Every runtime skill needs a SKILL.md file.")
    return content


class SkillCatalog:
    """Immutable agent-instance snapshot; metadata is disclosed before bodies.

    Construct a new catalog to observe edited files. ``load`` returns a fresh
    dictionary, and resource reads use this snapshot rather than reopening paths.
    """

    def __init__(self, root: Path | None = None):
        package = Path(__file__).parents[2]
        roots = (
            [root]
            if root is not None
            else [
                Path(__file__).parent / "library",
                package / "agents/retail/skills",
                package / "review/skills",
            ]
        )
        for directory in roots:
            if directory.is_symlink() or not directory.is_dir():
                raise SkillError("The runtime skill library must be an ordinary directory.")
        self._skills: dict[str, _Skill] = {}
        total_bytes = 0
        directories = [directory for library in roots for directory in library.iterdir()]
        for directory in sorted(directories, key=lambda item: item.name):
            if directory.is_symlink() or not directory.is_dir():
                raise SkillError("The runtime library must contain ordinary skill directories.")
            if not _NAME.fullmatch(directory.name) or len(self._skills) >= MAX_SKILLS:
                raise SkillError("The runtime skill directory name or count is invalid.")
            content = _files(directory)
            total_bytes += sum(len(value.encode()) for value in content.values())
            if total_bytes > MAX_CATALOG_BYTES:
                raise SkillError("The runtime skill library exceeds its byte limit.")
            try:
                parsed = load_skill_from_dir(directory)
            except (ValueError, OSError) as exc:
                raise SkillError("A runtime skill has invalid ADK frontmatter.") from exc
            if _files(directory) != content:
                raise SkillError("A runtime skill changed while loading. Retry with stable files.")
            frontmatter = parsed.frontmatter
            metadata = frontmatter.metadata
            if (
                frontmatter.allowed_tools is not None
                or frontmatter.model_extra
                or set(metadata) != {"audience", "version"}
                or metadata["audience"] not in ("analyst", "reviewer")
                or not isinstance(metadata["version"], str)
                or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", metadata["version"])
                or not parsed.instructions.strip()
            ):
                raise SkillError(
                    "Runtime skills require an audience and version, without tool grants."
                )
            fingerprint = hashlib.sha256(
                json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            self._skills[frontmatter.name] = _Skill(
                name=frontmatter.name,
                description=frontmatter.description,
                version=metadata["version"],
                audience=metadata["audience"],
                sha256=fingerprint,
                instructions=parsed.instructions,
                resources={path: value for path, value in content.items() if path != "SKILL.md"},
            )

    def _get(self, name: str, role: Role) -> _Skill:
        if role not in ("analyst", "reviewer"):
            raise SkillError("Unknown runtime skill audience.")
        skill = self._skills.get(name)
        if skill is None or skill.audience != role:
            raise SkillError("No such skill is available to this agent.")
        return skill

    def list(self, role: Role = "analyst") -> list[dict]:
        """Return names, descriptions and provenance, without instruction bodies."""
        if role not in ("analyst", "reviewer"):
            raise SkillError("Unknown runtime skill audience.")
        return [skill.metadata() for skill in self._skills.values() if skill.audience == role]

    def load(self, name: str, role: Role = "analyst") -> dict:
        """Read an available skill; resource paths are metadata, not their contents."""
        skill = self._get(name, role)
        return {
            **skill.metadata(),
            "instructions": skill.instructions,
            "resources": sorted(skill.resources),
        }

    def read_resource(self, name: str, path: str, role: Role = "analyst") -> dict:
        """Read only a named reference from this catalog's bounded snapshot."""
        skill = self._get(name, role)
        parts = PurePosixPath(path).parts
        if (
            "\\" in path
            or len(parts) != 2
            or parts[0] != "references"
            or path not in skill.resources
        ):
            raise SkillError("No such reference is available in this skill.")
        return {
            **skill.metadata(),
            "resource": path,
            "resource_sha256": hashlib.sha256(skill.resources[path].encode()).hexdigest(),
            "content": skill.resources[path],
        }

    def review_skill(self) -> dict:
        """Application-pinned guidance for the tool-free evaluator on every review."""
        return self.load("analytical-review", role="reviewer")


class AgentSkills:
    def __init__(self, root: Path):
        self.common = SkillCatalog()
        self.role = SkillCatalog(root)

    def list(self, role: Role = "analyst"):
        return self.role.list(role) + self.common.list(role)

    def load(self, name, role: Role = "analyst"):
        catalog = self.role if name in {s["name"] for s in self.role.list(role)} else self.common
        return catalog.load(name, role)

    def read_resource(self, name, path, role: Role = "analyst"):
        catalog = self.role if name in {s["name"] for s in self.role.list(role)} else self.common
        return catalog.read_resource(name, path, role)

    def review_skill(self):
        guidance = self.common.review_skill()
        guidance["instructions"] += "\n\n" + "\n\n".join(
            self.role.load(s["name"])["instructions"] for s in self.role.list()
        )
        guidance["sha256"] = hashlib.sha256(guidance["instructions"].encode()).hexdigest()
        return guidance
