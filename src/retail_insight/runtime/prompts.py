"""Repository-owned prompt definitions shared by inference and evaluation snapshots and Foundry trace correlation."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from google.genai import types

from retail_insight.config import Settings
from retail_insight.contracts import Review
from retail_insight.runtime.skills import SkillCatalog

TRUST_POLICY = Path(__file__).with_name("trust_policy.md")
RUNTIME_PROMPT = Path(__file__).with_name("prompt.md")
ANSWER_STYLE = Path(__file__).with_name("answer_style.md")


@dataclass(frozen=True)
class PromptSpec:
    name: str
    instruction: str
    model: str
    config: types.GenerateContentConfig
    sources: tuple[str, ...]
    description: str

    @property
    def request_overhead_bytes(self) -> int:
        """Serialized instructions/configuration, excluding the candidate and evidence."""
        config = self.config.model_dump(mode="json", exclude_none=True)
        config["system_instruction"] = self.instruction
        return len(json.dumps({"model": self.model, "config": config}).encode())

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
        instruction="\n\n".join(
            path.read_text()
            for path in (
                TRUST_POLICY,
                RUNTIME_PROMPT,
                Path(__file__).parents[1] / "agents/retail/prompt.md",
                ANSWER_STYLE,
            )
        ),
        model=model or settings.gemini_model,
        config=types.GenerateContentConfig(
            max_output_tokens=settings.max_output_tokens,
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(settings.thinking_level)
            ),
        ),
        sources=(
            "src/retail_insight/agents/retail/prompt.md",
            str(TRUST_POLICY),
            str(RUNTIME_PROMPT),
            str(ANSWER_STYLE),
        ),
        description=(
            "Repository analyst instructions. context is the JSON initial context. "
            "Playground tests the prompt only; LangGraph tools, loaded skills, conversation "
            "state and dynamic budget instructions are supplied by the application."
        ),
    )


def reviewer_prompt(
    settings: Settings, *, guidance: dict | None = None, model: str | None = None
) -> PromptSpec:
    guidance = guidance if guidance is not None else SkillCatalog().review_skill()
    return PromptSpec(
        name="retail-reviewer",
        instruction=TRUST_POLICY.read_text()
        + "\n\n"
        + (Path(__file__).parents[1] / "review/prompt.md").read_text()
        + "\n\n"
        + guidance["instructions"]
        + "\n\n"
        + ANSWER_STYLE.read_text(),
        model=model or settings.gemini_model,
        config=types.GenerateContentConfig(
            max_output_tokens=settings.review_output_tokens,
            response_mime_type="application/json",
            response_json_schema=Review.response_schema(),
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(settings.review_thinking_level)
            ),
        ),
        sources=(
            "src/retail_insight/review/prompt.md",
            "src/retail_insight/review/skills/analytical-review/SKILL.md",
            str(TRUST_POLICY),
            str(ANSWER_STYLE),
        ),
        description=(
            "Runtime completion reviewer, including the mandatory analytical-review skill. "
            "context is the JSON candidate, question, authorized scope and evidence bundle."
        ),
    )


def agent_prompt(
    settings: Settings, *, name: str, path: Path, model: str, common: Path | None = None
) -> PromptSpec:
    """Build an agent prompt from explicit files without selecting a business role."""
    paths = (TRUST_POLICY, common, path) if common is not None else (TRUST_POLICY, path)
    paths += (ANSWER_STYLE,)
    return PromptSpec(
        name=name,
        instruction="\n\n".join(item.read_text() for item in paths),
        model=model,
        config=types.GenerateContentConfig(
            max_output_tokens=settings.max_output_tokens,
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(settings.thinking_level)
            ),
        ),
        sources=tuple(str(item) for item in paths),
        description="Agent instructions; tools and authorized context are supplied by the runtime.",
    )
