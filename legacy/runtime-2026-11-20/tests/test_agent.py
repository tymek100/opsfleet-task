"""Behavioral tests for one agent loop, including review as a tool observation."""

import json

import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from retail_agent.agent import Analyst
from retail_agent.cli import command
from retail_agent.config import Settings
from retail_agent.evaluator import Evaluation, ReviewIssue
from retail_agent.models import DEMO_USERS, Answer, AppError, QueryEvidence
from retail_agent.reports import ReportStore
from tests.agent_script import Reply, Script, query, submit, tool
from tests.fixture_data import FixtureExecutor

TOTAL = "SELECT SUM(sale_price) AS revenue FROM sales WHERE purchased_at >= '2026-01-01' AND purchased_at < '2026-04-01'"
CUSTOMERS = "SELECT COUNT(DISTINCT user_id) AS customers FROM sales WHERE purchased_at >= '2026-01-01' AND purchased_at < '2026-04-01'"


def analyst(settings: Settings, store: ReportStore) -> Analyst:
    return Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "chat")


@pytest.mark.asyncio
async def test_query_observation_then_approved_answer(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script(
        monkeypatch, [query(TOTAL), submit("Revenue was {{E1.r0.revenue}}. [E1]", "E1")]
    )
    runtime = analyst(settings, store)
    result = await runtime.ask("What was revenue in Q1 2026?")
    assert result.query_evidence[0].rows == [{"revenue": 350}]
    assert result.text == "Revenue was 350. [E1]"
    assert result.evaluation_status == "approved" and result.quality_status == "validated"
    assert len(script.requests) == 2 and len(script.review_requests) == 1
    assert "350" in script.requests[1].model_dump_json(exclude={"tools_dict"})
    assert script.requests[0].tools_dict and not script.review_requests[0].tools_dict
    assert not store.list("alice")
    assert "CANARY_NAME" not in script.payloads and "canary@example.test" not in script.payloads


@pytest.mark.asyncio
async def test_rejection_returns_to_same_agent_and_adds_evidence(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    revision = Evaluation(
        decision="revise",
        issues=[
            ReviewIssue(
                code="missing_customers", correction="Obtain the requested distinct customer count."
            )
        ],
    )
    script = Script(
        monkeypatch,
        [
            query(TOTAL),
            submit("Revenue {{E1.r0.revenue}}. [E1]", "E1"),
            query(CUSTOMERS),
            submit(
                "Revenue {{E1.r0.revenue}} and customers {{E2.r0.customers}}. [E1] [E2]", "E1", "E2"
            ),
        ],
        [revision, Evaluation(decision="approve")],
    )
    result = await analyst(settings, store).ask("Show Q1 2026 revenue and distinct customers.")
    assert result.evaluation_status == "approved" and len(result.query_evidence) == 2
    assert result.query_evidence[1].rows == [{"customers": 5}]
    feedback = script.requests[2].model_dump_json(exclude={"tools_dict"})
    assert "missing_customers" in feedback and "350" in feedback
    events = (settings.data_dir / "events.log").read_text()
    assert events.count('"event": "fixture_query"') == 2
    assert events.count('"event": "evaluation_complete"') == 2
    assert "plan_created" not in events


@pytest.mark.asyncio
@pytest.mark.parametrize("user, expected", [("alice", 350), ("bob", 900)])
async def test_next_action_depends_on_observation(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    store: ReportStore,
    user: str,
    expected: int,
) -> None:
    def choose(request: LlmRequest) -> types.Content:
        responses = [
            part.function_response
            for content in request.contents
            for part in content.parts or []
            if part.function_response
        ]
        response = responses[-1].response
        assert response is not None
        value = QueryEvidence.model_validate(response["evidence"]).rows[0]["revenue"]
        assert isinstance(value, (int, float))
        assert value == expected
        if value > 500:
            return query(
                "SELECT product_id, SUM(sale_price) AS revenue FROM sales GROUP BY product_id ORDER BY revenue DESC LIMIT 1"
            )
        return query(CUSTOMERS)

    Script(
        monkeypatch,
        [query(TOTAL), choose, submit("Results are shown below. [E1] [E2]", "E1", "E2")],
    )
    result = await Analyst(settings, DEMO_USERS[user], FixtureExecutor(), store, "adaptive").ask(
        "Investigate our Q1 2026 sales."
    )
    assert result.evaluation_status == "approved"
    assert ("product_id" in result.query_evidence[1].rows[0]) == (user == "bob")


@pytest.mark.asyncio
async def test_bad_reference_is_repaired_before_reviewer(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script(
        monkeypatch,
        [
            query(TOTAL),
            submit("Revenue {{E1.r9.revenue}}", "E1"),
            submit("Revenue {{E1.r0.revenue}}", "E1"),
        ],
    )
    result = await analyst(settings, store).ask("Revenue in Q1 2026?")
    assert result.evaluation_status == "approved" and len(script.review_requests) == 1
    assert "answer_grounding" in script.requests[-1].model_dump_json(exclude={"tools_dict"})


@pytest.mark.asyncio
async def test_query_repair_does_not_relax_scope(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    Script(
        monkeypatch,
        [
            query("SELECT unknown_column FROM sales"),
            query(TOTAL),
            submit("Revenue {{E1.r0.revenue}}", "E1"),
        ],
    )
    result = await analyst(settings, store).ask("Q1 2026 revenue?")
    assert result.query_evidence[0].rows == [{"revenue": 350}]
    assert (settings.data_dir / "events.log").read_text().count('"event": "fixture_query"') == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        AppError("Unavailable", code="provider_failure"),
        types.Content(role="model", parts=[types.Part(text="invalid JSON")]),
    ],
)
async def test_evaluator_failure_retains_partial_data(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    store: ReportStore,
    failure: AppError | types.Content,
) -> None:
    script = Script(
        monkeypatch, [query(TOTAL), submit("Revenue {{E1.r0.revenue}}", "E1")], [failure]
    )
    result = await analyst(settings, store).ask("Q1 2026 revenue?")
    assert result.evaluation_status == "incomplete" and result.quality_status == "fallback"
    assert result.query_evidence[0].rows[0]["revenue"] == 350
    assert len(script.requests) == 2 and len(script.review_requests) == 1
    assert not store.list("alice")


@pytest.mark.asyncio
async def test_unchanged_rejected_candidate_stops(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script(
        monkeypatch,
        [
            query(TOTAL),
            submit("Revenue {{E1.r0.revenue}}", "E1"),
            submit("Revenue {{E1.r0.revenue}}", "E1"),
        ],
        [
            Evaluation(
                decision="revise",
                issues=[ReviewIssue(code="missing_context", correction="State the period.")],
            )
        ],
    )
    result = await analyst(settings, store).ask("Q1 2026 revenue?")
    assert result.evaluation_status == "incomplete" and "no_progress" in str(result.warnings)
    assert len(script.review_requests) == 1


@pytest.mark.asyncio
async def test_save_commits_only_after_approval_with_final_metadata(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    def check_not_saved(_: LlmRequest) -> types.Content:
        assert store.list("alice") == []
        return submit("Revenue {{E1.r0.revenue}}. Q1 2026. [E1]", "E1")

    Script(
        monkeypatch,
        [
            tool("save_report", title="Quarter"),
            query(TOTAL),
            submit("Revenue {{E1.r0.revenue}}", "E1"),
            check_not_saved,
        ],
        [
            Evaluation(
                decision="revise",
                issues=[ReviewIssue(code="missing_period", correction="State Q1 2026.")],
            ),
            Evaluation(
                decision="approve", save_authorized=True, save_request_quote="save a report"
            ),
        ],
    )
    result = await analyst(settings, store).ask("Create and save a report on Q1 2026 revenue.")
    records = store.list("alice")
    assert len(records) == 1 and f"Saved report {records[0].id}" in result.text
    saved = store.read("alice", records[0].id)
    assert saved.evaluation_status == "approved" and saved.versions
    assert saved.estimated_cost_usd == result.estimated_cost_usd > 0


@pytest.mark.asyncio
async def test_quoted_save_is_not_authorized(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    Script(
        monkeypatch,
        [
            tool("save_report", title="Quarter"),
            submit("Saving requires an explicit request."),
            submit("Use /save TITLE after an analysis."),
        ],
        [Evaluation(decision="approve"), Evaluation(decision="approve")],
    )
    result = await analyst(settings, store).ask(
        'What would "save this report" do? Do not save anything.'
    )
    assert result.evaluation_status == "approved" and not store.list("alice")


@pytest.mark.asyncio
async def test_delete_still_requires_exact_cli_confirmation(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, answer: Answer
) -> None:
    store.save("alice", "chat", "Quarter", answer)
    Script(
        monkeypatch,
        [tool("preview_deletion", match="Quarter"), submit("Review the deletion preview below.")],
    )
    runtime = analyst(settings, store)
    await runtime.ask("Delete my Quarter report.")
    assert runtime.preview and len(store.list("alice")) == 1
    command("/confirm " + runtime.preview.token, runtime)
    assert not store.list("alice") and not runtime.sources and not runtime.history


@pytest.mark.asyncio
async def test_followup_reuses_source_and_is_reviewed(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script(
        monkeypatch,
        [
            query(TOTAL),
            submit("Revenue {{E1.r0.revenue}}", "E1"),
            tool("read_result", evidence_id="E1"),
            submit("The prior quarter's revenue was {{E1.r0.revenue}}. [E1]", "E1"),
        ],
        [Evaluation(decision="approve"), Evaluation(decision="approve")],
    )
    runtime = analyst(settings, store)
    await runtime.ask("Q1 2026 revenue?")
    followup = await runtime.ask("Remind me of that number.")
    assert followup.evaluation_status == "approved" and len(script.review_requests) == 2
    assert (settings.data_dir / "events.log").read_text().count('"event": "fixture_query"') == 1


@pytest.mark.asyncio
async def test_raw_final_cannot_bypass_evaluation(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    Script(
        monkeypatch,
        [
            query(TOTAL),
            types.Content(role="model", parts=[types.Part(text="Revenue is a billion")]),
        ],
        [],
    )
    result = await analyst(settings, store).ask("Q1 2026 revenue?")
    assert result.evaluation_status == "incomplete" and "billion" not in result.text


@pytest.mark.asyncio
async def test_budget_and_logs_include_review(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    settings.max_model_calls = 3
    Script(monkeypatch, [query(TOTAL), submit("Revenue {{E1.r0.revenue}}", "E1")])
    result = await analyst(settings, store).ask("Q1 2026 revenue?")
    events = [
        json.loads(line) for line in (settings.data_dir / "events.log").read_text().splitlines()
    ]
    assert events[-1]["model_calls"] == 3 and result.evaluation_status == "approved"
    assert "Q1 2026 revenue?" not in (settings.data_dir / "events.log").read_text()


@pytest.mark.asyncio
async def test_selection_preserves_previous_population_and_parent_evidence(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    script = Script(
        monkeypatch,
        [
            query(
                "SELECT product_id, SUM(sale_price) AS revenue FROM sales GROUP BY product_id ORDER BY revenue DESC LIMIT 2"
            ),
            submit("The ranked products are shown below. [E1]", "E1"),
            tool(
                "select_result",
                evidence_id="E1",
                columns=["product_id", "revenue"],
                sort_by="revenue",
                descending=False,
                offset=0,
                limit=1,
            ),
            submit("Among those products, the smaller revenue was {{E2.r0.revenue}}. [E2]", "E2"),
        ],
        [Evaluation(decision="approve"), Evaluation(decision="approve")],
    )
    runtime = analyst(settings, store)
    original = await runtime.ask("Rank our two products by all-time revenue.")
    followup = await runtime.ask("Which of those had the smaller revenue?")
    assert len(original.query_evidence[0].rows) == 2
    assert followup.query_evidence[0].rows == [{"product_id": 3, "revenue": 200}]
    assert followup.query_evidence[0].parent_ids == ["E1"]
    parts = script.review_requests[-1].contents[0].parts
    assert parts and parts[0].text
    reviewed = json.loads(parts[0].text)
    assert reviewed["parent_evidence"][0]["id"] == "E1"
    assert len(reviewed["parent_evidence"][0]["rows"]) == 2
    assert len(runtime.sources["E1"].rows) == 2
    assert (settings.data_dir / "events.log").read_text().count('"event": "fixture_query"') == 1


@pytest.mark.asyncio
async def test_repeated_query_reuses_evidence_but_state_periods_do_not(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    settings.question_budget_usd = 2
    Script(
        monkeypatch,
        [
            query(TOTAL),
            query(TOTAL),
            tool("analyze_states", start="2026-01-01", end="2026-04-01"),
            tool("analyze_states", start="2026-04-01", end="2026-07-01"),
            submit(
                "The quarter and state comparisons are shown below. [E1] [E2] [E3]",
                "E1",
                "E2",
                "E3",
            ),
        ],
    )
    result = await analyst(settings, store).ask(
        "Show Q1 revenue and state breakdowns for Q1 and Q2 2026."
    )
    assert result.evaluation_status == "approved"
    assert len(result.query_evidence) == 3
    assert result.query_evidence[1].rows[0]["revenue"] == 350
    assert result.query_evidence[2].rows == []
    assert (settings.data_dir / "events.log").read_text().count('"event": "fixture_query"') == 3


@pytest.mark.asyncio
async def test_saved_report_citations_are_rebased_without_mutating_original(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    runtime = analyst(settings, store)
    Script(monkeypatch, [query(TOTAL), submit("Revenue {{E1.r0.revenue}}. [E1]", "E1")])
    original = await runtime.ask("Q1 2026 revenue?")
    rid = store.save("alice", "chat", "Quarter", original)
    script = Script(
        monkeypatch,
        [tool("read_report", report_id=rid), submit("Saved revenue {{E2.r0.revenue}}. [E2]", "E2")],
    )
    result = await runtime.ask("What revenue did my Quarter report show?")
    assert result.evaluation_status == "approved" and result.query_evidence[0].id == "E2"
    content = script.requests[-1].contents[-1]
    assert content.parts and content.parts[0].function_response
    response = content.parts[0].function_response.response
    assert response and "Revenue 350. [E2]" in str(response)
    assert store.read("alice", rid).text == original.text
    assert store.read("alice", rid).query_evidence[0].id == "E1"
    assert store.read("alice", rid).artifact_version == 2


@pytest.mark.asyncio
async def test_multiple_tool_calls_cannot_race_submission_and_mutations(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    calls = types.Content(
        role="model",
        parts=[*(query(TOTAL).parts or []), *(tool("save_report", title="Quarter").parts or [])],
    )
    Script(monkeypatch, [calls])
    with pytest.raises(AppError) as exc:
        await analyst(settings, store).ask("Create and save a revenue report.")
    assert exc.value.code == "parallel_tool_calls"
    assert store.list("alice") == []
    assert '"event": "fixture_query"' not in (settings.data_dir / "events.log").read_text()


@pytest.mark.asyncio
async def test_review_limit_does_not_approve_or_save_last_candidate(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    settings.max_answer_reviews = 1
    script = Script(
        monkeypatch,
        [
            tool("save_report", title="Quarter"),
            query(TOTAL),
            submit("Revenue {{E1.r0.revenue}}", "E1"),
            submit("Q1 revenue {{E1.r0.revenue}}", "E1"),
        ],
        [
            Evaluation(
                decision="revise",
                issues=[ReviewIssue(code="missing_period", correction="Include the year.")],
            )
        ],
    )
    result = await analyst(settings, store).ask("Create and save a Q1 2026 revenue report.")
    assert result.evaluation_status == "incomplete" and "review_limit" in str(result.warnings)
    assert len(script.review_requests) == 1 and store.list("alice") == []


@pytest.mark.asyncio
async def test_default_budget_leaves_room_to_submit_and_review_six_small_queries(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    replies: list[Reply] = [
        query(f"SELECT SUM(sale_price) AS revenue FROM sales WHERE product_id={i}")
        for i in range(1, 7)
    ]
    replies.append(
        submit(
            "The requested product results are shown in the tables.",
            *(f"E{i}" for i in range(1, 7)),
        )
    )
    script = Script(monkeypatch, replies)
    answer = await analyst(settings, store).ask(
        "Compare revenue for the six requested product IDs."
    )
    assert answer.evaluation_status == "approved"
    assert len(answer.query_evidence) == 6
    assert len(script.requests) == 7 and len(script.review_requests) == 1
    assert answer.estimated_cost_usd <= 1
    instruction = script.requests[-1].config.model_dump(mode="json")["system_instruction"]
    assert "2 model calls" in instruction and "0 queries" in instruction
