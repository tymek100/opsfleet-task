"""Opt-in local Phoenix registry check; no model or warehouse calls."""

import pytest
from phoenix.client import Client

from evaluation.prompt_catalog import judge_prompt
from evaluation.settings import EvaluationSettings
from retail_insight.integrations.phoenix.prompts import phoenix_version, sync_prompts
from retail_insight.runtime.prompts import analyst_prompt, reviewer_prompt

pytestmark = [pytest.mark.phoenix, pytest.mark.enable_socket]


def test_registry_round_trip_and_idempotent_publication(settings, phoenix_url):
    specs = [analyst_prompt(settings), reviewer_prompt(settings)] + [
        judge_prompt(EvaluationSettings(), kind) for kind in ("answer", "trajectory")
    ]
    references = sync_prompts(specs, phoenix_url)
    assert sync_prompts(specs, phoenix_url) == references
    client = Client(base_url=phoenix_url)
    for spec, reference in zip(specs, references, strict=True):
        stored = client.prompts.get(prompt_version_id=reference["version_id"])
        assert stored.metadata["sha256"] == spec.sha256
        variables = {"context": '{"question":"Which quarter?"}'}
        assert stored.format(variables=variables, sdk="google_genai") == phoenix_version(
            spec
        ).format(variables=variables, sdk="google_genai")
