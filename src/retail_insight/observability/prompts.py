"""Freeze local prompt definitions; hashes correlate them with Foundry spans.

This is a local artifact, not a hosted prompt registry or a remote instruction source.
"""

import time


def sync_prompts(specs, endpoint=None, *, deadline=None, client=None):
    references = []
    for spec in specs:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Prompt capture deadline reached")
        references.append(
            {
                "name": spec.name,
                "sha256": spec.sha256,
                "version_id": spec.sha256,
                "instruction": spec.instruction,
            }
        )
    return references
