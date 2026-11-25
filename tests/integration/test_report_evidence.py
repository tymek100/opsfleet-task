"""Report observations reach the real reviewer handoff without SQL or control tokens."""

import json

from tests.support.models import calls, finish, verdict


def review_payload(app, index=0):
    request = app.reviewer_model.requests[index]
    return json.loads(request["contents"][0]["parts"][0]["text"])


async def test_preview_cancel_and_library_state_are_reviewable_without_queries(make_agent):
    app = make_agent(
        [
            calls(("search_reports", {"query": "Review queue"})),
            calls(("preview_report_deletion", {"query": "Review queue"})),
            finish("One report matches. Nothing has been deleted.", ["E1", "E2"]),
            calls(("cancel_report_deletion", {})),
            calls(("search_reports", {})),
            finish("Cancelled. Review queue remains in your library.", ["E3", "E4"]),
        ],
        [verdict(), verdict()],
    )
    owned = app.reports.save("workspace", "Review queue", "Owned report.", [], "A-owned")
    private = app.reports.save(
        "other-workspace", "Private report", "Other workspace only.", [], "A-private"
    )

    preview = await app.ask("Preview deleting Review queue; do not delete it yet.")
    token = preview.deletion_preview["token"]
    first = review_payload(app)["evidence"]
    assert [item["operation"] for item in first] == ["search_reports", "preview_report_deletion"]
    assert first[0]["observation"]["reports"][0]["id"] == owned["id"]
    assert first[1]["observation"]["status"] == "confirmation_required"
    assert first[1]["observation"]["reports"] == [{"id": owned["id"], "title": "Review queue"}]
    assert set(first[1]["observation"]) == {"status", "message", "reports"}
    assert preview.deletion_preview["reports"][0]["version"] == owned["version"]
    assert app.reports.read("workspace", owned["id"]) is not None

    cancelled = await app.ask("Cancel that deletion and show the remaining report titles.")
    second = review_payload(app, 1)["evidence"]
    assert [item["operation"] for item in second] == ["cancel_report_deletion", "search_reports"]
    assert second[0]["observation"] == {"status": "ok", "cancelled": True, "deleted_ids": []}
    assert second[1]["observation"]["reports"][0]["id"] == owned["id"]
    assert all(item["evidence_type"] == "report_operation" for item in [*first, *second])
    assert preview.usage["queries"] == cancelled.usage["queries"] == 0
    captured = json.dumps(
        app.model.requests + app.reviewer_model.requests + list(app.results.values())
    )
    assert token not in captured
    assert private["id"] not in captured and "Other workspace only." not in captured
    assert app.reports.read("workspace", owned["id"]) is not None
    assert app.reports.read("other-workspace", private["id"]) is not None
    assert app.confirm_delete(token)["status"] == "invalid_confirmation"


async def test_saved_text_and_original_ids_survive_historical_evidence_readback(make_agent):
    app = make_agent(reviews=[verdict()])
    saved = app.reports.save(
        "workspace",
        "Prior quarter",
        "Exact saved **historical** text: 12.50.",
        [{"id": "old-evidence", "columns": ["revenue"], "rows": [{"revenue": 12.5}]}],
        "A-original",
    )
    app.model.script.extend(
        [
            calls(("read_report", {"report_id": saved["id"]})),
            calls(("read_result", {"result_id": "E2"})),
            finish("The saved report contains historical revenue of 12.50.", ["E3"]),
        ]
    )
    result = await app.ask("Read my saved Prior quarter report exactly.")
    evidence = review_payload(app)["evidence"][0]
    observation = evidence["observation"]
    assert evidence["parents"] == ["E2"]
    assert evidence["operation"] == "read_report"
    assert observation["historical"] is True
    assert observation["report"]["id"] == saved["id"]
    assert observation["report"]["answer_id"] == "A-original"
    assert observation["report"]["markdown"] == saved["markdown"]
    assert observation["evidence"][0]["rows"] == [{"revenue": 12.5}]
    assert result.usage["queries"] == 0


async def test_exact_prior_answer_is_reviewable_with_original_answer_id(make_agent):
    app = make_agent([finish("Which quarter should I use?", outcome="clarification")], [verdict()])
    previous = await app.ask("Describe our sales.")
    app.model.script.extend(
        [
            calls(("read_answer", {"answer_id": previous.answer.id})),
            finish("I asked which quarter to use.", ["E1"]),
        ]
    )
    app.reviewer_model.script.append(verdict())
    await app.ask("What did you ask me in your previous answer?")
    evidence = review_payload(app, 1)["evidence"][0]
    assert evidence["operation"] == "read_answer"
    assert evidence["observation"]["id"] == previous.answer.id
    assert evidence["observation"]["markdown"] == previous.answer.markdown
    assert evidence["observation"]["historical"] is True
    response = next(
        part["function_response"]["response"]
        for content in app.model.requests[-1]["contents"]
        for part in content["parts"]
        if (part.get("function_response") or {}).get("name") == "read_answer"
    )
    assert response["id"] == previous.answer.id
    assert response["evidence_id"] == "E1"


async def test_unowned_report_absence_is_supported_without_exposing_its_content(make_agent):
    app = make_agent(reviews=[verdict()])
    private = app.reports.save(
        "other-workspace", "Private title", "Private content.", [], "A-private"
    )
    app.model.script.extend(
        [
            calls(("read_report", {"report_id": private["id"]})),
            finish("That report was not found in your library.", ["E1"]),
        ]
    )
    await app.ask("Read this report identifier from my own library.")
    evidence = review_payload(app)["evidence"][0]
    assert evidence["observation"] == {
        "status": "empty",
        "message": "Report not found in your library.",
    }
    captured = json.dumps(app.model.requests + app.reviewer_model.requests)
    assert "Private title" not in captured and "Private content." not in captured
