"""Optional prose must fail closed without changing verified analytical results."""

import json
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from google import genai
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from retail_agent.budget import Budget
from retail_agent.commentary import Commentary, admissible, reviewed_commentary
from retail_agent.config import Settings
from retail_agent.model import BoundedGemini
from retail_agent.models import Answer
from retail_agent.observability import Trace
from retail_agent.quality import metric_catalog


@pytest.mark.parametrize(
    "text,ids",
    [
        ("Revenue was 999 dollars.", ["E1.r0.revenue"]),
        ("Contact canary@example.test.", ["E1.r0.revenue"]),
        ("See https://example.test.", ["E1.r0.revenue"]),
        ("Revenue rose.", ["E99.r0.revenue"]),
        ("Revenue rose.", ["E1.r0.revenue", "E1.r0.revenue"]),
    ],
)
def test_commentary_rejects_unsafe_or_unbound_text(
    answer: Answer, text: str, ids: list[str]
) -> None:
    assert not admissible(Commentary(text=text, metric_ids=ids), metric_catalog(answer.evidence))


@pytest.mark.asyncio
@pytest.mark.parametrize("review_passes", [True, False])
async def test_semantic_review_gates_prose_and_accounts_for_thinking(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, answer: Answer, review_passes: bool
) -> None:
    captured: list[LlmRequest] = []

    async def fake(
        self: Gemini, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        del self, stream
        captured.append(llm_request)
        payload = (
            {
                "text": "Revenue in {{E1.scope}} was {{E1.r0.revenue}}.",
                "metric_ids": ["E1.r0.revenue"],
            }
            if len(captured) == 1
            else {"supported": review_passes, "relevant": True, "safe": True}
        )
        yield LlmResponse(
            content=types.Content(parts=[types.Part(text=json.dumps(payload))]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100,
                candidates_token_count=20,
                thoughts_token_count=80,
                cached_content_token_count=10,
            ),
        )

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    budget, trace = Budget(settings), Trace()
    client = genai.Client(api_key="fake")
    model = BoundedGemini(model="fake", client=client).bind(budget, trace)
    try:
        result = await reviewed_commentary(
            model, budget, trace, answer.text, metric_catalog(answer.evidence), answer.evidence
        )
        assert bool(result) == review_passes
        assert budget.model_calls == 2 and budget.reserved_usd > 0
        assert all(not r.tools_dict for r in captured)
        assert all(r.config.temperature is None for r in captured)
        assert all(
            r.config.thinking_config is not None
            and r.config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
            for r in captured
        )
        assert "Current question" not in captured[0].model_dump_json(exclude={"tools_dict"})
        usages = [e for e in trace.events if e["event"] == "provider_usage"]
        assert len(usages) == 2
        assert sum(int(e["thinking_tokens"] or 0) for e in usages) == 160
        if result:
            assert "Sources: [E1]." in result
            assert "{{" not in result and "Calvin Klein" in result
            parts = captured[1].contents[0].parts
            assert parts is not None
            review_payload = json.loads(parts[0].text or "{}")
            assert "{{" not in review_payload["candidate"]["text"]
    finally:
        await client.aio.aclose()
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["invalid_json", "timeout", "budget"])
async def test_optional_commentary_failure_leaves_findings_available(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, answer: Answer, failure: str
) -> None:
    calls = 0

    async def fake(
        self: Gemini, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        nonlocal calls
        del self, llm_request, stream
        calls += 1
        if failure == "timeout":
            raise TimeoutError()
        yield LlmResponse(content=types.Content(parts=[types.Part(text="not JSON")]))

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    if failure == "budget":
        settings.max_model_calls = 1
    budget, trace = Budget(settings), Trace()
    client = genai.Client(api_key="fake")
    model = BoundedGemini(model="fake", client=client).bind(budget, trace)
    original = answer.model_dump_json()
    try:
        assert (
            await reviewed_commentary(
                model, budget, trace, answer.text, metric_catalog(answer.evidence)
            )
            is None
        )
        assert answer.model_dump_json() == original
        assert calls == (0 if failure == "budget" else 1)
        assert trace.events[-1]["event"] == "commentary_omitted"
    finally:
        await client.aio.aclose()
        client.close()


def test_bound_names_dates_and_values_are_checked_before_substitution(answer: Answer) -> None:
    from retail_agent.commentary import reference_catalog, resolve_references

    answer.evidence[0].rows[0]["state"] = "California"
    catalog = metric_catalog(answer.evidence)
    refs = reference_catalog(answer.evidence, catalog)
    candidate = Commentary(
        text="Revenue in {{E1.r0.state}} was {{E1.r0.revenue}} during {{E1.period}}.",
        metric_ids=["E1.r0.revenue"],
    )
    assert admissible(candidate, catalog, refs)
    rendered = resolve_references(candidate.text, refs)
    assert "California" in rendered and "100.00" in rendered
    assert "01 Jan 2026 to 31 Mar 2026" in rendered
    for invalid in ("{{E9.r0.revenue}}", "{{E1.r9.state}}", "{{E1.r0.revenue}} plus 900"):
        assert not admissible(candidate.model_copy(update={"text": invalid}), catalog, refs)


def test_references_cannot_borrow_an_uncited_row_or_pii(answer: Answer) -> None:
    from retail_agent.commentary import reference_catalog, resolve_references

    e = answer.evidence[0]
    e.rows = [
        {"revenue": 100, "product_name": "[Example]* | Jacket"},
        {"revenue": 20, "product_name": "Other item"},
        {"revenue": 10, "product_name": "canary@example.test"},
    ]
    catalog = metric_catalog([e])
    refs = reference_catalog([e], catalog)
    assert "E1.r2.product_name" not in refs
    borrowed = Commentary(text="{{E1.r1.product_name}}", metric_ids=["E1.r0.revenue"])
    assert not admissible(borrowed, catalog, refs)
    safe = Commentary(text="{{E1.r0.product_name}}", metric_ids=["E1.r0.revenue"])
    assert admissible(safe, catalog, refs)
    assert resolve_references(safe.text, refs, markdown=True) == r"\[Example\]\* \| Jacket"


def test_simple_and_empty_results_do_not_need_extra_model_calls(answer: Answer) -> None:
    from retail_agent.commentary import needs_commentary
    from tests.contracts import contract_for

    intent = contract_for("What was total revenue in Q1 2026?", today=date(2026, 10, 25))
    assert not needs_commentary(answer.evidence, intent)
    assert needs_commentary(answer.evidence, intent, explanation_requested=True)
    answer.evidence[0].rows = [{"revenue": None, "units": 0, "orders": 0}]
    assert not needs_commentary(answer.evidence, intent, explanation_requested=True)
