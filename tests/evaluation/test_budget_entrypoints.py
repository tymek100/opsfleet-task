"""Standalone command entry points cannot bypass the evaluation spending policy."""

import importlib

import pytest

from retail_insight.config import Settings


@pytest.mark.parametrize(
    "module, extra",
    [
        ("evaluation.multi_agent.__main__", []),
        ("evaluation.runners.manual", ["--backend", "fixture", "--deadline-seconds", "30"]),
        ("evaluation.multi_agent.calibration_candidate", []),
    ],
)
@pytest.mark.parametrize("cap", ["5.01", "40", "nan", "inf", "0"])
def test_module_budget_validation_precedes_execution(module, extra, cap, monkeypatch):
    def forbidden():
        raise AssertionError("No credentials should be loaded for rejected budgets")

    monkeypatch.setattr(Settings, "load", forbidden)
    monkeypatch.setattr("sys.argv", [module, *extra, "--max-cost-usd", cap])
    with pytest.raises(SystemExit) as exc:
        importlib.import_module(module).main()
    assert exc.value.code == 2
