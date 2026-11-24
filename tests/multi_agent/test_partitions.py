"""Alternative presentation cannot excuse wrong counts or fabricated quoted sums."""

import pytest

from evaluation.multi_agent.build_fixture import build
from evaluation.multi_agent.oracle import Snapshot, reference
from evaluation.multi_agent.partitions import (
    extraction_reference,
    groups,
    numeric_partition_scores,
    with_partitions,
)
from evaluation.multi_agent.scenarios import load_suites
from evaluation.results import ExtractedFact, Judgment


def setup():
    snapshot = Snapshot(build())
    base = reference(snapshot, load_suites()["coordinator"][2], 1)
    ref = with_partitions(snapshot, "alice", base)
    group = groups(ref)[0]
    return base, ref, group


def judgment(ref, group, *, total=None, parts=("3", "3")):
    facts = [
        ExtractedFact(id=f.id, value=f.value, span=f"{f.entity}: {f.value}")
        for f in ref.facts
        if f.id != group["target_id"]
    ]
    if total is not None:
        facts.append(
            ExtractedFact(
                id=group["target_id"],
                value=total,
                span=f"All unknown assignments combined: {total}",
            )
        )
    for part, value in zip(group["components"], parts, strict=False):
        facts.append(ExtractedFact(id=part["id"], value=value, span=f"{part['entity']}: {value}"))
    return Judgment(
        facts=facts, claims=[], criteria=[], response_kind="substantive", coverage_complete=True
    )


def target_score(ref, group, result):
    return next(
        s for s in numeric_partition_scores(ref, result) if s.criterion_id == group["target_id"]
    )


def test_split_components_are_verified_without_requiring_a_printed_sum():
    base, ref, group = setup()
    assert len(ref.facts) == len(base.facts)
    assert len(extraction_reference(ref).facts) == len(base.facts) + 2
    assert target_score(ref, group, judgment(ref, group)).status == "PASS"
    assert target_score(ref, group, judgment(ref, group, total="6", parts=())).status == "PASS"


def test_wrong_missing_or_contradictory_partitions_fail():
    _, ref, group = setup()
    for result in (
        judgment(ref, group, parts=("3", "2")),
        judgment(ref, group, parts=("3",)),
        judgment(ref, group, total="5"),
    ):
        assert target_score(ref, group, result).status == "FAIL"
    scores = numeric_partition_scores(ref, judgment(ref, group, total="6", parts=("3", "2")))
    assert any(s.name == "numeric_partition_component" and s.status == "FAIL" for s in scores)


def test_product_partition_preserves_entity_binding():
    snapshot = Snapshot(build())
    base = reference(snapshot, load_suites()["coordinator"][4], 1)
    ref = with_partitions(snapshot, "alice", base)
    assert len(groups(ref)) == 3
    assert [g["components"][0]["value"] for g in groups(ref)] == ["1", "1", "1"]
    assert all("product 710" in p["entity"] for p in groups(ref)[0]["components"])


def test_distinct_product_counts_are_never_summed_across_unknown_centers():
    snapshot = Snapshot(build())
    base = reference(snapshot, load_suites()["coordinator"][11], 1)
    assert not groups(with_partitions(snapshot, "alice", base))


def test_null_partition_reference_fails_validation_instead_of_becoming_zero():
    _, ref, group = setup()
    result = judgment(ref, group)
    group["components"][0]["value"] = None
    group["components"][0]["value_type"] = "null"
    with pytest.raises(ValueError, match="non-null"):
        numeric_partition_scores(ref, result)
