"""Graph B: benchmark execution as a LangGraph StateGraph (spec §18.2; D-008).

Routing follows the §18.2 diagram: verify manifest -> expand matrix -> per cell
reset simulator -> route by track/architecture -> execute -> record. Node
bodies are the same functions the procedural baseline calls, so the graph
cannot introduce behavioral differences; §18.7's comparison checks that.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from lexstab.matrix import MatrixCell
from lexstab.runner import (
    CellResult,
    RunContext,
    run_agent_loop,
    run_canonical,
    run_direct,
    run_elicitation,
    run_formalization,
    run_memory,
    run_persistence,
)


class ExecutionState(TypedDict, total=False):
    run_id: str
    matrix_cell: dict
    cell: Any  # MatrixCell
    ctx: Any  # RunContext
    result: Any  # CellResult
    route: str


def node_reset(state: ExecutionState) -> dict:
    # Fresh simulator state and fresh model context are created inside each
    # execute node (§49.1); this node validates the cell reference.
    cell: MatrixCell = state["cell"]
    ctx: RunContext = state["ctx"]
    if cell.case_id not in ctx.bench.cases:
        raise ValueError(f"unknown case {cell.case_id}")
    return {"matrix_cell": cell.to_dict()}


def node_route(state: ExecutionState) -> dict:
    cell: MatrixCell = state["cell"]
    if cell.track == "intent_elicitation":
        return {"route": "elicitation"}
    if cell.track == "agent_loop":
        return {"route": "agent_loop"}
    arch = cell.architecture
    if arch in ("A0_DIRECT", "A1_DIRECT_CLARIFY"):
        return {"route": "direct"}
    if arch.startswith("M"):
        return {"route": "memory"}
    if arch.startswith("LP"):
        return {"route": "persistence"}
    if arch.startswith("P"):
        return {"route": "formalization"}
    return {"route": "canonical"}


def node_execute_direct(state: ExecutionState) -> dict:
    cell: MatrixCell = state["cell"]
    clarify = cell.architecture == "A1_DIRECT_CLARIFY"
    return {"result": run_direct(state["ctx"], cell, clarify_policy=clarify)}


def node_execute_canonical(state: ExecutionState) -> dict:
    return {"result": run_canonical(state["ctx"], state["cell"])}


def node_execute_memory(state: ExecutionState) -> dict:
    return {"result": run_memory(state["ctx"], state["cell"])}


def node_execute_formalization(state: ExecutionState) -> dict:
    return {"result": run_formalization(state["ctx"], state["cell"])}


def node_execute_persistence(state: ExecutionState) -> dict:
    return {"result": run_persistence(state["ctx"], state["cell"])}


def node_execute_agent_loop(state: ExecutionState) -> dict:
    return {"result": run_agent_loop(state["ctx"], state["cell"])}


def node_execute_elicitation(state: ExecutionState) -> dict:
    return {"result": run_elicitation(state["ctx"], state["cell"])}


def node_record(state: ExecutionState) -> dict:
    result: CellResult = state["result"]
    return {"matrix_cell": result.cell.to_dict()}


def build_execution_graph():
    graph = StateGraph(ExecutionState)
    graph.add_node("reset_simulator", node_reset)
    graph.add_node("route", node_route)
    graph.add_node("execute_direct", node_execute_direct)
    graph.add_node("execute_canonical", node_execute_canonical)
    graph.add_node("execute_memory", node_execute_memory)
    graph.add_node("execute_formalization", node_execute_formalization)
    graph.add_node("execute_persistence", node_execute_persistence)
    graph.add_node("execute_agent_loop", node_execute_agent_loop)
    graph.add_node("execute_elicitation", node_execute_elicitation)
    graph.add_node("record", node_record)

    graph.add_edge(START, "reset_simulator")
    graph.add_edge("reset_simulator", "route")
    graph.add_conditional_edges(
        "route",
        lambda state: state["route"],
        {
            "direct": "execute_direct",
            "canonical": "execute_canonical",
            "memory": "execute_memory",
            "formalization": "execute_formalization",
            "persistence": "execute_persistence",
            "agent_loop": "execute_agent_loop",
            "elicitation": "execute_elicitation",
        },
    )
    for node in ("execute_direct", "execute_canonical", "execute_memory",
                 "execute_formalization", "execute_persistence",
                 "execute_agent_loop", "execute_elicitation"):
        graph.add_edge(node, "record")
    graph.add_edge("record", END)
    return graph.compile()


_COMPILED = None


def graph_run_cell(ctx: RunContext, cell: MatrixCell) -> CellResult:
    """Cell runner backed by the compiled LangGraph (drop-in for run_cell)."""
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = build_execution_graph()
    final_state = _COMPILED.invoke({"ctx": ctx, "cell": cell, "run_id": ctx.run_id})
    return final_state["result"]


def compare_runners(run_dir_a, run_dir_b) -> dict:
    """§18.7 control: graph and procedural runs must match cell for cell
    except trace metadata (timestamps, latency)."""
    from lexstab.artifacts import jsonl_read

    def _essential(row: dict) -> dict:
        return {
            "cell_id": row["cell_id"],
            "decision": row.get("decision"),
            "tool_call": row.get("tool_call"),
            "proposal": row.get("proposal"),
            "final_state": row.get("final_state"),
            "schema_valid": row.get("schema_valid"),
            "error_category": row.get("error_category"),
        }

    rows_a = {row["cell_id"]: _essential(row) for row in jsonl_read(f"{run_dir_a}/cell-results.jsonl")}
    rows_b = {row["cell_id"]: _essential(row) for row in jsonl_read(f"{run_dir_b}/cell-results.jsonl")}
    mismatches = []
    for cell_id in sorted(set(rows_a) | set(rows_b)):
        if rows_a.get(cell_id) != rows_b.get(cell_id):
            mismatches.append(cell_id)
    return {
        "cells_a": len(rows_a),
        "cells_b": len(rows_b),
        "mismatched_cells": mismatches,
        "equivalent": not mismatches and len(rows_a) == len(rows_b),
    }
