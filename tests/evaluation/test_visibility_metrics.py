"""Grounding visibility, missing-denominator accounting, and calibration sentinel diagnostics."""

import json

from evaluation.graders.calibration import calibration_metrics, score_saved_controls
from evaluation.graders.checks import grounding_scores
from evaluation.graders.judge import observed_context
from evaluation.models import Case, TurnReference
from evaluation.reporting.summary import summarize
from evaluation.results import Claim, Judgment, Score, Trial, TrialGrade, TurnGrade, TurnRecord
from evaluation.runners.artifacts import read_json, write_json


def judgment(text="Revenue was 9.", label="SUPPORTED", kind="substantive"):
    return Judgment.model_validate(
        {
            "facts": [],
            "claims": [
                {
                    "span": text,
                    "label": label,
                    "evidence_ids": ["E1"] if kind == "substantive" else [],
                    "reason": "Control",
                }
            ],
            "criteria": [],
            "response_kind": kind,
            "coverage_complete": True,
        }
    )


def test_raw_prior_observations_cannot_ground_forgotten_followup_rows():
    old = [{"result": {"id": "E1", "rows": [{"revenue": 9, "unretained": "hidden-row-canary"}]}}]
    turn = TurnRecord(
        step_id="followup",
        status="approved",
        markdown="Revenue was 9.",
        context={
            "prior_approved_conversation": [
                {"markdown": "A result is available.", "evidence_ids": ["E1"]}
            ]
        },
    )
    payload = observed_context(turn, old)
    assert "hidden-row-canary" not in json.dumps(payload)
    assert payload["visible_tool_observations"] == []
    assert payload["initial_context"] == turn.context
    # The ID can remain in history; the forgotten row itself is never sent to the judge.
    assert grounding_scores(turn, judgment(), old)[0].status != "ERROR"
    turn.context = {}
    assert grounding_scores(turn, judgment(), old)[0].status == "ERROR"


def test_reread_prior_result_is_visible_in_current_tool_observation():
    reread = {"result": {"id": "E1", "rows": [{"revenue": 9}]}}
    turn = TurnRecord(step_id="followup", status="approved", observations=[reread])
    assert observed_context(turn, [])["visible_tool_observations"] == [reread]
    assert grounding_scores(turn, judgment(), [])[0].status == "PASS"


def test_summary_keeps_missing_judgments_and_unreviewed_candidates_out_of_success_rates():
    cases, trials, grades = [], [], []
    definitions = [
        ("correct", "answerable", "PASS", judgment()),
        ("refusal", "answerable", "FAIL", judgment("I cannot answer.", "NOT_FACTUAL", "refusal")),
        ("unknown", "answerable", "ERROR", None),
        ("wrong", "answerable", "FAIL", judgment(label="CONTRADICTED")),
        ("denied", "access_denied", "PASS", judgment("Access denied.", "NOT_FACTUAL", "refusal")),
    ]
    for name, answerability, status, judged in definitions:
        reference = TurnReference.model_validate(
            {
                "reference_answer": "Control",
                "answerability": answerability,
                "allowed_outcomes": ["refusal" if answerability == "access_denied" else "answer"],
            }
        )
        cases.append(
            Case.model_construct(id=name, family="contract", references={"ask": reference})
        )
        turn = TurnRecord(step_id="ask", status="approved", observations=[{"result": {"id": "E1"}}])
        trials.append(Trial(id=name, case_id=name, repetition=1, status="completed", turns=[turn]))
        scores = (
            grounding_scores(turn, judged, [])
            if judged
            else [Score(name="independent_judgment", status="ERROR", finding="Missing")]
        )
        if status == "FAIL":
            scores.append(Score(name="response_kind", status="FAIL", finding="Control"))
        candidates = (
            [
                {"status": "FAIL", "review_decision": None},
                {"status": "FAIL", "review_decision": "approve"},
            ]
            if name == "wrong"
            else []
        )
        grades.append(
            TrialGrade.model_validate(
                {
                    "trial_id": name,
                    "case_id": name,
                    "repetition": 1,
                    "status": status,
                    "turns": [
                        TurnGrade(
                            step_id="ask",
                            status=status,
                            scores=scores,
                            judgment=judged,
                            candidate_grades=candidates,
                        ).model_dump()
                    ],
                }
            )
        )
    manifest = {
        "id": "run",
        "planned_trials": 5,
        "repetitions": 1,
        "case_ids": [c.id for c in cases],
        "completed_trials": 5,
        "accounted_usd": 1,
    }
    result = summarize(manifest, trials, grades, {"id": "grade"}, cases)
    metrics = result["answerability"]
    assert metrics["useful_answer_coverage"]["value"] == 1 / 4
    assert metrics["unnecessary_abstention"]["value"] == 1 / 3
    assert metrics["material_error_among_substantive"]["value"] == 1 / 2
    assert metrics["answer_level_grading_coverage"]["value"] == 4 / 5
    assert metrics["unresolved_turns"] == 1
    assert result["affected_answer_rate"]["value"] == 1 / 2
    assert result["reviewer_false_accepts"]["denominator"] == 1
    assert result["reviewer_false_accepts"]["value"] == 1
    assert result["reviewer_candidates_without_decision"] == 1
    assert result["claim_extraction_recall"]["status"] == "NOT_MEASURED"


def control():
    return {
        "id": "cause",
        "expected_pass": False,
        "question": "Why did revenue rise?",
        "answer": "Revenue rose. Demand caused it.",
        "evidence": [{"id": "E1", "rows": [{"revenue_change": 9}]}],
        "reference": TurnReference(reference_answer="Revenue rose; cause unknown.").model_dump(
            mode="json"
        ),
        "expected_claims": [
            {"span": "Revenue rose.", "label": "SUPPORTED"},
            {"span": "Demand caused it.", "label": "UNSUPPORTED"},
        ],
    }


def test_calibration_detects_missing_claim_despite_correct_overall_failure():
    item = control()
    partial = judgment("Revenue rose.")
    # A semantic task failure alone does not establish that the causal claim was extracted.
    result = calibration_metrics(
        [item], [{"id": "cause", "actual": "FAIL", "judgment": partial.model_dump(mode="json")}]
    )
    assert result["synthetic_expected_claim_coverage"]["value"] == 1 / 2
    assert result["control_details"][0]["claim_checks"][1]["label_detected"] is False
    assert result["claim_extraction_recall"]["status"] == "NOT_MEASURED"
    unknown = calibration_metrics([item], [{"id": "cause", "actual": "ERROR"}])
    assert unknown["resolved_control_coverage"]["value"] == 0
    assert unknown["synthetic_expected_claim_coverage"]["value"] == 0


def test_saved_calibration_rescoring_is_versioned_and_preserves_original_files(tmp_path):
    item = control()
    parsed = judgment("Revenue rose.")
    parsed.claims.append(
        Claim(span="Demand caused it.", label="UNSUPPORTED", reason="No cause observed")
    )
    write_json(
        tmp_path / "controls.json",
        [{"id": "cause", "actual": "FAIL", "judgment": parsed.model_dump(mode="json")}],
    )
    write_json(tmp_path / "summary.json", {"original": True, "accounted_judge_usd": 0.25})
    before = (tmp_path / "summary.json").read_bytes()
    target = score_saved_controls(tmp_path, [item])
    summary = read_json(target / "summary.json")
    assert summary["confusion"] == {"FAIL_as_FAIL": 1}
    assert summary["synthetic_expected_claim_coverage"]["value"] == 1
    assert read_json(target / "manifest.json")["model_calls"] == 0
    assert (tmp_path / "summary.json").read_bytes() == before
    assert (target / "reference_controls.json").exists()


def test_visible_judge_response_is_sanitized_and_bounded():
    from evaluation.graders.judge import MAX_VISIBLE_RESPONSE_BYTES, visible_response_record

    payload = json.dumps(
        {
            "api_key": "field-secret",
            "text": "provider-key /confirm deletion-secret",
            "parts": [{"thought": True, "text": "hidden-thought"}],
        }
    )
    record = visible_response_record(payload, ("provider-key",))
    assert all(
        secret not in record["visible_response"]
        for secret in ["field-secret", "provider-key", "deletion-secret", "hidden-thought"]
    )
    oversized = visible_response_record("界" * MAX_VISIBLE_RESPONSE_BYTES, ())
    assert oversized["visible_response_truncated"] is True
    assert len(oversized["visible_response"].encode()) <= MAX_VISIBLE_RESPONSE_BYTES


async def test_markdown_span_mismatch_remains_error_with_a_specific_diagnostic():
    import pytest
    from google.genai import types

    from evaluation.graders.judge import GeminiJudge, JudgeUnavailable
    from evaluation.settings import EvaluationSettings
    from tests.evaluation.test_judge_budget import Client

    payload = judgment("Revenue was 9.").model_dump(mode="json")
    payload["claims"][0]["reason"] = "provider-key"
    client = Client(
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        parts=[
                            types.Part(text="hidden-thought", thought=True),
                            types.Part(text=json.dumps(payload)),
                        ]
                    )
                )
            ]
        )
    )
    judge = GeminiJudge(
        "provider-key", EvaluationSettings(), max_cost_usd=1, deadline_seconds=10, client=client
    )
    turn = TurnRecord(step_id="ask", status="approved", markdown="Revenue was **9**.")
    with pytest.raises(JudgeUnavailable, match=r"claims\[0\].span"):
        await judge.evaluate(turn, TurnReference(reference_answer="Revenue was **9**."), [])
    record = judge.calls[0]
    assert record["error_stage"] == "attribution"
    assert "Revenue was 9." in record["visible_response"]
    assert "provider-key" not in json.dumps(record) and "hidden-thought" not in json.dumps(record)


def test_dynamic_schema_enumerates_original_markdown_and_known_identifiers():
    import pytest

    from evaluation.graders.judge import (
        response_schema,
        source_catalog,
        source_excerpts,
        validate_judgment,
    )
    from evaluation.models import Criterion, Fact

    markdown = "## Results\n\n* **Q4 Revenue:** 570.00\n* **Q1 Revenue:** 798.00"
    turn = TurnRecord(step_id="ask", status="approved", markdown=markdown)
    reference = TurnReference(
        reference_answer=markdown,
        facts=[Fact(id="q4", value="570", source_key="q4", metric="revenue")],
        criteria=[Criterion(id="scope", kind="semantic", description="Preserve scope")],
    )
    schema = response_schema(turn, reference)
    choices = source_excerpts(markdown)
    ids = list(source_catalog(markdown))
    assert "* **Q4 Revenue:** 570.00" in choices
    assert "Q4 Revenue: 570.00" not in choices
    assert all(choice in markdown for choice in choices)
    for key in ("ExtractedFact", "Claim"):
        assert schema["$defs"][key]["properties"]["span"]["enum"] == ids
    assert schema["$defs"]["ExtractedFact"]["properties"]["id"]["enum"] == ["q4"]
    assert schema["$defs"]["CriterionFinding"]["properties"]["id"]["enum"] == ["scope"]
    assert schema["$defs"]["CriterionFinding"]["properties"]["spans"]["items"]["enum"] == ids
    forged = judgment("Q4 Revenue: 570.00")
    with pytest.raises(ValueError, match="fabricated"):
        validate_judgment(
            forged, turn, TurnReference(reference_answer=markdown), allowed_excerpts=set(choices)
        )


async def test_dynamic_schema_bytes_are_included_in_judge_cost_reservation():
    from google.genai import types

    from evaluation.graders.judge import PROMPT_PATH, GeminiJudge, judge_input, response_schema
    from evaluation.settings import EvaluationSettings
    from tests.evaluation.test_judge_budget import Client

    markdown = "* **Revenue:** 798.00\n* **Orders:** 20"
    turn = TurnRecord(step_id="ask", status="approved", markdown=markdown)
    reference = TurnReference(reference_answer=markdown)
    payload = judgment("s1").model_dump(mode="json")
    client = Client(
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(content=types.Content(parts=[types.Part(text=json.dumps(payload))]))
            ]
        )
    )
    settings = EvaluationSettings()
    judge = GeminiJudge(
        "provider-key", settings, max_cost_usd=1, deadline_seconds=10, client=client
    )
    resolved = await judge.evaluate(turn, reference, [])
    assert resolved.claims[0].span == "* **Revenue:** 798.00"
    assert judge.calls[0]["resolved_judgment"]["claims"][0]["span"] == "* **Revenue:** 798.00"
    dynamic = response_schema(turn, reference)
    expected_bytes = (
        len(
            (
                json.dumps(judge_input(turn, reference, []), ensure_ascii=False)
                + PROMPT_PATH.read_text()
                + json.dumps(dynamic, ensure_ascii=False)
            ).encode()
        )
        + 1024
    )
    assert judge.calls[0]["admitted_input_bytes"] == expected_bytes
    assert client.requests[0]["config"].response_json_schema == dynamic
    assert (
        judge.calls[0]["accounted_usd"]
        == (
            expected_bytes * settings.input_usd_per_million
            + settings.judge_max_output_tokens * settings.output_usd_per_million
        )
        / 1e6
    )


def test_unlisted_source_id_cannot_be_hydrated_to_fabricated_evidence():
    import pytest

    from evaluation.graders.judge import resolve_source_ids

    turn = TurnRecord(step_id="ask", status="approved", markdown="Revenue was 9.")
    with pytest.raises(ValueError, match="unknown source ID"):
        resolve_source_ids(judgment("s999"), turn)
    with pytest.raises(ValueError, match="unknown source ID"):
        resolve_source_ids(judgment("Revenue was 9."), turn)
    assert resolve_source_ids(judgment("s1"), turn).claims[0].span == turn.markdown


async def test_provider_error_diagnostics_are_bounded_and_redact_known_credentials():
    import pytest
    from google.genai import errors

    from evaluation.graders.judge import GeminiJudge, JudgeUnavailable
    from evaluation.settings import EvaluationSettings
    from tests.evaluation.test_judge_budget import Client, records

    client = Client(
        errors.ClientError(
            400, {"error": {"message": "provider-key " + "schema too complex " * 200}}
        )
    )
    judge = GeminiJudge(
        "provider-key", EvaluationSettings(), max_cost_usd=1, deadline_seconds=10, client=client
    )
    turn, reference = records()
    with pytest.raises(JudgeUnavailable, match="code 400"):
        await judge.evaluate(turn, reference, [])
    record = judge.calls[0]
    assert record["provider_code"] == 400 and record["error_stage"] == "provider"
    assert "schema too complex" in record["provider_message"]
    assert "provider-key" not in json.dumps(record)
    assert len(record["provider_message"].encode()) <= 1024
