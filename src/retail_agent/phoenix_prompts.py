"""Publish repository prompts to local Phoenix without changing inference inputs."""

import time
from collections.abc import Sequence
from urllib.parse import urlparse

import httpx
from google.genai import types

from retail_agent.prompt_catalog import PromptSpec


def phoenix_version(spec: PromptSpec):
    from phoenix.client.types.prompts import PromptVersion

    return PromptVersion.from_google_genai(
        spec.model,
        [types.Content(role="user", parts=[types.Part(text="{{context}}")])],
        config=spec.config.model_copy(update={"system_instruction": spec.instruction}),
        template_format="MUSTACHE",
        description=spec.description,
        metadata={"source": "repository", "sha256": spec.sha256, "files": list(spec.sources)},
    )


def _sync(specs: Sequence[PromptSpec], client) -> list[dict]:
    published = []
    for spec in specs:
        desired = phoenix_version(spec)
        tag = "code-" + spec.sha256
        try:
            version = client.prompts.get(prompt_identifier=spec.name, tag=tag)
        except ValueError as exc:
            if not str(exc).startswith("Prompt not found:"):
                raise
            version = client.prompts.create(
                name=spec.name,
                version=desired,
                prompt_description=spec.description,
                prompt_metadata={"source": "repository", "files": list(spec.sources)},
            )
        # Tags are mutable in Phoenix. Verify the actual stored definition before
        # attributing an execution to it, rather than trusting its claimed hash.
        variables = {"context": "{{context}}"}
        if version.format(variables=variables, sdk="google_genai") != desired.format(
            variables=variables, sdk="google_genai"
        ):
            raise ValueError(f"Phoenix prompt differs from repository version: {spec.name}")
        if not version.id:
            raise ValueError("Phoenix did not return a prompt version ID")
        client.prompts.tags.create(prompt_version_id=version.id, name=tag)
        client.prompts.tags.create(
            prompt_version_id=version.id,
            name="repository",
            description="Most recently synchronized repository definition; not a deployment tag.",
        )
        published.append(
            {
                "name": spec.name,
                "sha256": spec.sha256,
                "version_id": version.id,
                "sources": list(spec.sources),
            }
        )
    return published


def sync_prompts(
    specs: Sequence[PromptSpec],
    endpoint: str = "http://127.0.0.1:6006",
    *,
    deadline: float | None = None,
) -> list[dict]:
    """Synchronize static templates only; no user data, secrets or model calls."""
    from phoenix.client import Client

    parsed = urlparse(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Prompt publication requires a localhost Phoenix endpoint")
    deadline = min(deadline, time.monotonic() + 20) if deadline else time.monotonic() + 20

    def cap_timeout(request: httpx.Request) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Prompt synchronization deadline exhausted")
        request.extensions["timeout"] = httpx.Timeout(min(3, remaining)).as_dict()

    with httpx.Client(
        base_url=endpoint,
        timeout=3,
        follow_redirects=False,
        trust_env=False,
        event_hooks={"request": [cap_timeout]},
    ) as http_client:
        return _sync(specs, Client(base_url=endpoint, http_client=http_client))
