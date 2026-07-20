"""Graph E: progressive formalization and language persistence (spec §18.6).

Nodes mirror §18.6's required list; condition execution delegates to the
shared runner functions so the graph and procedural paths stay equivalent.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from lexstab.runner import CellResult, RunContext, run_formalization, run_persistence


class FormalizationState(TypedDict, total=False):
    ctx: Any
    cell: Any
    parity_ok: bool
    condition_kind: str
    result: Any


def node_load_formalization_artifacts(state: FormalizationState) -> dict:
    ctx: RunContext = state["ctx"]
    cell = state["cell"]
    if cell.procedure_id and cell.procedure_id not in ctx.bench.procedures:
        raise ValueError(f"unknown procedure {cell.procedure_id}")
    if cell.interface_id and cell.interface_id not in ctx.bench.interfaces:
        raise ValueError(f"unknown interface {cell.interface_id}")
    return {}


def node_verify_information_parity(state: FormalizationState) -> dict:
    """P0-P3 share the generic proposal contract; P3/P4 share procedure bytes
    (§15.6). Structural parity is enforced here before any invocation."""
    ctx: RunContext = state["ctx"]
    cell = state["cell"]
    if cell.architecture in ("P0_RAW_PROPOSAL", "P1_CLARIFY_PROPOSAL",
                             "P2_CANONICAL_PROPOSAL", "P2F_CANONICAL_FACTS_PROPOSAL",
                             "P3_CANONICAL_PROCEDURE_PROPOSAL"):
        if cell.interface_id != "GENERIC_ACTION_PROPOSAL_V1":
            raise ValueError(f"{cell.architecture} must use the generic proposal interface")
    if cell.architecture in ("P4_CANONICAL_PROCEDURE_TOOL", "LP3_CANONICAL_PROCEDURE_TOOL"):
        if cell.interface_id not in ("TYPED_SUPPORT_TOOLS_V1", "MCP_SUPPORT_CAPABILITIES_V1"):
            raise ValueError(f"{cell.architecture} must use a typed action interface")
    return {"parity_ok": True}


def node_select_condition(state: FormalizationState) -> dict:
    cell = state["cell"]
    return {"condition_kind": "persistence" if cell.architecture.startswith("LP") else "ladder"}


def node_execute_ladder(state: FormalizationState) -> dict:
    return {"result": run_formalization(state["ctx"], state["cell"])}


def node_execute_persistence(state: FormalizationState) -> dict:
    return {"result": run_persistence(state["ctx"], state["cell"])}


def node_record_ledger(state: FormalizationState) -> dict:
    result: CellResult = state["result"]
    if not result.ledger:
        raise ValueError(f"cell {result.cell.cell_id}: no representation ledger recorded")
    if result.cell.architecture.startswith("P"):
        parity = next(
            (
                stage.get("output")
                for stage in result.stage_outputs
                if stage.get("stage") == "information_parity"
            ),
            None,
        )
        if not parity or not parity.get("verified") or not parity.get("common_facts_hash"):
            raise ValueError(
                f"cell {result.cell.cell_id}: information-parity evidence missing"
            )
    return {}


def build_formalization_graph():
    graph = StateGraph(FormalizationState)
    graph.add_node("load_formalization_artifacts", node_load_formalization_artifacts)
    graph.add_node("verify_information_parity", node_verify_information_parity)
    graph.add_node("select_formalization_condition", node_select_condition)
    graph.add_node("execute_ladder_condition", node_execute_ladder)
    graph.add_node("execute_persistence_condition", node_execute_persistence)
    graph.add_node("record_representation_ledger", node_record_ledger)

    graph.add_edge(START, "load_formalization_artifacts")
    graph.add_edge("load_formalization_artifacts", "verify_information_parity")
    graph.add_edge("verify_information_parity", "select_formalization_condition")
    graph.add_conditional_edges(
        "select_formalization_condition",
        lambda state: state["condition_kind"],
        {"ladder": "execute_ladder_condition", "persistence": "execute_persistence_condition"},
    )
    graph.add_edge("execute_ladder_condition", "record_representation_ledger")
    graph.add_edge("execute_persistence_condition", "record_representation_ledger")
    graph.add_edge("record_representation_ledger", END)
    return graph.compile()
