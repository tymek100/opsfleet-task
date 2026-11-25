"""Changing warehouse sources must not reuse fixture answers or saved reports."""

from pathlib import Path

import pytest

from retail_insight.a2a.server import profile_directory


def test_source_profiles_separate_all_persistent_state():
    base = Path("/data")
    profiles = {
        profile_directory(base, "fixture", "fixture-aaa"),
        profile_directory(base, "fixture", "fixture-bbb"),
        profile_directory(base, "bigquery", "bigquery-ccc"),
    }
    assert len(profiles) == 3
    assert all(path.is_relative_to(base) for path in profiles)


@pytest.mark.parametrize("profile", ["../other", "/root", "", "a/b", "a" * 81])
def test_profile_cannot_select_an_arbitrary_data_directory(profile):
    with pytest.raises(ValueError):
        profile_directory(Path("/data"), "fixture", profile)
