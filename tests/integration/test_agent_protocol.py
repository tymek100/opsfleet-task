"""Real ADK loop, scoped tools, reviewer handoff, and persisted effects."""

import asyncio
import json
from decimal import Decimal

import pytest
from google.adk.models.llm_response import LlmResponse

from retail_agent.services.warehouse import QueryGateway
from retail_agent.turn import Turn
from tests.support.models import calls, finish, text, verdict
from tests.support.warehouse import Q1


def query(sql=None):
    return calls(
        (
            "query_data",
            {
                "sql": sql or f"SELECT SUM(sale_price) revenue FROM sales WHERE {Q1}",
                "purpose": "Measure qualifying Q1 revenue",
            },
        )
    )


async def test_reviewer_feedback_returns_to_same_analyst_and_exact_candidate_is_published(
    make_agent,
):
    draft = "Revenue increased because shoppers preferred premium coats."
    final = "Qualifying revenue was **65.65** in Q1 2026 [E1]. The query does not establish why."
    app = make_agent(
        [query(), finish(draft, ["E1"]), finish(final, ["E1"])], [verdict("revise"), verdict()]
    )
    result = await app.ask("Describe Q1 revenue without unsupported explanations.")
    assert result.status == "approved" and result.answer.markdown == final
    assert len(app.model.requests) == 3 and len(app.reviewer_model.requests) == 2
    assert "Verify the claim" in json.dumps(app.model.requests[-1])
    assert all(r["registered_tools"] == [] for r in app.reviewer_model.requests)
    assert Decimal(str(result.evidence[0]["rows"][0]["revenue"])) == Decimal("65.65")
    assert app.history[-1]["markdown"] == final
    assert app.reports.search("alice") == []


async def test_query_failure_is_observed_then_model_selects_a_different_query(make_agent):
    app = make_agent(
        [
            query("SELECT missing_column FROM sales"),
            query(),
            finish("Revenue: 65.65 [E1].", ["E1"]),
        ],
        [verdict()],
    )
    result = await app.ask("Find qualifying Q1 revenue.")
    assert result.answer is not None
    assert result.usage["queries"] == 2
    assert "missing_column" in json.dumps(app.model.requests[1])
    assert len(app.results) == 1


async def test_plain_final_text_requires_completion_protocol_and_review(make_agent):
    app = make_agent(
        [
            text("An unreviewed final answer."),
            finish("Which year should I use?", outcome="clarification"),
        ],
        [verdict()],
    )
    result = await app.ask("Compare our Q1 results.")
    assert result.answer.markdown == "Which year should I use?"
    assert len(app.reviewer_model.requests) == 1
    assert any(item["event"] == "completion_protocol_repair" for item in result.trace)
    assert "unreviewed final" not in json.dumps(app.context_history())


async def test_every_prompt_gets_fresh_budget_while_approved_context_survives(make_agent):
    app = make_agent(
        [
            finish("Which year?", outcome="clarification"),
            finish("Which metric?", outcome="clarification"),
        ],
        [verdict(), verdict()],
        max_model_calls=2,
    )
    first = await app.ask("Compare Q1.")
    second = await app.ask("Use 2026.")
    assert first.status == second.status == "approved"
    assert first.usage["model_calls"] == second.usage["model_calls"] == 2
    assert first.usage["spent_usd"] == second.usage["spent_usd"]
    assert "Which year?" in json.dumps(app.model.requests[1])
    assert len(app.history) == 2


async def test_authorized_save_uses_exact_reviewed_text_and_evidence(make_agent):
    markdown = "## Q1 result\n\nRevenue: **65.65** [E1].\n"
    app = make_agent(
        [
            query(),
            calls(("stage_report_save", {"title": "Quarterly result"})),
            finish(markdown, ["E1"]),
        ],
        [verdict(save=True)],
    )
    result = await app.ask("Measure qualifying Q1 revenue and save the report.")
    assert result.answer.markdown == markdown
    receipt = result.answer.receipts[0]
    assert receipt["status"] == "saved"
    stored = app.reports.read("alice", receipt["id"])
    assert stored["markdown"] == markdown
    assert stored["evidence"] == result.evidence
    assert app.reports.read("bob", receipt["id"]) is None


async def test_stop_never_publishes_or_saves_an_unapproved_candidate(make_agent):
    app = make_agent(
        [calls(("stage_report_save", {"title": "Unrequested"})), finish("Invented revenue: 42.")],
        [verdict("stop")],
    )
    result = await app.ask("Describe our revenue. Do not save anything.")
    assert result.answer is None and result.status == "incomplete"
    assert app.answers == {} and app.history == []
    assert app.reports.db.execute("SELECT COUNT(*) FROM agent_reports").fetchone()[0] == 0


async def test_unapproved_save_intent_is_removed_before_a_revised_answer(make_agent):
    app = make_agent(
        [
            calls(("stage_report_save", {"title": "Unrequested"})),
            finish("Which period?", outcome="clarification"),
            finish("Which quarter should I use?", outcome="clarification"),
        ],
        [verdict(), verdict()],
    )
    result = await app.ask("Describe sales without saving a report.")
    assert result.answer is not None and result.answer.receipts == []
    assert app.reports.search("alice") == []


@pytest.mark.parametrize("invalid", ["not JSON", '{"decision":"approve"}'])
async def test_malformed_review_gets_one_schema_repair_and_never_implicit_approval(
    make_agent, invalid
):
    app = make_agent([finish("Which period?", outcome="clarification")], [text(invalid), verdict()])
    result = await app.ask("Describe sales.")
    assert result.status == "approved"
    assert len(app.reviewer_model.requests) == 2
    assert any(e["event"] == "review_schema_error" for e in result.trace)


async def test_repeated_candidate_and_review_limit_terminate_without_publication(make_agent):
    app = make_agent(
        [finish("Draft one."), finish("Draft two."), finish("Draft three.")],
        [verdict("revise"), verdict("revise")],
        max_answer_reviews=2,
    )
    result = await app.ask("Describe qualifying sales.")
    assert result.answer is None
    assert len(app.reviewer_model.requests) == 2
    assert app.history == [] and app.reports.search("alice") == []


async def test_deletion_token_is_trusted_control_and_never_enters_model_requests(make_agent):
    app = make_agent(
        [
            calls(("preview_report_deletion", {"query": "Quarterly"})),
            finish("Confirm the deletion using the displayed command."),
        ],
        [verdict()],
    )
    report = app.reports.save("alice", "Quarterly", "Historical report.", [], "A-old")
    result = await app.ask("Delete my Quarterly report.")
    token = result.deletion_preview["token"]
    captured = json.dumps(app.model.requests + app.reviewer_model.requests)
    assert token not in captured
    assert app.reports.read("alice", report["id"]) is not None
    assert app.confirm_delete(token)["status"] == "ok"
    assert app.reports.read("alice", report["id"]) is None
    assert app.history == [] and app.answers == {} and app.results == {}


async def test_input_contact_canary_is_rejected_before_any_model_request(make_agent):
    app = make_agent()
    result = await app.ask("Send the report to privacy-canary@example.test")
    assert result.answer is None
    assert app.model.requests == app.reviewer_model.requests == []
    assert app.results == {} and app.history == []


def test_poisoned_artifact_is_rejected_before_storage(make_agent):
    app = make_agent()
    turn = Turn(app, "Measure revenue.")
    with pytest.raises(ValueError):
        turn.artifact(
            {"rows": [{"revenue": 1}], "columns": ["revenue"]}, "Contact canary@example.test"
        )
    assert app.results == {} and turn.new_results == []


async def test_parallel_finish_cannot_approve_before_other_tool_finishes(make_agent):
    app = make_agent(
        [
            calls(
                ("describe_data", {}),
                (
                    "finish_answer",
                    {"markdown": "Premature", "evidence_ids": [], "outcome": "answer"},
                ),
            ),
            finish("Which metric?", outcome="clarification"),
        ],
        [verdict()],
    )
    result = await app.ask("Describe performance.")
    assert result.answer.markdown == "Which metric?"
    assert len(app.reviewer_model.requests) == 1


async def test_runtime_skills_and_golden_methods_are_not_numerical_evidence(make_agent):
    app = make_agent(
        [
            calls(("load_skill", {"name": "revenue-driver-analysis"})),
            calls(
                (
                    "load_skill_resource",
                    {"name": "revenue-driver-analysis", "path": "references/measurement-guide.md"},
                )
            ),
            calls(("list_golden", {})),
            calls(("read_golden", {"example_id": "average_scoped_order_value"})),
            finish("Which period should I query?", outcome="clarification"),
        ],
        [verdict()],
        golden_bootstrap=True,
    )
    result = await app.ask("How would you investigate a revenue change?")
    assert result.answer is not None
    assert app.results == {} and result.evidence == []
    requests = json.dumps(app.model.requests)
    assert "not current analytical evidence" in requests
    reviewer = json.dumps(app.reviewer_model.requests)
    assert "average_scoped_order_value" in reviewer
    assert "revenue-driver-analysis" in reviewer
    assert "confirm_delete" not in app.model.requests[0]["registered_tools"]


async def test_unknown_evidence_reference_is_rejected_before_reviewer(make_agent):
    app = make_agent(
        [finish("Revenue 9 [E404].", ["E404"]), finish("Which period?", outcome="clarification")],
        [verdict()],
    )
    result = await app.ask("Describe revenue.")
    assert result.answer.markdown == "Which period?"
    assert len(app.reviewer_model.requests) == 1
    assert "E404" not in json.dumps(app.context_history())


async def test_private_tool_canary_never_reaches_either_model_or_trace(make_agent, settings):
    canary = "warehouse-canary@example.test"

    class ContaminatedBoundary(QueryGateway):
        async def query(self, sql, parameters=None, timeout=30):
            result = await super().query(sql, parameters, timeout)
            result["rows"][0]["contact"] = canary
            return result

    app = make_agent(
        [query(), finish("I could not obtain usable evidence.", outcome="partial")], [verdict()]
    )
    app.gateway = ContaminatedBoundary(
        ("Calvin Klein",), backend="fixture", fixture_path=settings.fixture_path
    )
    result = await app.ask("Measure qualifying Q1 revenue.")
    assert result.answer is not None and result.answer.evidence_ids == []
    assert app.results == {}
    assert canary not in json.dumps(app.model.requests + app.reviewer_model.requests)
    assert canary not in json.dumps(result.trace)
    assert canary not in (app.settings.data_dir / "events-v2.jsonl").read_text()


async def test_saving_previous_answer_preserves_original_not_confirmation_text(make_agent):
    app = make_agent([finish("Which period should I use?", outcome="clarification")], [verdict()])
    original = await app.ask("Describe sales.")
    app.model.script.extend(
        [
            calls(
                (
                    "stage_report_save",
                    {"title": "Original answer", "target_answer_id": original.answer.id},
                )
            ),
            finish("I have prepared your earlier answer for saving."),
        ]
    )
    app.reviewer_model.script.append(verdict(save=True))
    result = await app.ask("Save the previous answer exactly.")
    saved = app.reports.read("alice", result.answer.receipts[0]["id"])
    assert saved["markdown"] == original.answer.markdown
    assert saved["answer_id"] == original.answer.id
    assert saved["markdown"] != result.answer.markdown


async def test_cancelling_partial_generation_does_not_publish_and_followup_recovers(make_agent):
    waiting, cancelled = asyncio.Event(), asyncio.Event()

    async def interrupted(_request):
        yield LlmResponse(content=text("Unreviewed partial draft."), partial=True)
        waiting.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    app = make_agent([interrupted, finish("Which year?", outcome="clarification")], [verdict()])
    task = asyncio.create_task(app.ask("Compare Q1."))
    await asyncio.wait_for(waiting.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    assert app.answers == {} and app.history == [] and app.last_result is None
    assert app.reviewer_model.requests == []
    result = await app.ask("Try again.")
    assert result.answer.markdown == "Which year?"
    assert "Unreviewed partial draft" not in json.dumps(app.context_history())


async def test_identical_candidate_is_not_rebilled_for_review(make_agent):
    app = make_agent(
        [
            finish("Unsupported draft."),
            finish("Unsupported draft."),
            finish("Which period?", outcome="clarification"),
        ],
        [verdict("revise"), verdict()],
    )
    result = await app.ask("Describe sales.")
    assert result.answer.markdown == "Which period?"
    assert len(app.reviewer_model.requests) == 2
    assert "unchanged candidate" in json.dumps(app.model.requests[-1])


def test_history_excerpts_are_utf8_bounded_and_original_answers_are_intact(make_agent):
    app = make_agent()
    original = "Revenue increased 📈 in the observed period. " * 300
    for index in range(6):
        app.history.append(
            {
                "question": "Explain the trend.",
                "answer_id": f"A{index}",
                "markdown": original,
                "evidence_ids": [],
                "timestamp": app.now().timestamp(),
            }
        )
    history = app.context_history()
    assert history and history[-1]["answer_id"] == "A5"
    assert len(json.dumps(history).encode()) <= min(16000, app.settings.max_review_bytes // 3)
    assert all(len(item["markdown"].encode()) <= 4000 and item["excerpt_only"] for item in history)
    assert all(item["markdown"] == original for item in app.history)


async def test_failed_storage_commit_emits_failure_receipt_without_partial_save(make_agent):
    app = make_agent(
        [
            calls(("stage_report_save", {"title": "Quarterly"})),
            finish("Which period?", outcome="clarification"),
        ],
        [verdict(save=True)],
    )
    app.reports.db.execute("""CREATE TRIGGER reject_save BEFORE INSERT ON report_audit
        WHEN NEW.action = 'save' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
    result = await app.ask("Save your answer.")
    assert result.answer is not None
    assert result.answer.receipts[0]["status"] == "failed"
    assert app.reports.search("alice") == []
    assert app.reports.db.execute("SELECT COUNT(*) FROM report_audit").fetchone()[0] == 0


async def test_reviewer_cannot_approve_with_nonexistent_evidence_reference(make_agent):
    invalid = verdict()
    assert invalid.parts and invalid.parts[0].text
    payload = json.loads(invalid.parts[0].text)
    payload["checks"][0]["evidence_ids"] = ["E999"]
    app = make_agent(
        [finish("Which period?", outcome="clarification")], [text(json.dumps(payload)), verdict()]
    )
    result = await app.ask("Describe revenue.")
    assert result.status == "approved"
    assert len(app.reviewer_model.requests) == 2
    assert len([e for e in result.trace if e["event"] == "review_schema_error"]) == 1
