"""Graph A: dataset authoring as a LangGraph StateGraph (spec §18.1).

State follows §14.2 AuthoringState. Node bodies delegate to
:mod:`lexstab.authoring`; critic disagreement routes to human review rather
than automatic acceptance.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from lexstab import authoring as auth


class AuthoringState(TypedDict, total=False):
    authoring_run_id: str
    ctx: Any  # AuthoringContext
    case: dict
    case_id: str
    requested_axes: list[str]
    count_per_axis: int
    existing: list[dict]
    coverage_snapshot: dict
    candidates: list[dict]
    equivalence_judgments: list[dict]
    adversarial_judgments: list[dict]
    adequacy_labels: list[dict]
    ambiguity_labels: list[dict]
    duplicate_groups: list[list[str]]
    human_review_required: list[str]
    accepted_candidates: list[dict]
    rejected_candidates: list[dict]
    errors: list[dict]


def node_load_cases(state: AuthoringState) -> dict:
    ctx: auth.AuthoringContext = state["ctx"]
    case = ctx.cases[state["case_id"]]
    return {"case": case.model_dump(), "errors": state.get("errors", [])}


def node_measure_axis_coverage(state: AuthoringState) -> dict:
    coverage = auth.measure_axis_coverage(
        state.get("existing", []), state["case_id"], state["requested_axes"]
    )
    return {"coverage_snapshot": {"counts": coverage}}


def node_plan_generation(state: AuthoringState) -> dict:
    ctx: auth.AuthoringContext = state["ctx"]
    case = ctx.cases[state["case_id"]]
    plan = auth.plan_generation(
        ctx, case, state.get("existing", []), state["requested_axes"],
        state.get("count_per_axis", 4),
    )
    coverage = dict(state.get("coverage_snapshot", {}))
    coverage["plan"] = plan
    return {"coverage_snapshot": coverage}


def node_generate_candidates(state: AuthoringState) -> dict:
    ctx: auth.AuthoringContext = state["ctx"]
    case = ctx.cases[state["case_id"]]
    candidates = auth.generate_candidates(
        ctx, case, state["requested_axes"], state.get("count_per_axis", 4),
        state.get("existing", []),
    )
    return {"candidates": candidates}


def node_validate_equivalence(state: AuthoringState) -> dict:
    ctx: auth.AuthoringContext = state["ctx"]
    case = ctx.cases[state["case_id"]]
    return {"equivalence_judgments": [
        auth.validate_equivalence(ctx, case, candidate["text"]) or {}
        for candidate in state["candidates"]
    ]}


def node_challenge_equivalence(state: AuthoringState) -> dict:
    ctx: auth.AuthoringContext = state["ctx"]
    case = ctx.cases[state["case_id"]]
    return {"adversarial_judgments": [
        auth.challenge_equivalence(ctx, case, candidate["text"], judgment) or {}
        for candidate, judgment in zip(state["candidates"], state["equivalence_judgments"])
    ]}


def node_classify_adequacy(state: AuthoringState) -> dict:
    ctx: auth.AuthoringContext = state["ctx"]
    case = ctx.cases[state["case_id"]]
    return {"adequacy_labels": [
        auth.classify_adequacy(ctx, case, candidate["text"], "(no shared context)") or {}
        for candidate in state["candidates"]
    ]}


def node_classify_ambiguity(state: AuthoringState) -> dict:
    ctx: auth.AuthoringContext = state["ctx"]
    case = ctx.cases[state["case_id"]]
    return {"ambiguity_labels": [
        auth.classify_ambiguity(ctx, case, candidate["text"], "(no shared context)") or {}
        for candidate in state["candidates"]
    ]}


def node_deduplicate(state: AuthoringState) -> dict:
    kept, duplicate_groups = auth.deduplicate(
        state["candidates"], [row["text"] for row in state.get("existing", [])]
    )
    kept_texts = {candidate["text"] for candidate in kept}
    indexes = [i for i, c in enumerate(state["candidates"]) if c["text"] in kept_texts]
    return {
        "candidates": [state["candidates"][i] for i in indexes],
        "equivalence_judgments": [state["equivalence_judgments"][i] for i in indexes],
        "adversarial_judgments": [state["adversarial_judgments"][i] for i in indexes],
        "adequacy_labels": [state["adequacy_labels"][i] for i in indexes],
        "ambiguity_labels": [state["ambiguity_labels"][i] for i in indexes],
        "duplicate_groups": duplicate_groups,
    }


def node_route_review(state: AuthoringState) -> dict:
    ctx: auth.AuthoringContext = state["ctx"]
    case = ctx.cases[state["case_id"]]
    generator_model = ctx.models_config.role("authoring_generator").model_id or ""
    existing_ids = {row["request_id"] for row in state.get("existing", [])}
    accepted, rejected, review = [], [], []
    for candidate, equivalence, adversarial, adequacy, ambiguity in zip(
        state["candidates"], state["equivalence_judgments"],
        state["adversarial_judgments"], state["adequacy_labels"], state["ambiguity_labels"],
    ):
        if equivalence.get("equivalent") is False and (
            equivalence.get("component_checks", {}).get("operation") == "DIFFERENT"
        ):
            rejected.append({"case_id": case.case_id, "text": candidate["text"],
                             "reason": "equivalence critic rejected"})
            continue
        record = auth.build_candidate_record(
            ctx, case, candidate,
            {"equivalence": equivalence, "adversarial": adversarial,
             "adequacy": adequacy, "ambiguity": ambiguity},
            existing_ids, generator_model,
        )
        existing_ids.add(record["request_id"])
        accepted.append(record)
        if record["validation"]["status"] == "NEEDS_REVIEW":
            review.append(record["request_id"])
    return {
        "accepted_candidates": accepted,
        "rejected_candidates": rejected,
        "human_review_required": review,
    }


def build_authoring_graph():
    graph = StateGraph(AuthoringState)
    graph.add_node("load_cases", node_load_cases)
    graph.add_node("measure_axis_coverage", node_measure_axis_coverage)
    graph.add_node("plan_generation", node_plan_generation)
    graph.add_node("generate_candidates", node_generate_candidates)
    graph.add_node("validate_equivalence", node_validate_equivalence)
    graph.add_node("challenge_equivalence", node_challenge_equivalence)
    graph.add_node("classify_adequacy", node_classify_adequacy)
    graph.add_node("classify_ambiguity", node_classify_ambiguity)
    graph.add_node("deduplicate", node_deduplicate)
    graph.add_node("route_review", node_route_review)

    graph.add_edge(START, "load_cases")
    graph.add_edge("load_cases", "measure_axis_coverage")
    graph.add_edge("measure_axis_coverage", "plan_generation")
    graph.add_edge("plan_generation", "generate_candidates")
    graph.add_edge("generate_candidates", "validate_equivalence")
    graph.add_edge("validate_equivalence", "challenge_equivalence")
    graph.add_edge("challenge_equivalence", "classify_adequacy")
    graph.add_edge("classify_adequacy", "classify_ambiguity")
    graph.add_edge("classify_ambiguity", "deduplicate")
    graph.add_edge("deduplicate", "route_review")
    graph.add_edge("route_review", END)
    return graph.compile()


def author_with_graph(ctx: auth.AuthoringContext, *, case_ids: list[str],
                      axes: list[str], count_per_axis: int,
                      existing: list[dict]) -> dict:
    compiled = build_authoring_graph()
    state: dict = {
        "authoring_run_id": ctx.authoring_run_id,
        "accepted_candidates": [],
        "rejected_candidates": [],
        "human_review_required": [],
        "duplicate_groups": [],
        "coverage": {},
        "errors": [],
    }
    for case_id in case_ids:
        final = compiled.invoke({
            "ctx": ctx,
            "case_id": case_id,
            "requested_axes": axes,
            "count_per_axis": count_per_axis,
            "existing": existing + state["accepted_candidates"],
        })
        state["accepted_candidates"].extend(final.get("accepted_candidates", []))
        state["rejected_candidates"].extend(final.get("rejected_candidates", []))
        state["human_review_required"].extend(final.get("human_review_required", []))
        state["duplicate_groups"].extend(final.get("duplicate_groups", []))
        state["coverage"][case_id] = final.get("coverage_snapshot")
    return state
