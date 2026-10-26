import json

import pytest

from retail_agent.agent import Analyst
from retail_agent.config import Settings
from retail_agent.models import DEMO_USERS, Answer, AppError
from retail_agent.privacy import safe_text, validate_question
from retail_agent.reports import ReportStore
from tests.fixture_data import FixtureExecutor
from tests.test_planning import Provider, analytical_plan


@pytest.mark.parametrize(
    "text",
    [
        "Contact jane.canary@example.test for this report.",
        "Phone: +44 20 7946 0958",
        "Call (415) 555-0123 about the order.",
        "Telephone number is 020 7946 0958",
        "Send it to 42 Oak Road, London.",
        "Customer name: Jane Canary",
        "ZIP code: 90210",
        "Coordinates 51.12345, -0.12345",
        "Contact jane@\u200bexample.test",
        "Show monthly revenue. " * 100 + "Customer name is Jane Canary",
    ],
)
@pytest.mark.asyncio
async def test_contact_input_never_reaches_provider_or_logs(
    text: str, monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    provider = Provider(monkeypatch, [])
    with pytest.raises(AppError) as error:
        await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "privacy").ask(text)
    assert error.value.code == "privacy_input"
    assert str(error.value) == (
        "Please remove personal details; ask using metrics or an internal user_id."
    )
    assert not provider.requests and not store.list("alice")
    log = (settings.data_dir / "events.log").read_text()
    assert text not in log and "Jane Canary" not in log and "example.test" not in log
    failures = [
        json.loads(line) for line in log.splitlines() if json.loads(line)["event"] == "turn_failed"
    ]
    assert failures[-1]["error"] == "privacy_input"
    assert failures[-1]["trace_id"]
    assert "privacy_screening" in log
    assert "[redacted]" in safe_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "Compare Calvin Klein revenue in Q1 2026 with Q2 2026.",
        "Show total spend for customer 1234567890 in 2026.",
        "Compare product 1316 and 23816 for 2026-01-01 through 2026-03-31.",
        "Show Levi's revenue and a target of 1,234,567.89.",
        "What are top customers by revenue?",
        "Autumn review",
    ],
)
def test_retail_numbers_and_brands_are_not_contact_details(text: str) -> None:
    assert validate_question(text) == text
    assert safe_text(text) == text


def test_unlabelled_names_and_nonstandard_addresses_are_documented_limitations() -> None:
    # Deliberately not NER: these inputs are NOT guaranteed to be detected.
    assert validate_question("Jane Doe bought jeans.") == "Jane Doe bought jeans."
    assert (
        validate_question("Deliver to Flat B, The Old Mill.") == "Deliver to Flat B, The Old Mill."
    )


@pytest.mark.parametrize(
    "title", ["Customer name: Jane Canary", "Contact jane@example.test", "Call 415-555-0123"]
)
def test_unsafe_title_is_never_saved(store: ReportStore, answer: Answer, title: str) -> None:
    with pytest.raises(AppError) as error:
        store.save("alice", "private", title, answer)
    assert error.value.code == "privacy_input"
    assert store.list("alice") == []
    assert store.db.execute("SELECT count(*) FROM audit").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_library_titles_do_not_enter_next_model_payload(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore, answer: Answer
) -> None:
    store.save("alice", "legacy", "PRIVATE_CANARY", answer)
    provider = Provider(monkeypatch, [{"route": "reports"}, {"route": "capabilities"}])
    analyst = Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "context")
    await analyst.ask("List my reports")
    await analyst.ask("What can you analyze?")
    assert len(provider.requests) == 2
    assert all(
        "PRIVATE_CANARY" not in r.model_dump_json(exclude={"tools_dict"}) for r in provider.requests
    )


@pytest.mark.asyncio
async def test_analysis_and_save_need_no_local_model(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, store: ReportStore
) -> None:
    provider = Provider(monkeypatch, [analytical_plan()])
    answer = await Analyst(settings, DEMO_USERS["alice"], FixtureExecutor(), store, "no-model").ask(
        "Show revenue for Q1 2026."
    )
    assert answer.quality_status == "validated" and len(provider.requests) == 1
    report_id = store.save("alice", "no-model", "Quarter review", answer)
    assert store.read("alice", report_id).evidence
