"""Direct execution and optional real ADK narration over synthetic SQL evidence."""

import json
from collections.abc import AsyncGenerator

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from retail_agent.agent import Analyst
from retail_agent.cli import command
from retail_agent.config import Settings
from retail_agent.model import BoundedGemini
from retail_agent.models import DEMO_USERS, Answer, AppError
from retail_agent.planning import TurnPlan
from retail_agent.reports import ReportStore
from tests.contracts import fixture_plan_for
from tests.fixture_data import FixtureExecutor


class Script:
    def __init__(self, replies: list[types.Content]) -> None:
        self.replies = iter(replies)
        self.payloads: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fixture(question: str, *args: object, **kwargs: object) -> TurnPlan:
            return fixture_plan_for(question)

        monkeypatch.setattr("retail_agent.agent.propose_plan", fixture)

        async def generate(
            model: BoundedGemini, request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            del model, stream
            self.payloads.append(request.model_dump_json(exclude={"tools_dict"}))
            yield LlmResponse(content=next(self.replies))

        monkeypatch.setattr(BoundedGemini, "generate_content_async", generate)


def tool(name: str, args: dict[str, object]) -> types.Content:
    return types.Content(
        role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]
    )


def content(value: object) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=json.dumps(value))])


REPORT_FACTS = [
    "E1.r0.revenue",
    "E1.r0.units_per_order",
    "E2.r0.revenue",
    "E2.r1.revenue",
    "E2.r2.revenue",
    "E3.r0.revenue",
    "E3.r1.revenue",
]


def report_final(**extras: object) -> types.Content:
    payload: dict[str, object] = {
        "kind": "analysis",
        "message": "",
        "narrative": {
            "facts": REPORT_FACTS,
            "actions": [
                {
                    "kind": "cross_sell_test",
                    "metric_id": "E1.r0.units_per_order",
                    "start": "2026-04-01",
                    "end": "2026-07-01",
                    "target": None,
                }
            ],
        },
        **extras,
    }
    return types.Content(role="model", parts=[types.Part(text=json.dumps(payload))])


@pytest.mark.asyncio
async def test_direct_flow_preserves_followup_filters_and_persistence(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script([])
    script.install(monkeypatch)
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "chat")
    first = await analyst.ask("What was revenue for Q1 2026?")
    second = await analyst.ask("What about customer 1?")
    assert first.evidence[0].rows[0]["revenue"] == 350
    assert second.evidence[0].rows[0]["revenue"] == 150
    assert second.evidence[0].request.customer_id == 1
    assert not script.payloads and not store.list("alice")
    stored = store.read("alice", store.save("alice", "chat", "Customer", second))
    assert stored.intent == second.intent and stored.versions == second.versions
    logs = (settings.data_dir / "events.log").read_text()
    assert "evidence_ready" in logs and "CANARY_NAME" not in logs and "What was revenue" not in logs


@pytest.mark.asyncio
async def test_natural_deletion_only_previews_then_token_confirmation(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, answer: Answer
) -> None:
    store.save("alice", "chat", "Q1", answer)
    script = Script([])
    script.install(monkeypatch)
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "chat")
    await analyst.ask("Delete all reports we made in this conversation")
    assert analyst.preview and len(store.list("alice")) == 1
    assert not script.payloads
    command("/confirm " + analyst.preview.token, analyst)
    assert not store.list("alice") and not analyst.history


@pytest.mark.asyncio
async def test_question_pii_blocked_before_planning(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script([])
    script.install(monkeypatch)
    with pytest.raises(AppError, match="remove personal"):
        await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "chat").ask(
            "Analyze canary@example.test"
        )
    assert not script.payloads


@pytest.mark.asyncio
async def test_report_adk_has_no_analytical_tools_and_cannot_autosave(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script([report_final()])
    script.install(monkeypatch)
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "report").ask(
        "Create Q1 2026 report with Q2 actions"
    )
    assert result.quality_status == "validated" and len(result.evidence) == 3
    assert "Suggested next steps" in result.text and not store.list("alice")
    assert len(script.payloads) == 1
    assert "run_analysis" not in script.payloads[0] and "preview_deletion" not in script.payloads[0]
    assert "CANARY_NAME" not in script.payloads[0] and "@example.test" not in script.payloads[0]


@pytest.mark.asyncio
async def test_quality_repair_is_bounded_tool_free_and_does_not_requery(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script([report_final(message="Invented cause"), report_final()])
    script.install(monkeypatch)
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "report").ask(
        "Create Q1 2026 report with Q2 actions"
    )
    assert result.quality_status == "validated" and "Invented" not in result.text
    assert len(result.evidence) == 3 and len(script.payloads) == 2
    repair = json.loads(script.payloads[-1])
    assert not repair.get("tools_dict") and not repair["config"].get("tools")
    assert "analysis_free_text_not_allowed" in script.payloads[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "broken", [report_final(message="Still invalid"), content("invalid"), tool("run_analysis", {})]
)
async def test_failed_repair_preserves_figures_and_next_turn(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, broken: types.Content
) -> None:
    script = Script([report_final(message="Bad claim"), broken])
    script.install(monkeypatch)
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "report")
    result = await analyst.ask("Create Q1 2026 report with Q2 actions")
    assert result.quality_status == "fallback" and "revenue = 350" in result.text
    assert "Bad claim" not in result.text and len(result.evidence) == 3
    assert len(script.payloads) == 2
    assert (await analyst.ask("Q1 report?")).text == "Which year for Q1?"


@pytest.mark.asyncio
async def test_narrative_repair_budget_and_outage_preserve_evidence(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    settings.max_model_calls = 1
    script = Script([report_final(message="Bad claim")])
    script.install(monkeypatch)
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "report").ask(
        "Create Q1 2026 report with Q2 actions"
    )
    assert result.quality_status == "fallback" and len(script.payloads) == 1
    assert len(result.evidence) == 3 and "revenue = 350" in result.text


@pytest.mark.asyncio
async def test_real_adk_native_structured_response_handles_action_dates(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    payload = json.loads(report_final().parts[0].text)  # type: ignore[index, arg-type]
    script = Script([content(payload)])
    script.install(monkeypatch)
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "report").ask(
        "Create Q1 2026 report with Q2 actions"
    )
    assert result.quality_status == "validated" and "01 Apr 2026 to 30 Jun 2026" in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "What was total revenue in Q1 2026?",
        "Q1 2026 report without actions",
        "Did inactivity increase between May 15 and July 1 2026?",
        "List the top 5 products by revenue and separately by number of distinct customers for Q1 2026.",
    ],
)
async def test_requested_facts_need_no_narrative_or_commentary_calls(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, question: str
) -> None:
    settings.commentary_enabled = True
    script = Script([])
    script.install(monkeypatch)
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "facts").ask(
        question
    )
    assert result.quality_status == "validated" and not script.payloads
    if result.intent and result.intent.kind == "churn":
        assert (
            "Eligible customers: 2 → 5" in result.text and "Inactivity was unchanged" in result.text
        )
    if len(result.evidence) == 2:
        assert "by revenue" in result.text and "by distinct customers" in result.text


@pytest.mark.asyncio
async def test_diagnostic_disk_failure_does_not_break_analysis(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    (settings.data_dir / "events.log").mkdir()
    script = Script([])
    script.install(monkeypatch)
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "facts").ask(
        "Q1 2026 revenue"
    )
    assert result.quality_status == "validated" and result.warnings


@pytest.mark.asyncio
@pytest.mark.parametrize("user", ["alice", "bob", "ceo"])
async def test_capability_overview_scoped_and_model_free_after_routing(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, user: str
) -> None:
    script = Script([])
    script.install(monkeypatch)
    result = await Analyst(settings, DEMO_USERS[user], FixtureExecutor(), store, "help").ask(
        "What data is available, and what analyses can you perform?"
    )
    assert (
        DEMO_USERS[user].scope in result.text
        and "best-selling" in result.text
        and not script.payloads
    )


@pytest.mark.asyncio
async def test_schema_is_generated_from_executable_capabilities(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script([])
    script.install(monkeypatch)
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "help").ask(
        "Show the schema and columns."
    )
    assert (
        "inactivity_days" in result.text
        and "minimum" in result.text
        and "order_items" in result.text
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_requested_commentary_review_never_replaces_table(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, approved: bool
) -> None:
    settings.commentary_enabled = True
    text = "Revenue is shown for the authorized brand and selected period."
    script = Script(
        [
            content({"text": text, "metric_ids": ["E1.r0.revenue"]}),
            content({"supported": approved, "relevant": True, "safe": True}),
        ]
    )
    script.install(monkeypatch)
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "explain").ask(
        "Explain revenue for Q1 2026."
    )
    assert result.quality_status == "validated" and result.evidence[0].rows[0]["revenue"] == 350
    assert ("AI commentary" in result.text) == approved and len(script.payloads) == 2


@pytest.mark.asyncio
async def test_narrative_outage_or_unknown_tool_never_loses_data_or_executes_more_queries(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script([tool("run_analysis", {"spec_json": '{"brands":["Levi\'s"]}'})])
    script.install(monkeypatch)
    result = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "outage").ask(
        "Create Q1 2026 report with Q2 actions"
    )
    assert result.quality_status == "fallback" and len(result.evidence) == 3
    assert "revenue = 350" in result.text
    assert (settings.data_dir / "events.log").read_text().count("fixture_query") == 3


@pytest.mark.asyncio
async def test_full_plan_preflight_rejects_excess_queries_before_any_data(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script([])
    script.install(monkeypatch)
    settings.max_queries = 2
    with pytest.raises(AppError, match="query limit"):
        await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "preflight").ask(
            "Q1 2026 report without actions"
        )
    assert "fixture_query" not in (settings.data_dir / "events.log").read_text()
