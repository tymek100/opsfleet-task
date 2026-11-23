"""Prompt publication, SDK round trips and immutable execution attribution."""

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from evaluation.prompt_catalog import judge_prompt
from evaluation.settings import EvaluationSettings
from retail_agent.observability import configure_tracing, prompt_attributes
from retail_agent.phoenix_prompts import _sync, phoenix_version, sync_prompts
from retail_agent.prompt_catalog import analyst_prompt, reviewer_prompt
from tests.support.models import finish, verdict


class Registry:
    def __init__(self):
        self.versions = {}
        self.names = {}
        self.tagged = {}
        self.tags = SimpleNamespace(create=self.tag)

    def get(self, *, prompt_identifier, tag):
        version_id = self.tagged.get((prompt_identifier, tag))
        if not version_id:
            raise ValueError(f"Prompt not found: {prompt_identifier}")
        return self.versions[version_id]

    def create(self, *, name, version, **kwargs):
        version = copy.deepcopy(version)
        identifier = f"version-{len(self.versions) + 1}"
        version._id = identifier
        self.versions[identifier] = version
        self.names[identifier] = name
        return version

    def tag(self, *, prompt_version_id, name, **kwargs):
        self.tagged[self.names[prompt_version_id], name] = prompt_version_id


def test_four_prompts_round_trip_instructions_model_and_configuration(settings):
    specs = [analyst_prompt(settings), reviewer_prompt(settings)] + [
        judge_prompt(EvaluationSettings(), kind) for kind in ("answer", "trajectory")
    ]
    assert len({spec.name for spec in specs}) == 4
    context = '{"question":"A < B", "quoted":"{{not_a_variable}}"}'
    for spec in specs:
        formatted = phoenix_version(spec).format(variables={"context": context}, sdk="google_genai")
        assert formatted["model"] == spec.model
        assert formatted["config"].system_instruction == spec.instruction
        assert formatted["messages"][0].parts[0].text == context
        config = formatted["config"].model_copy(update={"system_instruction": None})
        assert config == spec.config
        assert "offline-placeholder" not in str(phoenix_version(spec).metadata)
    assert "analytical-review/SKILL.md" in specs[1].sources[1]


def test_repeat_sync_reuses_versions_and_preserves_playground_changes(settings):
    registry = Registry()
    client = SimpleNamespace(prompts=registry)
    spec = reviewer_prompt(settings)
    original = _sync([spec], client)
    assert _sync([spec], client) == original
    assert len(registry.versions) == 1
    edit = registry.create(
        name=spec.name, version=phoenix_version(replace(spec, instruction="UI edit"))
    )
    registry.tag(prompt_version_id=edit.id, name="experimental")
    assert _sync([spec], client) == original
    assert registry.get(prompt_identifier=spec.name, tag="experimental").id == edit.id
    changed = replace(spec, instruction=spec.instruction + "\nAdditional review guidance.")
    next_version = _sync([changed], client)
    assert next_version[0]["version_id"] != original[0]["version_id"]
    assert _sync([changed], client) == next_version
    assert (
        _sync([spec], client) == original
    )  # Reverting the repository reuses its original version.
    assert len(registry.versions) == 3


def test_hash_changes_for_model_settings_and_review_skill(settings):
    original = reviewer_prompt(settings)
    altered = settings.model_copy(update={"review_thinking_level": "high"})
    assert reviewer_prompt(altered).sha256 != original.sha256
    assert reviewer_prompt(settings, model="another-model").sha256 != original.sha256
    assert (
        reviewer_prompt(settings, guidance={"instructions": "different skill"}).sha256
        != original.sha256
    )


def test_repointed_hash_tag_cannot_misattribute_a_prompt(settings):
    registry = Registry()
    client = SimpleNamespace(prompts=registry)
    spec = analyst_prompt(settings)
    _sync([spec], client)
    altered = registry.create(
        name=spec.name, version=phoenix_version(replace(spec, instruction="UI edit"))
    )
    registry.tag(prompt_version_id=altered.id, name="code-" + spec.sha256)
    with pytest.raises(ValueError, match="differs from repository"):
        _sync([spec], client)


@pytest.mark.parametrize(
    "endpoint",
    ["https://example.com", "http://user:secret@localhost:6006", "http://localhost:6006?token=x"],
)
def test_registry_rejects_nonlocal_or_credential_endpoints(settings, endpoint):
    with pytest.raises(ValueError, match="localhost"):
        sync_prompts([analyst_prompt(settings)], endpoint)


async def test_trace_versions_match_actual_role_and_do_not_leak_after_close(make_agent):
    app = make_agent([finish("Which quarter?", outcome="clarification")], [verdict()])
    specs = [
        analyst_prompt(app.settings, model=app.model.model),
        reviewer_prompt(app.settings, model=app.reviewer_model.model),
    ]
    references = _sync(specs, SimpleNamespace(prompts=Registry()))
    exporter = InMemorySpanExporter()
    tracing = configure_tracing(exporter=exporter)
    try:
        tracing.register_prompts(references)
        result = await app.ask("Summarize our revenue.")
        assert result.status == "approved"
        assert tracing.provider.force_flush(timeout_millis=2000)
        attempts = [s for s in exporter.get_finished_spans() if s.name == "retail.provider_attempt"]
        assert len(attempts) == 2
        for spec, reference in zip(specs, references, strict=True):
            attempt = next(
                s for s in attempts if (s.attributes or {}).get("retail.prompt_name") == spec.name
            )
            assert attempt.attributes is not None
            assert attempt.attributes["prompt.id"] == reference["version_id"]
            assert attempt.attributes["retail.prompt_sha256"] == spec.sha256
        unknown = replace(specs[0], instruction="Modified after synchronization")
        assert "prompt.id" not in prompt_attributes(unknown)
    finally:
        tracing.close()
    assert "prompt.id" not in prompt_attributes(specs[0])


def test_cli_registry_outage_keeps_tracing_and_repository_instructions(settings, monkeypatch):
    from retail_agent import cli

    exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        cli, "configure_tracing", lambda **kwargs: configure_tracing(exporter=exporter)
    )

    def unavailable(*args, **kwargs):
        raise ConnectionError("Controlled registry outage")

    monkeypatch.setattr("retail_agent.phoenix_prompts.sync_prompts", unavailable)
    session = cli._start_tracing(True, settings)
    assert session is not None
    try:
        assert session.prompt_versions == {}
        assert "prompt.id" not in prompt_attributes(analyst_prompt(settings))
    finally:
        session.close()
