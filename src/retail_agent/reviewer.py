"""A tool-free review call; feedback returns to the existing analyst conversation."""

import json
from collections.abc import Callable

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError

from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.contracts import REVIEW_CATEGORIES, Review, ReviewIssue
from retail_agent.privacy import screen
from retail_agent.prompt_catalog import reviewer_prompt
from retail_agent.provider import AccountedModel, ProviderUnavailable
from retail_agent.skills import SkillCatalog


async def evaluate(
    payload: dict,
    model: BaseLlm,
    budget: Budget,
    settings: Settings,
    emit,
    *,
    review_skill: dict | None = None,
    screener: Callable[[str], str] = screen,
) -> Review:
    content = json.dumps(payload, ensure_ascii=False, default=str)
    if len(content.encode()) > settings.max_review_bytes:
        return Review(
            decision="revise",
            issues=[
                ReviewIssue(
                    category="evidence_bundle_too_large",
                    message="Obtain smaller supported aggregates or narrow the answer; evidence cannot be silently omitted.",
                )
            ],
        )
    guidance = review_skill if review_skill is not None else SkillCatalog().review_skill()
    emit(
        "skill_loaded",
        role="reviewer",
        **{key: guidance[key] for key in ("name", "version", "sha256")},
    )
    prompt_spec = reviewer_prompt(settings, guidance=guidance, model=model.model)
    reviewer = LlmAgent(
        name="completion_reviewer",
        model=AccountedModel(model=model.model, delegate=model).bind(
            budget, emit, reviewer=True, prompt=prompt_spec, screener=screener
        ),
        instruction=prompt_spec.instruction,
        tools=[],
        generate_content_config=prompt_spec.config,
    )
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name="retail_review", user_id="review")
    runner = Runner(app_name="retail_review", agent=reviewer, session_service=sessions)
    try:
        for attempt in range(2):
            text = ""
            async for event in runner.run_async(
                user_id="review",
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=content)]),
                run_config=RunConfig(max_llm_calls=1),
            ):
                if event.is_final_response() and event.content:
                    text = "".join(p.text or "" for p in event.content.parts or [] if not p.thought)
            try:
                review = Review.model_validate_json(text)
                if len(review.checks) != len(REVIEW_CATEGORIES):
                    raise ValueError("The model must provide all five review findings.")
                known_ids = {
                    item["id"]
                    for item in payload.get("evidence", [])
                    + payload.get("other_results_manifest", [])
                    if "id" in item
                }
                if any(
                    evidence_id not in known_ids
                    for finding in [*review.checks, *review.issues]
                    for evidence_id in finding.evidence_ids
                ):
                    raise ValueError("Review findings must reference actual evidence IDs.")
                if review.decision != "approve" and not review.issues:
                    review.issues = [
                        ReviewIssue(
                            category=check.category,
                            message=check.finding,
                            evidence_ids=check.evidence_ids,
                        )
                        for check in review.checks
                        if not check.passed
                    ]
                emit(
                    "review_checks",
                    checks=[
                        {"category": check.category, "passed": check.passed}
                        for check in review.checks
                    ],
                )
                return review
            except (ValidationError, ValueError):
                emit("review_schema_error", attempt=attempt + 1)
                content = (
                    "Return a complete, consistent review of the ORIGINAL candidate and evidence. "
                    "Provide exactly one brief factual finding for each of coverage, grounding, metrics, "
                    "presentation and operations before the decision. Refer only to actual evidence IDs. "
                    "Approve only if every check passed and no unresolved issue remains; otherwise revise or stop."
                )
        raise ProviderUnavailable("The evaluator did not return a valid review.")
    finally:
        await runner.close()
