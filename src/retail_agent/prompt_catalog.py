"""Repository-owned prompt definitions shared by inference and Phoenix publication."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from google.genai import types

from retail_agent.config import Settings
from retail_agent.contracts import Review
from retail_agent.skills import SkillCatalog


@dataclass(frozen=True)
class PromptSpec:
    name: str
    instruction: str
    model: str
    config: types.GenerateContentConfig
    sources: tuple[str, ...]
    description: str

    @property
    def sha256(self) -> str:
        payload = {
            "name": self.name,
            "instruction": self.instruction,
            "model": self.model,
            "config": self.config.model_dump(mode="json", exclude_none=True),
            "context_template": "{{context}}",
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def analyst_prompt(settings: Settings, *, model: str | None = None) -> PromptSpec:
    return PromptSpec(
        name="retail-analyst",
        instruction=(Path(__file__).parent / "prompts/analyst.md").read_text(),
        model=model or settings.gemini_model,
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=settings.max_output_tokens,
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(settings.thinking_level)
            ),
        ),
        sources=("src/retail_agent/prompts/analyst.md",),
        description=(
            "Repository analyst instructions. context is the JSON initial context. "
            "Playground tests the prompt only; ADK tools, loaded skills, conversation "
            "state and dynamic budget instructions are supplied by the application."
        ),
    )


def reviewer_prompt(
    settings: Settings, *, guidance: dict | None = None, model: str | None = None
) -> PromptSpec:
    guidance = guidance if guidance is not None else SkillCatalog().review_skill()
    return PromptSpec(
        name="retail-reviewer",
        instruction=(Path(__file__).parent / "prompts/reviewer.md").read_text()
        + "\n\n"
        + guidance["instructions"],
        model=model or settings.gemini_model,
        config=types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=settings.review_output_tokens,
            response_mime_type="application/json",
            response_json_schema=Review.response_schema(),
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(settings.review_thinking_level)
            ),
        ),
        sources=(
            "src/retail_agent/prompts/reviewer.md",
            "src/retail_agent/skills/library/analytical-review/SKILL.md",
        ),
        description=(
            "Runtime completion reviewer, including the mandatory analytical-review skill. "
            "context is the JSON candidate, question, authorized scope and evidence bundle."
        ),
    )
