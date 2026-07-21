"""Explicit benchmark selections must never be silently narrowed."""

from pathlib import Path

import pytest

from lexstab.artifacts import find_repo_root
from lexstab.config import load_run_config
from lexstab.freeze import FrozenBenchmark
from lexstab.matrix import MatrixSelectionError, expand_matrix, select_cases

ROOT = find_repo_root(Path(__file__))
BENCH = FrozenBenchmark(ROOT, ROOT / "dataset/manifests/benchmark-v0.2.0.json")


def _config():
    return load_run_config(ROOT / "config/run.v0.2-provider-check.yaml")


def test_explicit_case_outside_split_fails_instead_of_disappearing():
    config = _config()
    config.selection["case_ids"] = ["ESCALATE_001", "RMI_001"]
    with pytest.raises(MatrixSelectionError, match="outside the selected 'development' split"):
        select_cases(BENCH, config)


def test_explicit_request_outside_selected_cases_fails():
    config = _config()
    config.selection["case_ids"] = ["ESCALATE_001"]
    config.selection["request_ids"] = ["REQ-RMI-001-0004"]
    with pytest.raises(MatrixSelectionError, match="outside the selected case slice"):
        expand_matrix(BENCH, config)


def test_validation_rmi_config_selects_every_explicit_request():
    config = load_run_config(ROOT / "config/run.v0.2-rmi-check.yaml")
    matrix = expand_matrix(BENCH, config)
    selected = {cell.request_id for cell in matrix.cells if cell.request_id}
    assert set(config.selection["request_ids"]) <= selected
    assert {cell.case_id for cell in matrix.cells} == {"RMI_001", "CLOSE_001"}


def test_persistence_intent_modes_can_restrict_lp1_to_gold():
    config = _config()
    formal = config.tracks["progressive_formalization"]
    formal["enabled"] = True
    formal["conditions"] = []
    formal["persistence_conditions"] = ["LP1_CANONICAL_ONCE"]
    formal["persistence_intent_modes"] = {"LP1_CANONICAL_ONCE": ["gold"]}
    formal["run_cumulative_ladder"] = False
    formal["run_component_ablations"] = False
    formal["run_language_persistence_ablation"] = True
    for track_name, track in config.tracks.items():
        if track_name != "progressive_formalization":
            track["enabled"] = False

    matrix = expand_matrix(BENCH, config)
    cells = [
        cell for cell in matrix.cells
        if cell.architecture == "LP1_CANONICAL_ONCE"
    ]
    assert cells
    assert {cell.intent_mode for cell in cells} == {"gold"}
