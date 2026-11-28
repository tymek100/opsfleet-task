"""Independent judge prompt definitions; evaluation references are never published here."""

from pathlib import Path
from typing import Literal

from google.genai import types

from evaluation.results import Judgment
from evaluation.settings import EvaluationSettings
from retail_insight.runtime.prompts import PromptSpec


def judge_prompt(
    settings: EvaluationSettings,
    kind: Literal["answer", "trajectory"],
    *,
    instruction: str | None = None,
) -> PromptSpec:
    from evaluation.graders.trajectory import TrajectoryJudgment

    filename = "judge.md" if kind == "answer" else "trajectory.md"
    schema = Judgment if kind == "answer" else TrajectoryJudgment
    return PromptSpec(
        name=f"retail-{kind}-judge",
        instruction=instruction
        if instruction is not None
        else (Path(__file__).parent / "prompts" / filename).read_text(),
        model=settings.judge_model,
        config=types.GenerateContentConfig(
            max_output_tokens=settings.judge_max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        ),
        sources=(f"evaluation/prompts/{filename}",),
        description=(
            f"Independent {kind} judge. context is the sanitized JSON evaluation input. "
            "The application specializes the output schema with observed source/event IDs "
            "and performs attribution checks after generation. Playground uses the base schema."
        ),
    )
