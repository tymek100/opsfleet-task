"""Public facility evidence must survive review without permitting customer geography."""

import datetime as dt
import json
from types import SimpleNamespace

import pytest

from retail_insight.agents.registry import create_agent
from retail_insight.contracts import WORKSPACE_IDENTITY
from retail_insight.integrations.bigquery.domains import DEFAULT_FIXTURE, DomainGateway
from retail_insight.runtime.domain_privacy import facility_coordinates, screen_role_text
from retail_insight.runtime.privacy import screen
from tests.support.models import ScriptedModel, calls, finish, verdict

AS_OF = dt.datetime(2026, 4, 1, tzinfo=dt.UTC)
COORDINATES = "35.1174, -89.9711"
FACILITIES = """SELECT c.center_id, c.center_name, c.center_latitude, c.center_longitude,
  COUNT(s.inventory_id) AS stock_units FROM centers c
  LEFT JOIN stock s ON s.inventory_center_id = c.center_id
  GROUP BY c.center_id, c.center_name, c.center_latitude, c.center_longitude
  ORDER BY c.center_id"""


@pytest.fixture
def facility_gateway(tmp_path):
    fixture = json.loads(DEFAULT_FIXTURE.read_text())
    fixture["distribution_centers"][0].update(latitude=35.1174, longitude=-89.9711)
    path = tmp_path / "facility-fixture.json"
    path.write_text(json.dumps(fixture))
    return DomainGateway(
        "distribution",
        ("Calvin Klein",),
        backend="fixture",
        clock=lambda: AS_OF,
        fixture_path=path,
    )


def evidence(sql=FACILITIES):
    return {
        "sql": sql,
        "rows": [{"center_id": 1, "center_latitude": 35.1174, "center_longitude": -89.9711}],
        "metric_version": "scoped-inventory-v1",
        "scope": "all brands",
        "backend": "fixture",
        "as_of": AS_OF.isoformat(),
        "snapshot_at": None,
        "source_agent": "distribution",
        "source_task_id": "authenticated-child-task",
    }


def runtime_context(role="coordinator", artifact=None):
    return SimpleNamespace(
        role=role,
        results={"E1": evidence() if artifact is None else artifact},
        identity=WORKSPACE_IDENTITY,
        as_of=AS_OF.isoformat(),
        snapshot_at=None,
        settings=SimpleNamespace(backend="fixture"),
    )


@pytest.mark.parametrize(
    "sql",
    [
        FACILITIES,
        "SELECT center_id, center_latitude, center_longitude FROM centers",
    ],
)
def test_direct_facility_columns_authorize_exact_numeric_pair(sql):
    artifact = evidence(sql)
    assert len(facility_coordinates(artifact)) == 1
    assert screen_role_text(COORDINATES, runtime_context(artifact=artifact)) == COORDINATES
    padded = "35.117400, -89.971100"
    assert screen_role_text(padded, runtime_context(artifact=artifact)) == padded


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 AS center_id, 35.1174 AS center_latitude, -89.9711 AS center_longitude",
        "SELECT center_id, 35.1174 AS center_latitude, center_longitude FROM centers",
        "SELECT center_id, center_latitude + 1 AS center_latitude, center_longitude FROM centers",
        "SELECT c.center_id, d.center_latitude, c.center_longitude FROM centers c JOIN centers d ON TRUE",
        "SELECT center_id, center_latitude, center_longitude FROM customer_locations",
        "WITH centers AS (SELECT 1 AS center_id) SELECT center_id, center_latitude, center_longitude FROM centers",
        "SELECT center_id, center_latitude, center_longitude FROM centers UNION ALL SELECT 1, 35.1174, -89.9711",
        "SELECT center_id, center_latitude, center_longitude, 35.1174 AS center_latitude FROM centers",
    ],
)
def test_coordinate_shaped_or_transformed_results_do_not_grant_capability(sql):
    assert not facility_coordinates(evidence(sql))
    with pytest.raises(ValueError):
        screen_role_text(COORDINATES, runtime_context(artifact=evidence(sql)))


@pytest.mark.parametrize(
    "changed",
    [
        {"source_agent": "inventory"},
        {"source_task_id": ""},
        {"metric_version": "arbitrary-result"},
        {"scope": "Levi's"},
        {"backend": "bigquery"},
        {"as_of": "2026-03-01T00:00:00+00:00"},
        {"snapshot_at": "2026-03-01T00:00:00+00:00"},
    ],
)
def test_import_requires_distribution_provenance_and_matching_scope_time(changed):
    with pytest.raises(ValueError):
        screen_role_text(COORDINATES, runtime_context(artifact={**evidence(), **changed}))


@pytest.mark.parametrize("role", ["inventory", "retail"])
def test_other_roles_do_not_gain_facility_exception(role):
    with pytest.raises(ValueError):
        screen_role_text(COORDINATES, runtime_context(role))


@pytest.mark.parametrize(
    "text",
    [
        "Customer location: 35.1234, -89.9876",
        "customer address: 35.1174, -89.9711",
        "Email facility-manager@example.test",
        "Call 312-555-1234",
        "Meet at 123 Main Street",
        "Memphis: 35.1174, -89.9711; customer: 35.1234, -89.9876",
    ],
)
def test_facility_exception_does_not_allow_other_contact_information(text):
    with pytest.raises(ValueError):
        screen_role_text(text, runtime_context())


def test_default_screen_stays_strict():
    with pytest.raises(ValueError):
        screen(COORDINATES)


@pytest.mark.asyncio
async def test_facility_query_survives_analyst_history_reviewer_revision_and_followup(
    settings, facility_gateway
):
    gateway = facility_gateway
    draft = f"Recorded Memphis facility coordinates: {COORDINATES}."
    final = draft + " These are demonstration facility metadata, not customer locations."
    analyst = ScriptedModel(
        script=[
            calls(
                ("query_data", {"sql": FACILITIES, "purpose": "Read public facility coordinates"})
            ),
            finish(draft, ["E1"]),
            finish(final, ["E1"]),
            finish(final, ["E1"]),
        ]
    )
    reviewer = ScriptedModel(script=[verdict("revise"), verdict(), verdict()])
    app = create_agent(
        "distribution",
        settings,
        WORKSPACE_IDENTITY,
        gateway=gateway,
        model=analyst,
        reviewer_model=reviewer,
        as_of=AS_OF.isoformat(),
    )
    try:
        first = await app.ask("Show recorded Memphis facility coordinates.")
        assert first.status == "approved", first.trace
        assert first.answer.markdown == final
        assert len(reviewer.requests) == 2
        assert COORDINATES in json.dumps(analyst.requests[2])
        assert COORDINATES in json.dumps(reviewer.requests[1])
        following = await app.ask("Repeat those recorded facility coordinates.")
        assert following.status == "approved" and following.answer.markdown == final
        assert len(analyst.requests) == 4 and len(reviewer.requests) == 3
    finally:
        app.reports.close()


@pytest.mark.asyncio
async def test_coordinator_imported_facility_evidence_allows_reviewed_prose(
    settings, facility_gateway
):
    gateway = facility_gateway
    observed = await gateway.query(FACILITIES)

    class Specialist:
        async def ask(self, *args, **kwargs):
            return {
                "status": "approved",
                "scope": "all brands",
                "as_of": AS_OF.isoformat(),
                "snapshot_at": None,
                "task_id": "distribution-task",
                "context_id": "distribution-context",
                "markdown": f"Recorded Memphis facility coordinates: {COORDINATES}.",
                "evidence": [{**observed, "id": "E1", "purpose": "Read facility coordinates"}],
                "usage": {"accounted_usd": 0.01},
            }

    answer = (
        f"The recorded Memphis facility coordinates are {COORDINATES}; no live route is available."
    )
    analyst = ScriptedModel(
        script=[
            calls(
                (
                    "delegate",
                    {
                        "agent": "distribution",
                        "question": "Read the facility coordinates",
                        "evidence_ids": [],
                    },
                )
            ),
            finish(answer, ["E1"]),
        ]
    )
    reviewer = ScriptedModel(script=[verdict()])
    app = create_agent(
        "coordinator",
        settings,
        WORKSPACE_IDENTITY,
        gateway=object(),
        client=Specialist(),
        model=analyst,
        reviewer_model=reviewer,
        as_of=AS_OF.isoformat(),
    )
    try:
        result = await app.ask("Find the Memphis facility coordinates without inventing a route.")
        assert result.status == "approved", result.trace
        assert result.answer.markdown == answer
        assert app.results["E1"]["source_agent"] == "distribution"
        assert COORDINATES in json.dumps(analyst.requests[1])
        assert COORDINATES in json.dumps(reviewer.requests[0])
    finally:
        app.reports.close()
