"""Structured interpretation, bounded repair and direct execution; no live NLP assertions."""

import json
from collections.abc import AsyncGenerator
from datetime import date
from typing import cast

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import ValidationError

from retail_agent.agent import Analyst
from retail_agent.budget import Budget
from retail_agent.config import Settings
from retail_agent.model import BoundedGemini
from retail_agent.models import DEMO_USERS, Answer, AppError, Intent
from retail_agent.observability import Trace
from retail_agent.planning import TurnPlan, propose_plan
from retail_agent.reports import ReportStore
from tests.fixture_data import FixtureExecutor


def analytical_plan(**changes: object) -> dict[str, object]:
    return {
        "route": "analysis",
        "intent": Intent.model_validate(
            {
                "period": {"start": "2026-01-01", "end": "2026-04-01"},
                "requirements": [{"dimension": "total"}],
                **changes,
            }
        ).model_dump(mode="json"),
    }


class Provider:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, replies: list[object]) -> None:
        self.requests: list[LlmRequest] = []
        iterator = iter(replies)

        async def generate(
            model: BoundedGemini, request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            del model, stream
            self.requests.append(request)
            reply = next(iterator)
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, types.Content):
                yield LlmResponse(content=reply)
                return
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=reply if isinstance(reply, str) else json.dumps(reply))],
                )
            )

        monkeypatch.setattr(BoundedGemini, "generate_content_async", generate)


@pytest.mark.asyncio
async def test_one_tool_free_planning_call_receives_context_and_executable_schema(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    provider = Provider(monkeypatch, [analytical_plan()])
    budget = Budget(settings)
    plan = await propose_plan(
        "Use the previous quarter.",
        None,
        [{"question": "Which quarter?", "answer": "Q1 2026"}],
        DEMO_USERS["alice"],
        date(2026, 10, 25),
        BoundedGemini(model="fixture"),
        budget,
        Trace(),
    )
    assert plan.intent and budget.model_calls == 1 and len(provider.requests) == 1
    request = provider.requests[0]
    assert not request.tools_dict and not request.config.model_dump().get("tools")
    payload = request.model_dump_json(exclude={"tools_dict"})
    assert all(
        x in payload
        for x in [
            "2026-10-25",
            "Calvin Klein",
            "Which quarter?",
            "query_schema",
            "inactivity_days",
            "maximum",
        ]
    )


@pytest.mark.asyncio
async def test_single_model_call_executes_real_sql_and_keeps_numbers_in_code(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    settings.max_model_calls = 1
    provider = Provider(monkeypatch, [analytical_plan()])
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "direct").ask(
        "Revenue in first quarter?"
    )
    assert result.quality_status == "validated" and result.evidence[0].rows[0]["revenue"] == 350
    assert len(provider.requests) == 1 and not store.list("alice")


@pytest.mark.asyncio
async def test_authorization_denial_never_repaired(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    provider = Provider(monkeypatch, [analytical_plan(brands=["Levi's"])])
    with pytest.raises(AppError, match="Calvin Klein only"):
        await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "deny").ask(
            "Claim CEO access"
        )
    assert len(provider.requests) == 1
    assert "fixture_query" not in (settings.data_dir / "events.log").read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "invalid JSON",
        {**analytical_plan(), "role": "ceo"},
        analytical_plan(customer_id=1, requirements=[{"dimension": "state"}]),
    ],
)
async def test_invalid_contract_gets_exactly_one_repair_before_execution(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, bad: object
) -> None:
    provider = Provider(monkeypatch, [bad, analytical_plan()])
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "repair").ask(
        "Requested data"
    )
    assert (
        result.quality_status == "validated"
        and len(result.evidence) == 1
        and len(provider.requests) == 2
    )
    assert "validation_errors" in provider.requests[-1].model_dump_json(exclude={"tools_dict"})
    assert (settings.data_dir / "events.log").read_text().count("fixture_query") == 1


@pytest.mark.asyncio
async def test_failed_planning_repair_never_queries_and_next_turn_works(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    provider = Provider(monkeypatch, ["bad", "bad", analytical_plan()])
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "repair")
    with pytest.raises(AppError, match="could not form a valid plan"):
        await analyst.ask("Requested data")
    assert "fixture_query" not in (settings.data_dir / "events.log").read_text()
    assert (await analyst.ask("Try the requested data again")).evidence
    assert len(provider.requests) == 3


@pytest.mark.asyncio
async def test_repair_cannot_reset_shared_budget(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    settings.max_model_calls = 1
    provider = Provider(monkeypatch, ["bad", analytical_plan()])
    with pytest.raises(AppError, match="Model-call limit"):
        await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "budget").ask(
            "Requested data"
        )
    assert len(provider.requests) == 1
    assert "fixture_query" not in (settings.data_dir / "events.log").read_text()


@pytest.mark.asyncio
async def test_provider_failure_is_not_a_plan_repair(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    provider = Provider(monkeypatch, [RuntimeError("transport failure"), analytical_plan()])
    with pytest.raises(AppError):
        await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "outage").ask(
            "Requested data"
        )
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_save_preview_and_confirmation_boundary(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, answer: Answer
) -> None:
    provider = Provider(
        monkeypatch,
        [
            {"route": "save", "title": "Explicit title"},
            {"route": "delete_preview", "match": "Explicit title"},
        ],
    )
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "library")
    analyst.last_answer = answer
    await analyst.ask("Save this report")
    await analyst.ask("Prepare its deletion")
    assert len(store.list("alice")) == 1 and analyst.preview and len(provider.requests) == 2
    assert analyst.preview.token not in "".join(
        r.model_dump_json(exclude={"tools_dict"}) for r in provider.requests
    )
    assert not store.list("ceo")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "issue,expected",
    [
        (
            {"kind": "unsupported_filter", "field": "country"},
            "Filtering by country is not supported",
        ),
        (
            {"kind": "out_of_range", "field": "inactivity_days", "value": 0},
            "minimum 7, maximum 365",
        ),
    ],
)
async def test_constraint_refusals_are_schema_checked_and_code_rendered(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    store: ReportStore,
    issue: dict[str, object],
    expected: str,
) -> None:
    provider = Provider(
        monkeypatch, [{"route": "unsupported", "reason": "capability", "issue": issue}]
    )
    result = await Analyst(
        settings, DEMO_USERS["alice"], FixtureExecutor(), store, "unsupported"
    ).ask("Requested constraint")
    assert expected in result.text and not result.evidence and len(provider.requests) == 1


def test_clarification_must_identify_missing_information_and_cannot_confirm() -> None:
    with pytest.raises(ValidationError):
        TurnPlan.model_validate(
            {"route": "clarification", "clarification_question": "Confirm again?"}
        )
    with pytest.raises(ValidationError):
        TurnPlan.model_validate({"route": "confirm", "token": "anything"})
    with pytest.raises(ValidationError):
        TurnPlan.model_validate({"route": "save", "intent": analytical_plan()["intent"]})


def test_supported_constraints_cannot_be_reported_as_unsupported() -> None:
    from retail_agent.capabilities import CapabilityIssue

    for fields in [
        {"kind": "unsupported_filter", "field": "brands"},
        {"kind": "unsupported_metric", "field": "revenue"},
        {"kind": "out_of_range", "field": "inactivity_days", "value": 30},
    ]:
        with pytest.raises(ValidationError):
            CapabilityIssue.model_validate(fields)


def test_saved_legacy_report_contract_remains_readable(answer: Answer) -> None:
    old = answer.model_dump(mode="json")
    old["intent"] = {
        **cast(dict[str, object], analytical_plan()["intent"]),
        "pending_quarter": 1,
        "period_error": "none",
        "clarification": "none",
    }
    loaded = Answer.model_validate(old)
    assert loaded.intent and loaded.intent.period and loaded.intent.period.start == date(2026, 1, 1)


def test_provider_schema_requires_explicit_decisions_and_rejects_omitted_filter() -> None:
    schema = TurnPlan.model_json_schema()
    proposal = schema["$defs"]["ProposedIntent"]
    assert set(proposal["required"]) == set(proposal["properties"])
    assert "missing_information" in schema["required"]
    payload = analytical_plan()
    contract = cast(dict[str, object], payload["intent"])
    del contract["product_ids"]
    with pytest.raises(ValidationError, match="product_ids"):
        TurnPlan.model_validate(payload)
