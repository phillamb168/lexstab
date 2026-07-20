"""Intent-elicitation subgraph (spec §18.5, §31.7).

Multi-turn loop with the turn-limit check BEFORE any further model invocation.
The graph wraps the same turn logic as :func:`lexstab.runner.run_elicitation`;
this compiled form exists so the subgraph is independently runnable and its
routing is explicit.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from lexstab.runner import CellResult, RunContext, run_elicitation


class ElicitationState(TypedDict, total=False):
    ctx: Any
    cell: Any
    result: Any


def node_load_elicitation_case(state: ElicitationState) -> dict:
    ctx: RunContext = state["ctx"]
    cell = state["cell"]
    if cell.elicitation_case_id not in ctx.bench.elicitation:
        raise ValueError(f"unknown elicitation case {cell.elicitation_case_id}")
    return {}


def node_run_turn_loop(state: ElicitationState) -> dict:
    """Executes assess -> route -> clarify -> inject -> update -> check-limit as
    one deterministic turn loop (turn-limit checked before each new invocation)."""
    result: CellResult = run_elicitation(state["ctx"], state["cell"])
    return {"result": result}


def node_score_turn_trajectory(state: ElicitationState) -> dict:
    result: CellResult = state["result"]
    turns = [entry for entry in result.elicitation_trace if "decision" in entry]
    return {"result": result, "trajectory_length": len(turns)}


def build_elicitation_graph():
    graph = StateGraph(ElicitationState)
    graph.add_node("load_elicitation_case", node_load_elicitation_case)
    graph.add_node("assess_route_clarify_loop", node_run_turn_loop)
    graph.add_node("score_turn_trajectory", node_score_turn_trajectory)
    graph.add_edge(START, "load_elicitation_case")
    graph.add_edge("load_elicitation_case", "assess_route_clarify_loop")
    graph.add_edge("assess_route_clarify_loop", "score_turn_trajectory")
    graph.add_edge("score_turn_trajectory", END)
    return graph.compile()
