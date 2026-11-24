"""Explicit attribution for schema and skill observations without business evidence IDs."""

from copy import deepcopy


def bind_observations(observations):
    """Assign one local source ID per actual captured observation, preserving payloads.

    Names alone are not identifiers: two describe_data calls can expose different
    scopes or schemas. The ordered O namespace points to a concrete occurrence.
    """
    bound = deepcopy(observations)

    def identifiers(value):
        if isinstance(value, list):
            return set().union(*(identifiers(v) for v in value)) if value else set()
        if not isinstance(value, dict):
            return set()
        found = {
            value[key]
            for key in ("id", "evidence_id", "observation_source_id")
            if isinstance(value.get(key), str)
        }
        for key, child in value.items():
            if key != "rows":
                found.update(identifiers(child))
        return found

    used = identifiers(bound)
    index = 1
    for item in bound:
        while f"O{index}" in used:
            index += 1
        identifier = f"O{index}"
        item["observation_source_id"] = identifier
        used.add(identifier)
        index += 1
    return bound
