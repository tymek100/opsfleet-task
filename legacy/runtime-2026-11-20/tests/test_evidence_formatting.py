"""Formatting repairs must not confuse source labels with fabricated metrics."""

import pytest

from retail_agent.evidence import render_grounded_text
from retail_agent.models import AppError, QueryEvidence


@pytest.fixture
def sources() -> dict[str, QueryEvidence]:
    return {
        "E1": QueryEvidence(
            id="E1",
            sql="",
            purpose="Ranking",
            definitions="Fixture",
            scope="Calvin Klein",
            rows=[{"product_name": "Calvin Klein 3-Pack", "revenue": 15}],
            job_id="fixture",
            sql_hash="fixture",
            bytes_processed=0,
            queried_at="2026-11-19",
        )
    }


def test_list_ordinals_and_exact_product_labels_do_not_trigger_repair(
    sources: dict[str, QueryEvidence],
) -> None:
    text = "1. Calvin Klein 3-Pack generated {{E1.r0.revenue}}. [E1]"
    assert render_grounded_text(text, sources) == "1. Calvin Klein 3-Pack generated 15. [E1]"


def test_grouped_citations_are_normalized_and_still_validate_every_source(
    sources: dict[str, QueryEvidence],
) -> None:
    sources["E2"] = sources["E1"].model_copy(update={"id": "E2"})
    assert render_grounded_text("Both rankings [E1, E2].", sources) == "Both rankings [E1] [E2]."
    with pytest.raises(AppError, match="unavailable evidence"):
        render_grounded_text("Both rankings [E1, E99].", sources)


@pytest.mark.parametrize(
    "text",
    [
        "Revenue was 999. [E1]",
        "1. Revenue was 999. [E1]",
        "Calvin Klein 3-Pack generated 999. [E1]",
        "Calvin Klein 9-Pack generated {{E1.r0.revenue}}. [E1]",
    ],
)
def test_unreferenced_measurements_and_invented_labels_still_fail(
    text: str, sources: dict[str, QueryEvidence]
) -> None:
    with pytest.raises(AppError, match="Unreferenced numeric text") as error:
        render_grounded_text(text, sources)
    assert error.value.code == "answer_grounding"
