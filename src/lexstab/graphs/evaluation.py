"""Graph C: evaluation and reporting (spec §18.3).

Scores completed run artifacts without invoking the MUT. Node bodies delegate
to :mod:`lexstab.evaluate` and :mod:`lexstab.reporting.report`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from lexstab.artifacts import json_read
from lexstab.evaluate import evaluate_run


class EvaluationState(TypedDict, total=False):
    root: Any
    run_dir: Any
    run_manifest: dict
    metrics: dict
    report_paths: list[str]
    bootstrap_samples: int


def node_load_run_manifest(state: EvaluationState) -> dict:
    manifest = json_read(Path(state["run_dir"]) / "run-manifest.json")
    return {"run_manifest": manifest}


def node_verify_run_artifacts(state: EvaluationState) -> dict:
    run_dir = Path(state["run_dir"])
    required = ["cell-results.jsonl", "matrix.jsonl"]
    missing = [name for name in required if not (run_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"run artifacts missing: {missing}")
    return {}


def node_score_and_aggregate(state: EvaluationState) -> dict:
    metrics = evaluate_run(
        Path(state["root"]), Path(state["run_dir"]),
        bootstrap_samples=state.get("bootstrap_samples"),
    )
    return {"metrics": metrics}


def node_render_reports(state: EvaluationState) -> dict:
    from lexstab.reporting.report import generate_report

    paths = generate_report(Path(state["root"]), Path(state["run_dir"]))
    return {"report_paths": [str(path) for path in paths]}


def build_evaluation_graph(*, include_reports: bool = True):
    graph = StateGraph(EvaluationState)
    graph.add_node("load_run_manifest", node_load_run_manifest)
    graph.add_node("verify_run_artifacts", node_verify_run_artifacts)
    graph.add_node("score_and_aggregate", node_score_and_aggregate)
    graph.add_edge(START, "load_run_manifest")
    graph.add_edge("load_run_manifest", "verify_run_artifacts")
    graph.add_edge("verify_run_artifacts", "score_and_aggregate")
    if include_reports:
        graph.add_node("render_reports", node_render_reports)
        graph.add_edge("score_and_aggregate", "render_reports")
        graph.add_edge("render_reports", END)
    else:
        graph.add_edge("score_and_aggregate", END)
    return graph.compile()
