"""The publication gate requires a complete, internally consistent review."""

import json

import pytest
from pydantic import ValidationError

from retail_agent.contracts import Review
from tests.support.models import verdict


def valid_review():
    content = verdict()
    assert content.parts and content.parts[0].text
    return json.loads(content.parts[0].text)


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "failed", "issue", "string_bool", "extra"]
)
def test_approval_cannot_hide_missing_failed_or_invalid_findings(mutation):
    value = valid_review()
    if mutation == "missing":
        value["checks"].pop()
    elif mutation == "duplicate":
        value["checks"][-1] = value["checks"][0]
    elif mutation == "failed":
        value["checks"][0]["passed"] = False
    elif mutation == "issue":
        value["issues"] = [{"category": "grounding", "message": "Unsupported cause."}]
    elif mutation == "string_bool":
        value["checks"][0]["passed"] = "true"
    else:
        value["hidden_override"] = True
    with pytest.raises(ValidationError):
        Review.model_validate(value)


def test_complete_review_is_valid_and_model_schema_requires_all_categories():
    result = Review.model_validate(valid_review())
    assert result.decision == "approve"
    assert len(result.checks) == 5
    schema = Review.response_schema()
    assert set(schema["required"]) == {"checks", "issues", "save_authorized", "decision"}
    assert (
        schema["properties"]["checks"]["minItems"]
        == schema["properties"]["checks"]["maxItems"]
        == 5
    )
