"""Blocking threshold checks for scheduled regression runs."""

from lexstab.artifacts import json_read, json_write
from lexstab.regression import check_run_thresholds


def _interval(estimate: float, low: float | None = None, high: float | None = None) -> dict:
    return {
        "estimate": estimate,
        "ci_low": estimate if low is None else low,
        "ci_high": estimate if high is None else high,
        "n_cases": 10,
        "n_observations": 10,
    }


def _write_run(run_dir, candidate_low: float) -> None:
    run_dir.mkdir()
    json_write(run_dir / "run-manifest.json", {
        "run_id": "threshold-test",
        "mocked": False,
        "baseline_eligible": True,
    })
    baseline = {
        "track": "boundary",
        "architecture": "A1_DIRECT_CLARIFY",
        "schema_validity": _interval(1.0),
        "full_call_accuracy": _interval(0.95, 0.90, 1.0),
        "final_state_accuracy": _interval(0.95, 0.90, 1.0),
        "operational_invariance": _interval(0.95, 0.90, 1.0),
        "contrast_accuracy": _interval(0.95, 0.90, 1.0),
        "false_action_rate": 0.0,
        "false_action_interval": _interval(0.0),
        "clarification": {"unnecessary_clarification_rate": 0.0},
        "unnecessary_clarification_interval": _interval(0.0),
    }
    candidate = {
        **baseline,
        "architecture": "B_RUNTIME",
        "full_call_accuracy": _interval(0.95, candidate_low, 1.0),
        "final_state_accuracy": _interval(0.95, candidate_low, 1.0),
        "operational_invariance": _interval(0.95, candidate_low, 1.0),
        "contrast_accuracy": _interval(0.95, candidate_low, 1.0),
    }
    json_write(run_dir / "metrics.json", {
        "run_id": "threshold-test",
        "baseline_eligible": True,
        "completion": {"completion_rate": 1.0},
        "missing_cells": [],
        "headline": [baseline, candidate],
        "component_ablations": [],
        "elicitation": {},
    })


def test_threshold_check_rejects_observed_provider_failure(tmp_path):
    run_dir = tmp_path / "provider-failure"
    _write_run(run_dir, candidate_low=0.90)
    document = json_read(run_dir / "metrics.json")
    document["baseline_eligible"] = False
    json_write(run_dir / "metrics.json", document)
    report = check_run_thresholds(run_dir, {"blocking": {}})
    assert report["passed"] is False
    assert "run is mocked or baseline-ineligible" in report["failures"]


def test_threshold_check_uses_conservative_interval_bound(tmp_path):
    thresholds = {
        "baseline_architecture": "A1_DIRECT_CLARIFY",
        "blocking": {
            "require_case_clustered_interval": True,
            "block_on_missing_cells": True,
        },
        "gates": {
            "schema_validity": {"minimum": 0.99},
            "full_call_accuracy": {"maximum_drop_from_baseline": 0.06},
            "final_state_accuracy": {"maximum_drop_from_baseline": 0.06},
            "operational_invariance": {"maximum_drop_from_baseline": 0.06},
            "contrast_accuracy": {"maximum_drop_from_baseline": 0.06},
            "false_action_rate": {"maximum": 0.0},
            "unnecessary_clarification_rate": {"maximum": 0.05},
        },
    }
    passing = tmp_path / "passing"
    _write_run(passing, candidate_low=0.90)
    assert check_run_thresholds(passing, thresholds)["passed"] is True

    failing = tmp_path / "failing"
    _write_run(failing, candidate_low=0.80)
    report = check_run_thresholds(failing, thresholds)
    assert report["passed"] is False
    assert any("conservative drop" in failure for failure in report["failures"])
