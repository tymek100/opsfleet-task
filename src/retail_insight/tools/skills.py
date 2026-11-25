"""Read packaged analytical guidance through the shared tool boundary."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from retail_insight.runtime.privacy import screen

if TYPE_CHECKING:
    from retail_insight.runtime.turn import Turn


class SkillTools:
    def __init__(self, turn: Turn):
        self.turn = turn

    async def load_skill(self, name: str) -> dict:
        """Read a relevant skill from available_skills by exact name; returns guidance, not data."""

        def load():
            result = self.turn.app.skills.load(name, role="analyst")
            screen(json.dumps(result))
            metadata = {key: result[key] for key in ("name", "version", "sha256")}
            self.turn.loaded_skills[name] = metadata
            self.turn.emit("skill_loaded", role="analyst", **metadata)
            return result

        return await self.turn.run_tool("load_skill", load, name)

    async def load_skill_resource(self, name: str, path: str) -> dict:
        """Read a listed reference from a loaded skill; path is relative to its directory."""

        def read():
            if name not in self.turn.loaded_skills:
                return {"status": "invalid_request", "message": "Load this skill first."}
            result = self.turn.app.skills.read_resource(name, path, role="analyst")
            screen(json.dumps(result))
            self.turn.emit(
                "skill_resource_read",
                role="analyst",
                **{
                    key: result[key]
                    for key in ("name", "version", "sha256", "resource", "resource_sha256")
                },
            )
            return result

        return await self.turn.run_tool("load_skill_resource", read, name + ":" + path)
