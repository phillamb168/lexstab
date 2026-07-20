"""Graph D: adaptive red team (spec §18.4). Writes only candidate artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from lexstab import redteam as rt
from lexstab.artifacts import jsonl_read


class RedTeamState(TypedDict, total=False):
    ctx: Any
    run_dir: Any
    output: Any
    max_candidates: int
    failure_clusters: list[dict]
    hypotheses: dict
    report: dict


def node_load_failures(state: RedTeamState) -> dict:
    scores = jsonl_read(Path(state["run_dir"]) / "scores.jsonl")
    return {"failure_clusters": rt.cluster_failures(scores)}


def node_generate_hypotheses(state: RedTeamState) -> dict:
    hypotheses = rt.generate_hypotheses(state["ctx"], state["failure_clusters"])
    return {"hypotheses": hypotheses or {}}


def node_generate_and_validate(state: RedTeamState) -> dict:
    report = rt.run_redteam(
        state["ctx"], Path(state["run_dir"]),
        max_candidates=state.get("max_candidates", 50),
        output=Path(state["output"]),
    )
    return {"report": report}


def build_redteam_graph():
    graph = StateGraph(RedTeamState)
    graph.add_node("load_frozen_run_failures", node_load_failures)
    graph.add_node("generate_failure_hypotheses", node_generate_hypotheses)
    graph.add_node("generate_and_validate_candidates", node_generate_and_validate)
    graph.add_edge(START, "load_frozen_run_failures")
    graph.add_edge("load_frozen_run_failures", "generate_failure_hypotheses")
    graph.add_edge("generate_failure_hypotheses", "generate_and_validate_candidates")
    graph.add_edge("generate_and_validate_candidates", END)
    return graph.compile()
