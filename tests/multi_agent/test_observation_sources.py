"""Source identity and constrained attribution contracts."""

from evaluation.graders.judge import response_schema
from evaluation.models import TurnReference
from evaluation.multi_agent.grading import turn_record
from evaluation.multi_agent.observation_sources import bind_observations
from evaluation.results import TurnRecord


def test_repeated_tool_names_have_distinct_payload_sources_without_mutation():
    observed = [
        {"event": "tool_observation", "name": "describe_data", "result": {"scope": "A"}},
        {"event": "tool_observation", "name": "describe_data", "result": {"scope": "B"}},
        {"event": "tool_observation", "name": "load_skill", "result": {"name": "analysis"}},
    ]
    bound = bind_observations(observed)
    assert [item["observation_source_id"] for item in bound] == ["O1", "O2", "O3"]
    assert bound == bind_observations(observed)
    assert all("observation_source_id" not in item for item in observed)
    assert bound[0]["result"] == observed[0]["result"]
    turn = TurnRecord(
        step_id="turn-1",
        status="approved",
        markdown="The schema is unavailable.",
        context={"evaluation_source_ids": ["O1", "O2", "O3", "E1"]},
    )
    schema = response_schema(turn, TurnReference(reference_answer="Unknown"))
    allowed = schema["$defs"]["Claim"]["properties"]["evidence_ids"]["items"]["enum"]
    assert allowed == ["E1", "O1", "O2", "O3"]
    assert "describe_data" not in allowed and "analysis" not in allowed


def test_empty_evidence_context_permits_no_invented_reference():
    turn = TurnRecord(step_id="turn-1", status="approved", markdown="Hello.")
    reference = TurnReference(reference_answer="Greeting")
    schema = response_schema(turn, reference)
    turn.context["evaluation_source_ids"] = []
    bounded = response_schema(turn, reference)
    assert bounded["$defs"]["Claim"]["properties"]["evidence_ids"]["maxItems"] == 0
    assert "maxItems" not in schema["$defs"]["Claim"]["properties"]["evidence_ids"]


def test_observation_ids_do_not_collide_with_existing_top_level_ids():
    assert bind_observations([{"id": "O1"}])[0]["observation_source_id"] == "O2"
    assert bind_observations([{"result": {"id": "O1"}}])[0]["observation_source_id"] == "O2"


def test_adapter_catalog_binds_schema_and_skill_observations_without_whitelisting_names():
    raw = {
        "status": "approved",
        "markdown": "Purchase orders are unavailable.",
        "observations": [
            {"event": "tool_observation", "name": "describe_data", "result": {"relations": []}},
            {
                "event": "tool_observation",
                "name": "load_skill",
                "result": {"name": "inventory-analysis"},
            },
        ],
    }
    turn = turn_record(raw, "Show incoming purchase orders.", 1, [])
    assert turn.context["evaluation_source_ids"] == ["O1", "O2"]
    schema = response_schema(turn, TurnReference(reference_answer="Unavailable"))
    assert schema["$defs"]["Claim"]["properties"]["evidence_ids"]["items"]["enum"] == ["O1", "O2"]
