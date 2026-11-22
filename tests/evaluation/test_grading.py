"""Defective and valid controls for independent answer grading."""

from decimal import Decimal
from typing import Literal

import pytest

from evaluation.graders.checks import grounding_scores, numeric_scores, value_matches
from evaluation.graders.judge import judge_input, validate_judgment
from evaluation.graders.runner import grade_trial, grade_turn
from evaluation.models import Case, Fact, Step, TurnReference
from evaluation.results import Claim, ExtractedFact, Judgment, Trial, TurnRecord


def reference():
    return TurnReference(
        facts=[
            Fact(
                id="revenue",
                value="932.42",
                source_key="revenue",
                metric="qualifying revenue",
                entity="Outerwear",
                unit="unspecified currency",
                tolerance=Decimal("0.005"),
            )
        ],
        reference_answer="Outerwear revenue was 932.42.",
    )


def answer(value="932.42"):
    text = f"Outerwear revenue was {value}."
    return TurnRecord(
        step_id="ask",
        prompt="What was Outerwear revenue?",
        status="approved",
        markdown=text,
        outcome="answer",
        observations=[
            {"result": {"id": "E1", "rows": [{"category": "Outerwear", "revenue": 932.42}]}}
        ],
    )


def judgment(
    turn,
    *,
    value="932.42",
    label: Literal[
        "SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "NOT_FACTUAL", "UNJUDGEABLE"
    ] = "SUPPORTED",
):
    return Judgment(
        facts=[ExtractedFact(id="revenue", span=turn.markdown, value=value)],
        claims=[Claim(span=turn.markdown, label=label, evidence_ids=["E1"], reason="Control")],
        criteria=[],
        response_kind="substantive",
        coverage_complete=True,
    )


def test_fact_comparison_rejects_number_only_matching_and_wrong_extraction():
    ref = reference()
    turn = answer("383.51")
    assert numeric_scores(ref, judgment(turn, value="383.51"))[0].status == "FAIL"
    # Inventing the correct number in extracted JSON cannot fix a wrong quoted span.
    assert numeric_scores(ref, judgment(turn))[0].status == "FAIL"
    assert numeric_scores(ref, judgment(answer()))[0].status == "PASS"
    assert not value_matches(ref.facts[0], "NaN", "NaN")
    assert not value_matches(ref.facts[0], "932.42", "Product ID 1932.42")


def test_numeric_truth_does_not_establish_grounding():
    turn = answer()
    result = judgment(turn, label="UNSUPPORTED")
    assert numeric_scores(reference(), result)[0].status == "PASS"
    assert grounding_scores(turn, result, [])[0].status == "FAIL"


def test_nonfactual_padding_is_not_a_grounding_success():
    turn = answer()
    result = judgment(turn, label="UNSUPPORTED")
    result.claims.extend(
        [Claim(span="Consider an investigation.", label="NOT_FACTUAL", reason="Advice")] * 30
    )
    score = grounding_scores(turn, result, [])[0]
    assert (score.numerator, score.denominator, score.value) == (0, 1, 0)
    result.claims = result.claims[1:]
    score = grounding_scores(turn, result, [])[0]
    assert score.status == "NOT_APPLICABLE" and score.value is None


def test_unknown_evidence_and_fabricated_spans_are_judge_errors():
    turn = answer()
    result = judgment(turn)
    result.claims[0].evidence_ids = ["E999"]
    assert grounding_scores(turn, result, [])[0].status == "ERROR"
    result.facts[0].span = "This text never appeared."
    with pytest.raises(ValueError, match="fabricated"):
        validate_judgment(result, turn, reference())


def test_expected_fact_values_and_review_decisions_not_sent_to_judge():
    turn = answer("123")
    payload = judge_input(turn, reference(), [])
    assert "932.42" not in str(payload["trusted"])
    assert "runtime_review" not in str(payload)
    assert payload["trusted"]["fact_bindings"][0]["entity"] == "Outerwear"


async def test_code_only_does_not_claim_semantic_success():
    grade = await grade_turn(answer(), reference(), None, [])
    assert grade.status == "UNJUDGEABLE"


async def test_later_correction_does_not_erase_a_wrong_published_turn():
    class Judge:
        async def evaluate(self, turn, ref, prior):
            return judgment(turn, value="383.51" if turn.step_id == "first" else "932.42")

    first = answer("383.51").model_copy(update={"step_id": "first"})
    last = answer().model_copy(update={"step_id": "last"})
    case = Case.model_construct(
        id="conversation",
        identity="alice",
        steps=[Step(id="first", message="First?"), Step(id="last", message="Correct it.")],
        references={"first": reference(), "last": reference()},
        expected_report_count=0,
    )
    trial = Trial(
        id="conversation-r1", case_id=case.id, repetition=1, status="completed", turns=[first, last]
    )
    result = await grade_trial(case, trial, Judge())
    assert [t.status for t in result.turns] == ["FAIL", "PASS"]
    assert result.status == "FAIL"


def test_observed_report_ids_are_valid_sources_but_data_row_ids_are_not():
    turn = answer()
    turn.observations = [
        {"result": {"id": "R1", "markdown": "Historical report."}},
        {"result": {"id": "E1", "rows": [{"id": "E999"}]}},
    ]
    result = judgment(turn)
    result.claims[0].evidence_ids = ["R1"]
    assert grounding_scores(turn, result, [])[0].status == "PASS"
    result.claims[0].evidence_ids = ["E999"]
    assert grounding_scores(turn, result, [])[0].status == "ERROR"
