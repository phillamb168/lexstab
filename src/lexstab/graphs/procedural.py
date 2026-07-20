"""Minimal non-LangGraph procedural runner (spec §18.7; D-008).

Shares the manifest loader, matrix expander, provider adapters, cell runner,
and evaluators with the graph runner. ``compare_runners`` in
``lexstab.graphs.execution`` verifies cell-for-cell equivalence.
"""

from __future__ import annotations

from pathlib import Path

from lexstab.config import RunConfig
from lexstab.run import execute_run
from lexstab.runner import run_cell


def procedural_run(root: Path, run_config: RunConfig, *, run_id: str | None = None,
                   mock_script: dict | None = None) -> Path:
    return execute_run(root, run_config, run_id=run_id, mock_script=mock_script,
                       cell_runner=run_cell)


def graph_run(root: Path, run_config: RunConfig, *, run_id: str | None = None,
              mock_script: dict | None = None) -> Path:
    from lexstab.graphs.execution import graph_run_cell

    return execute_run(root, run_config, run_id=run_id, mock_script=mock_script,
                       cell_runner=graph_run_cell)
