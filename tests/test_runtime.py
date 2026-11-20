"""Native ADK continuation with scripted model boundaries, no provider credentials.

These verify application orchestration and side effects. Scripted reviewer replies
are deliberately not evidence of real-model answer quality.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

import pytest
from google.adk.models import BaseLlm
from google.adk.models._capabilities import LlmCapabilities
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field, PrivateAttr, SecretStr

from retail_agent.config import Settings
from retail_agent.contracts import DEMO_USERS, REVIEW_CATEGORIES
from retail_agent.runtime import Analyst
from retail_agent.services.warehouse import QueryGateway

REPO = Path(__file__).resolve().parents[1]
Q1_REVENUE = (
    "SELECT SUM(sale_price) AS revenue FROM sales "
    "WHERE purchased_at >= TIMESTAMP '2026-01-01 00:00:00' "
    "AND purchased_at < TIMESTAMP '2026-04-01 00:00:00'"
)
Q1_CUSTOMERS = (
    "SELECT COUNT(DISTINCT user_id) AS customers FROM sales "
    "WHERE purchased_at >= TIMESTAMP '2026-01-01 00:00:00' "
    "AND purchased_at < TIMESTAMP '2026-04-01 00:00:00'"
)
Step = types.Content | Callable[[dict[str, Any]], types.Content]


class ScriptedModel(BaseLlm):
    model: str = "offline-scripted-model"
    script: list[Any] = Field(exclude=True)
    usage: types.GenerateContentResponseUsageMetadata | None = None
    _requests: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self._requests

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        snapshot = json.loads(
            json.dumps(llm_request.model_dump(exclude={"tools_dict"}), default=str)
        )
        snapshot["registered_tools"] = list(llm_request.tools_dict)
        index = len(self._requests)
        self._requests.append(snapshot)
        if index >= len(self.script):
            raise AssertionError("Unexpected extra model call after the scripted completion")
        step = self.script[index]
        content = step(snapshot) if callable(step) else step
        assert isinstance(content, types.Content)
        yield LlmResponse(content=content, partial=False, usage_metadata=self.usage)


def calls(*entries: tuple[str, dict[str, Any]]) -> types.Content:
    return types.Content(
        role="model",
        parts=[
            types.Part(function_call=types.FunctionCall(name=name, args=arguments))
            for name, arguments in entries
        ],
    )


def text(value: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=value)])


def finish(
    markdown: str, evidence: list[str] | None = None, outcome: str = "answer"
) -> types.Content:
    return calls(
        (
            "finish_answer",
            {"markdown": markdown, "evidence_ids": evidence or [], "outcome": outcome},
        )
    )


def review(
    decision: str = "approve", *, save: bool = False, issues: list[dict] | None = None
) -> types.Content:
    failed = {issue["category"] for issue in issues or []} if decision != "approve" else set()
    checks = [
        {
            "category": category,
            "passed": category not in failed,
            "finding": "Scripted test finding; this is not a real model quality judgment.",
            "evidence_ids": [],
        }
        for category in REVIEW_CATEGORIES
    ]
    return text(
        json.dumps(
            {
                "checks": checks,
                "issues": issues or [],
                "save_authorized": save,
                "decision": decision,
            }
        )
    )


def settings(tmp_path: Path) -> Settings:
    return Settings(
        gemini_api_key=SecretStr("offline-test-key"),
        google_cloud_project="offline-test-project",
        backend="fixture",
        fixture_path=REPO / "knowledge/fixtures/retail_seed_v1.sql",
        golden_path=REPO / "knowledge/golden/bootstrap.json",
        golden_bootstrap=True,
        data_dir=tmp_path / "isolated-store",
        question_budget_usd=10,
        turn_timeout_seconds=15,
        review_reserve_seconds=1,
        max_model_calls=20,
        max_tool_calls=30,
        max_queries=8,
        max_context_bytes=400_000,
        model_min_interval_seconds=0,
    )


def make_app(
    tmp_path: Path, analyst: list[Step], reviews: list[Step], **kwargs: Any
) -> tuple[Analyst, ScriptedModel, ScriptedModel]:
    model = ScriptedModel(script=analyst)
    reviewer = ScriptedModel(script=reviews)
    app = Analyst(
        settings(tmp_path), DEMO_USERS["alice"], model=model, reviewer_model=reviewer, **kwargs
    )
    return app, model, reviewer


def observations(request: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [
        part["function_response"]["response"]
        for content in request["contents"]
        for part in content["parts"]
        if (part.get("function_response") or {}).get("name") == name
    ]


def reviewer_payload(request: dict[str, Any]) -> dict[str, Any]:
    for content in request["contents"]:
        if content["role"] == "user":
            for part in content["parts"]:
                if part.get("text", "").startswith("{"):
                    return json.loads(part["text"])
    raise AssertionError("Reviewer did not receive the evidence bundle")


@pytest.mark.asyncio
async def test_follow_up_receives_a_fresh_cost_budget_with_usage_settled_before_review(
    tmp_path: Path,
) -> None:
    app, model, reviewer = make_app(
        tmp_path,
        [finish("Please specify a period.", outcome="clarification")] * 2,
        [review()] * 2,
    )
    app.settings.question_budget_usd = 1
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=500, candidates_token_count=100, thoughts_token_count=50
    )
    model.usage = reviewer.usage = usage
    try:
        first = await app.ask("Compare our performance.")
        second = await app.ask("Use the same metrics for another period.")
        for result in (first, second):
            assert result.status == "approved"
            assert result.usage["spent_usd"] == pytest.approx(0.0056)
            assert result.usage["reserved_usd"] == 0
            assert result.usage["model_calls"] == 2
            analyst_usage = next(
                i
                for i, event in enumerate(result.trace)
                if event["event"] == "model_usage" and event["role"] == "analyst"
            )
            review_start = next(
                i for i, event in enumerate(result.trace) if event["event"] == "review_start"
            )
            assert analyst_usage < review_start
    finally:
        app.reports.close()
        app.knowledge.close()


@pytest.mark.asyncio
async def test_cost_limit_message_identifies_the_per_question_allowance(tmp_path: Path) -> None:
    app, model, _ = make_app(tmp_path, [], [])
    app.settings.question_budget_usd = 0.01
    try:
        result = await app.ask("Compare quarterly revenue.")
        assert result.status == "cost_budget"
        assert "This question reached its cost allowance" in result.message
        assert "shared limit" not in result.message
        assert model.requests == []
    finally:
        app.reports.close()
        app.knowledge.close()


@pytest.mark.asyncio
async def test_skills_load_on_model_request_without_becoming_numerical_evidence(
    tmp_path: Path,
) -> None:
    name = "revenue-driver-analysis"
    approved = (
        "Compare revenue, units sold and realized selling prices before explaining the change."
    )
    app, model, reviewer = make_app(
        tmp_path,
        [calls(("load_skill", {"name": name})), finish(approved)],
        [review()],
    )
    try:
        skill = app.skills.load(name, role="analyst")
        result = await app.ask(
            "How would you investigate a revenue change without guessing its cause?"
        )
        assert result.status == "approved", result.trace
        assert result.answer is not None and result.answer.markdown == approved
        first_request = json.dumps(model.requests[0])
        assert name in first_request
        assert json.dumps(skill["instructions"])[1:-1] not in first_request
        loaded = observations(model.requests[1], "load_skill")[-1]
        assert loaded["instructions"] == skill["instructions"]
        assert loaded["sha256"] == skill["sha256"]
        assert result.usage["tool_calls"] == 2  # Skill loading and reviewed completion.
        assert result.usage["queries"] == 0
        assert result.evidence == [] and result.answer.evidence_ids == []
        bundle = reviewer_payload(reviewer.requests[0])
        assert bundle["loaded_skills"] == [
            {key: skill[key] for key in ("name", "version", "sha256")}
        ]
        assert {event["role"] for event in result.trace if event["event"] == "skill_loaded"} == {
            "analyst",
            "reviewer",
        }
        assert reviewer.requests[0]["registered_tools"] == []
        assert "run_skill_script" not in model.requests[0]["registered_tools"]
    finally:
        app.reports.close()


@pytest.mark.asyncio
async def test_review_skill_is_present_even_when_analyst_loads_no_skill(tmp_path: Path) -> None:
    app, model, reviewer = make_app(
        tmp_path, [finish("Which year should I use?", outcome="clarification")], [review()]
    )
    try:
        result = await app.ask("Compare Q1 revenue with Q2.")
        assert result.status == "approved", result.trace
        guidance = app.skills.review_skill()
        assert json.dumps(guidance["instructions"])[1:-1] in json.dumps(reviewer.requests[0])
        assert json.dumps(guidance["instructions"])[1:-1] not in json.dumps(model.requests[0])
        loaded = [event for event in result.trace if event["event"] == "skill_loaded"]
        assert len(loaded) == 1 and loaded[0]["role"] == "reviewer"
        assert loaded[0]["sha256"] == guidance["sha256"]
    finally:
        app.reports.close()


@pytest.mark.asyncio
async def test_unknown_or_reviewer_only_skill_cannot_escape_role_catalog(tmp_path: Path) -> None:
    app, model, reviewer = make_app(
        tmp_path,
        [
            calls(("load_skill", {"name": "../../.env"})),
            calls(("load_skill", {"name": "analytical-review"})),
            finish("That skill is not available to the analyst.", outcome="partial"),
        ],
        [review()],
    )
    try:
        result = await app.ask("Read the unavailable skill.")
        assert result.status == "approved", result.trace
        assert observations(model.requests[1], "load_skill")[-1]["status"] != "ok"
        assert observations(model.requests[2], "load_skill")[-1]["status"] != "ok"
        assert reviewer_payload(reviewer.requests[0])["loaded_skills"] == []
        assert result.usage["tool_calls"] == 3
    finally:
        app.reports.close()


@pytest.mark.asyncio
async def test_skill_reads_share_tool_budget_and_preserve_completion_reserve(
    tmp_path: Path,
) -> None:
    app, _model, reviewer = make_app(
        tmp_path,
        [
            calls(("load_skill", {"name": "period-comparison"})),
            calls(("load_skill", {"name": "product-ranking-analysis"})),
        ],
        [],
    )
    app.settings.max_tool_calls = 2
    try:
        result = await app.ask("Load methods for comparing periods and rankings.")
        assert result.status == "tools", result.trace
        assert result.answer is None and reviewer.requests == []
        assert result.usage["tool_calls"] == 1
        assert [event["name"] for event in result.trace if event["event"] == "skill_loaded"] == [
            "period-comparison"
        ]
    finally:
        app.reports.close()


@pytest.mark.asyncio
async def test_reference_content_requires_skill_loading_and_separate_resource_read(
    tmp_path: Path,
) -> None:
    name = "revenue-driver-analysis"
    path = "references/measurement-guide.md"
    app, model, _reviewer = make_app(
        tmp_path,
        [
            calls(("load_skill_resource", {"name": name, "path": path})),
            calls(("load_skill", {"name": name})),
            calls(("load_skill_resource", {"name": name, "path": path})),
            finish(
                "Measure realized selling prices and quantities before attributing revenue changes."
            ),
        ],
        [review()],
    )
    try:
        resource = app.skills.read_resource(name, path)
        result = await app.ask("Explain how to investigate a revenue change.")
        assert result.status == "approved", result.trace
        assert (
            observations(model.requests[1], "load_skill_resource")[-1]["status"]
            == "invalid_request"
        )
        assert json.dumps(resource["content"])[1:-1] not in json.dumps(model.requests[2])
        response = observations(model.requests[3], "load_skill_resource")[-1]
        assert response["content"] == resource["content"]
        assert result.usage["tool_calls"] == 4
        events = [event for event in result.trace if event["event"] == "skill_resource_read"]
        assert len(events) == 1 and events[0]["resource_sha256"] == resource["resource_sha256"]
        assert "content" not in events[0] and "instructions" not in events[0]
    finally:
        app.reports.close()


@pytest.mark.asyncio
async def test_native_loop_revises_using_new_evidence_and_publishes_exact_markdown(
    tmp_path: Path,
) -> None:
    draft = "Qualifying revenue was 375.00."
    approved = "Qualifying revenue was **375.00** across **5 distinct customers** in Q1 2026."
    app, model, reviewer = make_app(
        tmp_path,
        [
            calls(("describe_data", {"topic_or_relations": "sales"})),
            calls(("query_data", {"sql": Q1_REVENUE, "purpose": "Q1 revenue"})),
            finish(draft, ["E1"]),
            calls(("query_data", {"sql": Q1_CUSTOMERS, "purpose": "Q1 customers"})),
            finish(approved, ["E1", "E2"]),
        ],
        [
            review(
                "revise",
                issues=[
                    {
                        "category": "coverage",
                        "message": "Include the requested distinct-customer count.",
                        "evidence_ids": ["E1"],
                    }
                ],
            ),
            review(),
        ],
    )
    result = await app.ask(
        "What were Q1 2026 revenue and distinct customers? Keep it in one sentence without a table."
    )
    assert result.status == "approved", result.trace
    assert result.answer is not None and result.answer.markdown == approved
    assert result.answer.evidence_ids == ["E1", "E2"]
    assert len(model.requests) == 5 and len(reviewer.requests) == 2
    assert observations(model.requests[2], "query_data")[-1]["rows"] == [{"revenue": 375.0}]
    assert observations(model.requests[3], "finish_answer")[-1]["status"] == "revise"
    assert "distinct-customer count" in json.dumps(model.requests[3])
    assert observations(model.requests[4], "query_data")[-1]["rows"] == [{"customers": 5}]
    assert not any(e["event"] == "completion_protocol_repair" for e in result.trace)
    assert [e["decision"] for e in result.trace if e["event"] == "review_end"] == [
        "revise",
        "approve",
    ]
    final_bundle = reviewer_payload(reviewer.requests[-1])
    assert final_bundle["candidate"]["markdown"] == approved
    assert final_bundle["evidence"][0]["rows"] == [{"revenue": 375.0}]
    assert final_bundle["evidence"][1]["rows"] == [{"customers": 5}]
    for request in reviewer.requests:
        assert request["registered_tools"] == []
        assert not request["config"].get("tools")
    assert result.usage["model_calls"] == 7


@pytest.mark.asyncio
async def test_raw_final_gets_one_protocol_repair_and_no_unreviewed_text_escapes(
    tmp_path: Path,
) -> None:
    approved = "Which year should I use for the Q1 report?"
    app, model, reviewer = make_app(
        tmp_path,
        [text("Unreviewed draft should never appear."), finish(approved, outcome="clarification")],
        [review()],
    )
    result = await app.ask("Write our Q1 report.")
    assert result.status == "approved", result.trace
    assert result.answer is not None and result.answer.markdown == approved
    assert len(model.requests) == 2 and len(reviewer.requests) == 1
    assert "Submit the complete answer through finish_answer" in json.dumps(model.requests[-1])
    assert sum(e["event"] == "completion_protocol_repair" for e in result.trace) == 1


@pytest.mark.asyncio
async def test_raw_final_repair_is_bounded(tmp_path: Path) -> None:
    app, model, reviewer = make_app(tmp_path, [text("First bypass."), text("Second bypass.")], [])
    result = await app.ask("What can you help with?")
    assert result.answer is None and result.status == "incomplete"
    assert len(model.requests) == 2 and reviewer.requests == []
    assert "First bypass" not in result.message and "Second bypass" not in result.message


@pytest.mark.asyncio
async def test_unknown_evidence_is_rejected_before_review_and_model_can_correct_it(
    tmp_path: Path,
) -> None:
    approved = "Which period should I analyze?"
    app, model, reviewer = make_app(
        tmp_path,
        [finish("Revenue was 999.00.", ["E999"]), finish(approved, outcome="clarification")],
        [review()],
    )
    result = await app.ask("Summarize sales.")
    assert result.status == "approved", result.trace
    assert result.answer is not None and result.answer.markdown == approved
    assert observations(model.requests[1], "finish_answer")[-1]["status"] == "invalid_request"
    assert len(reviewer.requests) == 1
    assert reviewer_payload(reviewer.requests[0])["evidence"] == []


@pytest.mark.asyncio
async def test_finish_batched_with_another_tool_waits_for_observations(tmp_path: Path) -> None:
    approved = "I can analyze authorized sales and help with your saved reports."
    app, model, reviewer = make_app(
        tmp_path,
        [
            calls(
                ("describe_data", {"topic_or_relations": "sales"}),
                (
                    "finish_answer",
                    {"markdown": "Premature draft", "evidence_ids": [], "outcome": "answer"},
                ),
            ),
            finish(approved),
        ],
        [review()],
    )
    result = await app.ask("What can you analyze?")
    assert result.status == "approved", result.trace
    assert result.answer is not None and result.answer.markdown == approved
    assert observations(model.requests[1], "finish_answer")[-1]["status"] == "invalid_request"
    assert observations(model.requests[1], "describe_data")
    assert len(reviewer.requests) == 1


@pytest.mark.asyncio
async def test_unauthorized_save_is_cancelled_and_false_saved_claim_is_revised(
    tmp_path: Path,
) -> None:
    approved = "This is a short report draft. It has not been saved."
    app, model, reviewer = make_app(
        tmp_path,
        [
            calls(("stage_report_save", {"title": "Unrequested report"})),
            finish("The report has been saved."),
            finish(approved),
        ],
        [review(save=False), review()],
    )
    result = await app.ask("Write a short report outline; do not save it.")
    assert result.status == "approved", result.trace
    assert result.answer is not None and result.answer.markdown == approved
    assert result.answer.receipts == []
    assert app.reports.search("alice", "") == []
    assert observations(model.requests[2], "finish_answer")[-1]["status"] == "revise"
    assert reviewer_payload(reviewer.requests[0])["pending_save"] is not None
    assert reviewer_payload(reviewer.requests[1])["pending_save"] is None


@pytest.mark.asyncio
async def test_explicit_save_preserves_exact_previous_approved_answer(tmp_path: Path) -> None:
    original = "Q1 2026 qualifying revenue was **375.00** for Calvin Klein."
    app, model, reviewer = make_app(
        tmp_path,
        [
            calls(("query_data", {"sql": Q1_REVENUE, "purpose": "Q1 revenue"})),
            finish(original, ["E1"]),
        ],
        [review()],
    )
    first = await app.ask("How much qualifying revenue did we earn in Q1 2026?")
    assert first.status == "approved" and first.answer is not None, first.trace
    model.script.extend(
        [
            calls(
                (
                    "stage_report_save",
                    {"title": "Revenue Review", "target_answer_id": first.answer.id},
                )
            ),
            finish("The previous reviewed answer is ready to save."),
        ]
    )
    reviewer.script.append(review(save=True))
    second = await app.ask("Save that answer as Revenue Review.")
    assert second.status == "approved" and second.answer is not None, second.trace
    assert second.answer.receipts[0]["status"] == "saved"
    stored = app.reports.read("alice", second.answer.receipts[0]["id"])
    assert stored is not None and stored["markdown"] == original
    assert stored["answer_id"] == first.answer.id
    assert stored["evidence"][0]["rows"] == [{"revenue": 375.0}]
    assert len(app.reports.search("alice", "")) == 1
    bundle = reviewer_payload(reviewer.requests[-1])
    assert bundle["question"] == "Save that answer as Revenue Review."
    assert bundle["save_target"]["markdown"] == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "markdown",
    ["There are **5 customers**.", "| Metric | Value |\n| --- | ---: |\n| Customers | 5 |"],
)
async def test_model_markdown_is_not_reformatted_or_appended(tmp_path: Path, markdown: str) -> None:
    app, model, reviewer = make_app(
        tmp_path,
        [
            calls(("query_data", {"sql": Q1_CUSTOMERS, "purpose": "Q1 customers"})),
            finish(markdown, ["E1"]),
        ],
        [review()],
    )
    result = await app.ask("How many customers bought in Q1 2026?")
    assert result.status == "approved", result.trace
    assert result.answer is not None and result.answer.markdown == markdown
    assert len(model.requests) == 2 and len(reviewer.requests) == 1


@pytest.mark.asyncio
async def test_user_pii_is_blocked_before_either_model(tmp_path: Path) -> None:
    app, model, reviewer = make_app(tmp_path, [], [])
    result = await app.ask("Analyze customer private-canary@example.test spending.")
    assert result.status == "input_rejected"
    assert model.requests == reviewer.requests == []
    assert result.answer is None
    assert "private-canary" not in result.message


@pytest.mark.asyncio
async def test_contaminated_tool_result_never_reaches_models_or_logs(tmp_path: Path) -> None:
    canary = "warehouse-private-canary@example.test"

    class ContaminatedGateway(QueryGateway):
        async def query(
            self, sql: str, parameters: dict | None = None, timeout: float = 30
        ) -> dict:
            result = await super().query(sql, parameters, timeout)
            result["rows"][0]["unexpected_contact"] = canary
            return result

    gateway = ContaminatedGateway(
        brands=("Calvin Klein",), backend="fixture", fixture_path=settings(tmp_path).fixture_path
    )
    app, model, reviewer = make_app(
        tmp_path,
        [
            calls(("query_data", {"sql": Q1_REVENUE, "purpose": "Q1 revenue"})),
            finish("I could not retrieve usable evidence for this request.", outcome="partial"),
        ],
        [review()],
        gateway=gateway,
    )
    result = await app.ask("Summarize qualifying Q1 2026 revenue.")
    assert result.status == "approved", result.trace
    assert result.answer is not None and result.answer.evidence_ids == []
    assert app.results == {}
    assert canary not in json.dumps(model.requests + reviewer.requests)
    assert canary not in json.dumps(result.trace)
    assert canary not in (app.settings.data_dir / "events-v2.jsonl").read_text()
    assert observations(model.requests[1], "query_data")[-1]["status"] != "ok"


@pytest.mark.asyncio
async def test_deletion_confirmation_token_is_only_available_to_trusted_ui(tmp_path: Path) -> None:
    app, model, reviewer = make_app(
        tmp_path,
        [
            calls(("preview_report_deletion", {"query": "Denim"})),
            finish("Review the exact selection below and confirm if you want to delete it."),
        ],
        [review()],
    )
    mine = app.reports.save("alice", "Denim report", "My report.", [], "mine")
    other = app.reports.save("bob", "Denim private", "Another owner's report.", [], "other")
    result = await app.ask("Delete my reports mentioning Denim.")
    assert result.status == "approved", result.trace
    assert result.deletion_preview is not None
    assert [r["id"] for r in result.deletion_preview["reports"]] == [mine["id"]]
    token = result.deletion_preview["token"]
    assert token not in json.dumps(model.requests + reviewer.requests)
    preview_observation = observations(model.requests[1], "preview_report_deletion")[-1]
    assert "token" not in preview_observation
    assert other["id"] not in json.dumps(model.requests + reviewer.requests)
    assert app.reports.read("alice", mine["id"]) is not None
    assert app.reports.read("bob", other["id"]) is not None


@pytest.mark.asyncio
async def test_reviewer_stop_never_publishes_candidate_or_calls_another_writer(
    tmp_path: Path,
) -> None:
    app, model, reviewer = make_app(
        tmp_path,
        [finish("Unsupported claim that should not be published.")],
        [
            review(
                "stop",
                issues=[
                    {
                        "category": "grounding",
                        "message": "No supporting evidence.",
                        "evidence_ids": [],
                    }
                ],
            )
        ],
    )
    result = await app.ask("Explain our sales performance.")
    assert result.answer is None and result.status == "incomplete"
    assert len(model.requests) == len(reviewer.requests) == 1
    assert "Unsupported claim" not in result.message


@pytest.mark.asyncio
async def test_reviewer_schema_repair_keeps_original_candidate_and_is_budgeted(
    tmp_path: Path,
) -> None:
    markdown = "Which year should I use?"
    app, model, reviewer = make_app(
        tmp_path,
        [finish(markdown, outcome="clarification")],
        [text("Malformed reviewer output."), review()],
    )
    result = await app.ask("Make a Q1 report.")
    assert result.status == "approved", result.trace
    assert result.answer is not None and result.answer.markdown == markdown
    assert len(model.requests) == 1 and len(reviewer.requests) == 2
    assert reviewer_payload(reviewer.requests[-1])["candidate"]["markdown"] == markdown
    assert result.usage["model_calls"] == 3
    assert any(e["event"] == "review_schema_error" for e in result.trace)
