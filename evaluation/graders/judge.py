"""Tool-free structured judgment with a separate conservative call budget."""

import asyncio
import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeVar

from google import genai
from google.genai import errors, types
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, ValidationError

from evaluation.models import TurnReference
from evaluation.prompt_catalog import judge_prompt
from evaluation.results import Judgment, Trial, TurnRecord
from evaluation.settings import EvaluationSettings
from retail_agent.observability import prompt_attributes, record_observation, sanitize_capture, span
from retail_agent.provider import _usage_counts

PROMPT_PATH = Path(__file__).parents[1] / "prompts/judge.md"
MAX_VISIBLE_RESPONSE_BYTES = 64_000
EXCERPT_POLICY = "exact-source-ids-v2"
Structured = TypeVar("Structured", bound=BaseModel)


class JudgeUnavailable(Exception):
    pass


class JudgmentValidationError(ValueError):
    """A fixed diagnostic from our attribution checks, never provider exception text."""


def visible_response_record(text: str, secrets: tuple[str, ...]) -> dict:
    """Bound diagnostic output after excluding thought parts and credential fields."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = text
    cleaned = sanitize_capture(value, secrets)
    rendered = cleaned if isinstance(cleaned, str) else json.dumps(cleaned, ensure_ascii=False)
    encoded = rendered.encode()
    return {
        "visible_response": encoded[:MAX_VISIBLE_RESPONSE_BYTES].decode(errors="ignore"),
        "visible_response_bytes": len(encoded),
        "visible_response_truncated": len(encoded) > MAX_VISIBLE_RESPONSE_BYTES,
    }


def observed_context(turn: TurnRecord, prior_observations: list[dict]) -> dict:
    # Each prompt uses a new ADK session. Earlier raw tool responses are not
    # retained implicitly: only the captured context and reread payloads count.
    return {
        "initial_context": turn.context,
        # Timeline coordinates are for trajectory attribution, not business evidence IDs.
        "visible_tool_observations": [
            {key: value for key, value in event.items() if key != "event_id"}
            for event in turn.observations
        ],
    }


def source_excerpts(text: str) -> list[str]:
    """Select original substrings without normalizing Markdown, numbers, or spacing."""
    values = [*text.splitlines(), *re.split(r"\n[ \t]*\n", text), text]
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def source_catalog(text: str) -> dict[str, str]:
    return {f"s{index + 1}": value for index, value in enumerate(source_excerpts(text))}


def response_schema(turn: TurnRecord, reference: TurnReference) -> dict:
    excerpts = list(source_catalog(turn.markdown or ""))
    if not excerpts:
        raise JudgeUnavailable("Cannot grade an answer without source excerpts")
    schema = Judgment.model_json_schema()
    definitions = schema["$defs"]
    for name in ("ExtractedFact", "Claim"):
        definitions[name]["properties"]["span"]["enum"] = excerpts
    definitions["CriterionFinding"]["properties"]["spans"]["items"]["enum"] = excerpts
    for key, name, ids in (
        ("facts", "ExtractedFact", [fact.id for fact in reference.facts]),
        (
            "criteria",
            "CriterionFinding",
            [item.id for item in reference.criteria if item.kind == "semantic"],
        ),
    ):
        if ids:
            definitions[name]["properties"]["id"]["enum"] = ids
        else:
            schema["properties"][key]["maxItems"] = 0
    return schema


def resolve_source_ids(judgment: Judgment, turn: TurnRecord) -> Judgment:
    """Resolve provider-selected IDs to original text before any correctness checks."""
    catalog = source_catalog(turn.markdown or "")
    result = judgment.model_copy(deep=True)

    def resolve(value: str, location: str) -> str:
        if value not in catalog:
            raise JudgmentValidationError(f"Judge selected an unknown source ID ({location})")
        return catalog[value]

    for index, fact in enumerate(result.facts):
        fact.span = resolve(fact.span, f"facts[{index}].span")
    for index, claim in enumerate(result.claims):
        claim.span = resolve(claim.span, f"claims[{index}].span")
    for index, criterion in enumerate(result.criteria):
        criterion.spans = [
            resolve(value, f"criteria[{index}].spans[{offset}]")
            for offset, value in enumerate(criterion.spans)
        ]
    return result


def judge_input(turn: TurnRecord, reference: TurnReference, prior_observations: list[dict]) -> dict:
    return {
        "trusted": {
            "question": turn.prompt,
            "fact_bindings": [
                f.model_dump(mode="json", exclude={"value", "source_key", "tolerance"})
                for f in reference.facts
            ],
            "semantic_criteria": [
                c.model_dump(mode="json") for c in reference.criteria if c.kind == "semantic"
            ],
            "allowed_outcomes": reference.allowed_outcomes,
            "answerability": reference.answerability,
        },
        "untrusted": {
            "answer": turn.markdown,
            "source_excerpts": source_catalog(turn.markdown or ""),
            **observed_context(turn, prior_observations),
        },
    }


def validate_judgment(
    judgment: Judgment,
    turn: TurnRecord,
    reference: TurnReference,
    *,
    allowed_excerpts: set[str] | None = None,
) -> None:
    text = turn.markdown or ""
    fact_ids = {f.id for f in reference.facts}
    extracted = [f.id for f in judgment.facts]
    if len(extracted) != len(set(extracted)) or not set(extracted) <= fact_ids:
        raise JudgmentValidationError("Duplicate or invented fact IDs")
    expected = {c.id for c in reference.criteria if c.kind == "semantic"}
    found = [c.id for c in judgment.criteria]
    if set(found) != expected or len(found) != len(expected):
        raise JudgmentValidationError("Missing, repeated, or invented criterion IDs")
    spans = [(f"facts[{i}].span", fact.span) for i, fact in enumerate(judgment.facts)]
    spans += [(f"claims[{i}].span", claim.span) for i, claim in enumerate(judgment.claims)]
    spans += [
        (f"criteria[{i}].spans[{j}]", value)
        for i, criterion in enumerate(judgment.criteria)
        for j, value in enumerate(criterion.spans)
    ]
    for location, value in spans:
        if not value.strip() or value not in text:
            raise JudgmentValidationError(f"Judge fabricated an answer span ({location})")
        if allowed_excerpts is not None and value not in allowed_excerpts:
            raise JudgmentValidationError(f"Judge selected an unlisted answer excerpt ({location})")
    if text.strip() and not judgment.claims and judgment.response_kind == "substantive":
        raise JudgmentValidationError("Substantive answer has no claim coverage")


def _trace_question(payload: dict, kind: str) -> str:
    """Describe the evaluated task without exporting evidence or hidden reference context."""
    if kind == "answer":
        return str(payload.get("trusted", {}).get("question", "Answer evaluation"))
    steps = payload.get("untrusted_execution", {}).get("steps", [])
    return "Review the conversation trajectory:\n" + "\n".join(
        f"{step.get('step_id', 'turn')}: {step.get('question', '')}" for step in steps
    )


def _trace_summary(call: dict) -> str:
    """Successful judgment execution is not an answer-quality PASS."""
    if call["status"] != "completed":
        if call.get("provider_code") is not None:
            return f"Evaluation unavailable: provider HTTP {call['provider_code']}. No judgment produced."
        return f"Evaluation failed during {call.get('error_stage', 'execution')}. No judgment produced."
    result = call["resolved_judgment"]
    if call["kind"] == "trajectory":
        findings = "; ".join(
            f"{finding['criterion']}: {finding['status']}" for finding in result["findings"]
        )
        return f"Trajectory evaluation completed. {findings}. Coverage complete: {result['coverage_complete']}."
    counts = {}
    for claim in result["claims"]:
        counts[claim["label"]] = counts.get(claim["label"], 0) + 1
    labels = ", ".join(f"{count} {label}" for label, count in sorted(counts.items())) or "none"
    passed = sum(item["passed"] for item in result["criteria"])
    return (
        f"Answer evaluation completed. Response: {result['response_kind']}. Claims: {labels}. "
        f"Criteria: {passed} passed, {len(result['criteria']) - passed} failed. "
        f"Extracted facts: {len(result['facts'])}. Coverage complete: {result['coverage_complete']}."
    )


class GeminiJudge:
    def __init__(
        self,
        api_key: str,
        settings: EvaluationSettings,
        *,
        max_cost_usd: float,
        deadline_seconds: float,
        client=None,
    ):
        if not all(math.isfinite(v) and v > 0 for v in (max_cost_usd, deadline_seconds)):
            raise ValueError("Judge cost and time limits must be positive")
        self.settings = settings
        self.ceiling = max_cost_usd
        self.deadline = time.monotonic() + deadline_seconds
        self.accounted_usd = 0.0
        self.calls: list[dict] = []
        self._redaction_secrets = (api_key,)
        self.client = client or genai.Client(
            api_key=api_key,
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=int(settings.judge_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    @property
    def version(self) -> dict:
        return {
            "model": self.settings.judge_model,
            "prompt_sha256": hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest(),
            "schema_sha256": hashlib.sha256(
                json.dumps(Judgment.model_json_schema(), sort_keys=True).encode()
            ).hexdigest(),
            "temperature": 0,
            "max_output_tokens": self.settings.judge_max_output_tokens,
            "thinking_level": "low",
            "source_excerpt_policy": EXCERPT_POLICY,
            "input_price": self.settings.input_usd_per_million,
            "output_price": self.settings.output_usd_per_million,
        }

    async def evaluate(
        self, turn: TurnRecord, reference: TurnReference, prior_observations: list[dict]
    ) -> Judgment:
        def parse(decoded: dict) -> Judgment:
            result = resolve_source_ids(Judgment.model_validate(decoded), turn)
            validate_judgment(
                result, turn, reference, allowed_excerpts=set(source_excerpts(turn.markdown or ""))
            )
            return result

        return await self._request(
            payload=judge_input(turn, reference, prior_observations),
            prompt=PROMPT_PATH.read_text(),
            schema=response_schema(turn, reference),
            step_id=turn.step_id,
            parse=parse,
        )

    async def evaluate_trajectory(self, trial: Trial):
        from evaluation.graders import trajectory

        problem = trajectory.capture_problem(trial)
        if problem:
            raise JudgeUnavailable(problem)

        def parse(decoded: dict) -> trajectory.TrajectoryJudgment:
            result = trajectory.TrajectoryJudgment.model_validate(decoded)
            try:
                trajectory.validate_judgment(result, trial)
            except ValueError as exc:
                raise JudgmentValidationError(str(exc)) from None
            return result

        return await self._request(
            payload=trajectory.trajectory_input(trial),
            prompt=trajectory.PROMPT_PATH.read_text(),
            schema=trajectory.response_schema(trial),
            step_id=trial.id,
            parse=parse,
            kind="trajectory",
            excerpt_policy=trajectory.POLICY,
        )

    async def _request(
        self,
        *,
        payload: dict,
        prompt: str,
        schema: dict,
        step_id: str,
        parse: Callable[[dict], Structured],
        kind: Literal["answer", "trajectory"] = "answer",
        excerpt_policy: str = EXCERPT_POLICY,
    ) -> Structured:
        prompt_spec = judge_prompt(self.settings, kind, instruction=prompt)
        attributes = prompt_attributes(prompt_spec)
        payload_text = json.dumps(
            sanitize_capture(payload, self._redaction_secrets), ensure_ascii=False
        )
        schema_json = json.dumps(schema, ensure_ascii=False)
        input_bound = len((payload_text + prompt + schema_json).encode()) + 1024
        if input_bound > 250_000:
            raise JudgeUnavailable(
                "Judge context and response schema exceed 250 KB; no evidence was silently truncated"
            )
        # Byte-based upper bound includes schema/instructions and output. Output allowance includes thinking tokens.
        reservation = (
            input_bound * self.settings.input_usd_per_million
            + self.settings.judge_max_output_tokens * self.settings.output_usd_per_million
        ) / 1e6
        remaining = min(self.deadline - time.monotonic(), self.settings.judge_timeout_seconds)
        if remaining <= 0 or self.accounted_usd + reservation > self.ceiling:
            raise JudgeUnavailable("Judge budget exhausted")
        self.accounted_usd += reservation
        call = {
            **attributes,
            "step_id": step_id,
            "kind": kind,
            "status": "unknown",
            "accounted_usd": reservation,
            "input_tokens": None,
            "output_tokens": None,
            "thinking_tokens": None,
            "response_schema_sha256": hashlib.sha256(schema_json.encode()).hexdigest(),
            "admitted_input_bytes": input_bound,
            "source_excerpt_policy": excerpt_policy,
        }
        self.calls.append(call)
        started = time.monotonic()
        with span(
            "retail.judge",
            **attributes,
            **{
                "openinference.span.kind": "LLM",
                "llm.model_name": prompt_spec.model,
                "retail.judge_kind": kind,
                "retail.step_id": step_id,
            },
        ) as current:
            record_observation(
                sanitize_capture(
                    {
                        "event": "judge_input",
                        "kind": kind,
                        "question": _trace_question(payload, kind),
                        "step_id": step_id,
                    },
                    self._redaction_secrets,
                ),
                mode="synthetic",
            )
            try:
                async with asyncio.timeout(remaining):
                    response = await self.client.aio.models.generate_content(
                        model=prompt_spec.model,
                        contents=payload_text,
                        config=prompt_spec.config.model_copy(
                            update={"system_instruction": prompt, "response_json_schema": schema}
                        ),
                    )
                counts = _usage_counts(response.usage_metadata)
                if counts is not None:
                    inputs, outputs, thinking = counts
                    input_cost = inputs * self.settings.input_usd_per_million / 1e6
                    output_cost = (outputs + thinking) * self.settings.output_usd_per_million / 1e6
                    cost = input_cost + output_cost
                    self.accounted_usd += cost - reservation
                    call.update(
                        input_tokens=inputs,
                        output_tokens=outputs,
                        thinking_tokens=thinking,
                        accounted_usd=cost,
                    )
                    for name, value in {
                        "llm.token_count.prompt": inputs,
                        "llm.token_count.completion": outputs + thinking,
                        "llm.token_count.total": inputs + outputs + thinking,
                        "llm.cost.prompt": input_cost,
                        "llm.cost.completion": output_cost,
                        "llm.cost.total": cost,
                    }.items():
                        current.set_attribute(name, value)
                parts = [
                    p.text
                    for c in (response.candidates or [])
                    if c.content
                    for p in (c.content.parts or [])
                    if p.text and not p.thought
                ]
                visible = "".join(parts)
                call.update(visible_response_record(visible, self._redaction_secrets))
                decoded = json.loads(visible)
                result = parse(decoded)
                call["resolved_judgment"] = sanitize_capture(
                    result.model_dump(mode="json"), self._redaction_secrets
                )
                call["status"] = "completed"
                return result
            except json.JSONDecodeError as exc:
                call.update(
                    status="ERROR",
                    error="JSONDecodeError",
                    error_stage="parse",
                    validation_error=f"Judge response is not valid JSON (line {exc.lineno}, column {exc.colno})",
                )
                raise JudgeUnavailable(call["validation_error"]) from None
            except ValidationError as exc:
                call.update(
                    status="ERROR",
                    error="ValidationError",
                    error_stage="schema",
                    validation_error=f"Judge response violates the judgment schema ({exc.error_count()} errors)",
                    schema_error_types=sorted(
                        {
                            error["type"]
                            for error in exc.errors(include_input=False, include_url=False)
                        }
                    ),
                )
                raise JudgeUnavailable(call["validation_error"]) from None
            except JudgmentValidationError as exc:
                call.update(
                    status="ERROR",
                    error="JudgmentValidationError",
                    error_stage="attribution",
                    validation_error=str(exc),
                )
                raise JudgeUnavailable(call["validation_error"]) from None
            except errors.APIError as exc:
                message = sanitize_capture(exc.message or "", self._redaction_secrets)
                call.update(
                    status="ERROR",
                    error=type(exc).__name__,
                    error_stage="provider",
                    provider_code=exc.code,
                    provider_message=str(message).encode()[:1024].decode(errors="ignore"),
                )
                raise JudgeUnavailable(f"Judge provider request failed (code {exc.code})") from None
            except Exception as exc:
                call["status"] = "ERROR"
                call["error"] = type(exc).__name__
                call["error_stage"] = "provider_or_runtime"
                raise JudgeUnavailable(f"Judge call failed: {type(exc).__name__}") from None
            finally:
                if call["status"] == "unknown":
                    call.update(status="ERROR", error_stage="interrupted")
                call["elapsed_seconds"] = round(time.monotonic() - started, 3)
                completed = call["status"] == "completed"
                current.set_attribute("retail.status", call["status"])
                current.set_status(Status(StatusCode.OK if completed else StatusCode.ERROR))
                record_observation(
                    {
                        "event": "judge_result",
                        "kind": kind,
                        "status": call["status"],
                        "summary": _trace_summary(call),
                        "provider_code": call.get("provider_code"),
                        "error_stage": call.get("error_stage"),
                    },
                    mode="synthetic",
                )

    async def close(self) -> None:
        async with asyncio.timeout(2):
            await self.client.aio.aclose()
