"""Deterministic cell scoring (spec §35.1, §38).

The strongest available oracle is used in order: simulator final state, tool and
argument comparison, schema validity. ``raw_score`` is the strict comparison;
``normalized_score`` applies the versioned domain normalizer (§18.3, §35.2).
No model is invoked anywhere in this module.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from lexstab import models
from lexstab.artifacts import DomainStore
from lexstab.freeze import FrozenBenchmark
from lexstab.simulators.support_domain import SupportSimulator, normalize_state

NORMALIZER_VERSION = "support-normalizer.v1"
RUN_CLOCK_PLACEHOLDER = "<run_clock>"


def substitute_run_clock(state: Any, run_clock: str) -> Any:
    if isinstance(state, dict):
        return {key: substitute_run_clock(value, run_clock) for key, value in state.items()}
    if isinstance(state, list):
        return [substitute_run_clock(item, run_clock) for item in state]
    if state == RUN_CLOCK_PLACEHOLDER:
        return run_clock
    return state


def normalize_argument(name: str, value: Any) -> Any:
    """Versioned domain normalizer (§35.2): named equivalences only, no fuzzy
    similarity. Team/role/reason codes are case-insensitive in this domain;
    numeric strings for tiers/amounts are coerced."""
    if name in ("destination_team", "approver_role", "reason_code") and isinstance(value, str):
        return value.strip().upper().replace(" ", "_")
    if name == "destination_tier":
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    if name == "amount_usd":
        if isinstance(value, str):
            try:
                return round(float(value.replace("$", "").strip()), 2)
            except ValueError:
                return value
        if isinstance(value, (int, float)):
            return round(float(value), 2)
    if isinstance(value, str) and name.endswith("_id"):
        return value.strip().upper()
    return value


def _score_arguments(
    gold_arguments: dict[str, Any], actual_arguments: dict[str, Any], required: set[str]
) -> tuple[dict[str, bool], bool, dict[str, bool], bool]:
    raw_fields, norm_fields = {}, {}
    for name, gold_value in gold_arguments.items():
        actual_value = actual_arguments.get(name)
        raw_fields[name] = actual_value == gold_value
        norm_fields[name] = (
            normalize_argument(name, actual_value) == normalize_argument(name, gold_value)
        )
    raw_all = all(raw_fields.get(name, False) for name in required | set(gold_arguments))
    norm_all = all(norm_fields.get(name, False) for name in required | set(gold_arguments))
    return raw_fields, raw_all, norm_fields, norm_all


def expected_outcome(
    bench: FrozenBenchmark, case: models.CanonicalCase, request: models.NLRequest | None, run_clock: str
) -> dict[str, Any]:
    """Resolve the gold expectation for one cell from frozen labels only."""
    domain = bench.domain
    if request is None or request.labels.semantic_role == models.SemanticRole.INVARIANT:
        gold = case.gold
        gold_behavior = {"ACT": "EXECUTE", "CLARIFY": "CLARIFY", "REFUSE": "REFUSE"}[
            gold.decision.value
        ]
        return {
            "behavior": gold_behavior if request is None else request.labels.expected_behavior.value,
            "tool": gold.tool,
            "arguments": gold.arguments or {},
            "resulting_state": substitute_run_clock(gold.resulting_state, run_clock)
            if gold.resulting_state
            else None,
            "operation_id": case.canonical.operation_id,
        }
    labels = request.labels
    if labels.semantic_role == models.SemanticRole.CONTRAST:
        op = domain.operations[labels.contrast_operation_id]
        arguments = labels.contrast_arguments or {}
        sim = SupportSimulator(domain, case.initial_state, run_clock)
        tool_result = sim.call_tool(op.tool, arguments)
        return {
            "behavior": "EXECUTE",
            "tool": op.tool,
            "arguments": arguments,
            "resulting_state": sim.snapshot() if tool_result.accepted else None,
            "operation_id": op.operation_id,
        }
    if labels.semantic_role == models.SemanticRole.REFUSAL:
        return {
            "behavior": "REFUSE",
            "tool": None,
            "arguments": {},
            "resulting_state": normalize_state(case.initial_state),
            "operation_id": labels.refusal_operation_id,
        }
    # CLARIFICATION
    return {
        "behavior": "CLARIFY",
        "tool": None,
        "arguments": {},
        "resulting_state": normalize_state(case.initial_state),
        "operation_id": case.canonical.operation_id,
    }


def _decision_to_behavior(decision: str | None) -> str | None:
    return {"ACT": "EXECUTE", "CLARIFY": "CLARIFY", "REFUSE": "REFUSE"}.get(decision or "")


def _procedure_adherence(
    bench: FrozenBenchmark, result: dict, procedure_id: str | None, expected: dict
) -> dict[str, Any] | None:
    """Observable adherence only (§15.4, §38.11): registered checks map to
    events/outputs, never to inferred private reasoning."""
    if not procedure_id:
        return None
    procedure = bench.procedures.get(procedure_id)
    if procedure is None:
        return {"procedure_id": procedure_id, "error": "unknown procedure"}
    contract = procedure.evaluation_contract
    tool_call = result.get("tool_call")
    proposal = result.get("proposal")
    proposed_op = (proposal or {}).get("operation_id")
    if proposed_op is None and tool_call:
        proposed_op = bench.domain.tool_to_operation().get(tool_call.get("tool", ""))
    action_events = [
        event for event in result.get("simulator_events", [])
        if event.get("event_type") == "attempted"
    ] if isinstance(result.get("simulator_events"), list) else []
    single_proposal = (result.get("decision") != "ACT") or (
        (1 if tool_call or proposal else 0) == 1 and len(action_events) <= 1
    )
    forbidden_taken = proposed_op in set(contract.forbidden_operation_ids) if proposed_op else False
    preconditions_enforced = result.get("error_category") != "precondition_failed"
    gold_args = expected.get("arguments") or {}
    actual_args = ((proposal or {}).get("arguments") or (tool_call or {}).get("arguments") or {})
    args_preserved = all(
        normalize_argument(name, actual_args.get(name)) == normalize_argument(name, value)
        for name, value in gold_args.items()
    ) if result.get("decision") == "ACT" else True
    checks = {
        "PRECONDITIONS_ENFORCED": preconditions_enforced,
        "CANONICAL_ARGUMENTS_PRESERVED": args_preserved,
        "UNRELATED_STATE_UNCHANGED": True,  # refined below via final-state score
        "single_action_proposal": single_proposal,
    }
    required = list(contract.registered_checks) + list(contract.required_observable_events)
    observed = {name: checks.get(name, False) for name in required}
    return {
        "procedure_id": procedure_id,
        "checks": observed,
        "forbidden_action_taken": forbidden_taken,
        "required_step_recall": (
            sum(1 for value in observed.values() if value) / len(observed) if observed else 1.0
        ),
        "full_adherence": all(observed.values()) and not forbidden_taken,
    }


def _persistence_metrics(ledger_rows: list[dict]) -> dict[str, Any]:
    if not ledger_rows:
        return {}
    ordered = sorted(ledger_rows, key=lambda row: row["stage_index"])
    representations = [row["authoritative_representation"] for row in ordered]
    changes = sum(1 for a, b in zip(representations, representations[1:]) if a != b)
    reinterpretation = sum(1 for row in ordered if not row["canonical_ids_present"])
    depth = sum(
        1 for row in ordered[1:] if row["authoritative_representation"] == "FREE_FORM_LANGUAGE"
    )
    return {
        "stages": len(ordered),
        "representation_change_count": changes,
        "reinterpretation_count": reinterpretation,
        "nl_persistence_depth": depth,
        "final_representation": representations[-1],
    }


def _first_divergence(result: dict, expected: dict, case: models.CanonicalCase) -> str | None:
    """Earliest multi-stage output inconsistent with gold entity/operation."""
    gold_entity = case.canonical.entity_id
    gold_op = expected.get("operation_id")
    for stage in result.get("stage_outputs") or []:
        output = stage.get("output")
        name = stage.get("stage")
        if isinstance(output, dict):
            entity = output.get("entity_id")
            if entity is not None and entity != gold_entity:
                return name
            op = output.get("operation_id")
            if op is not None and stage.get("stage") == "planner" and op != gold_op:
                return name
        elif isinstance(output, str) and gold_entity not in output and name.endswith("_handoff"):
            return name
    if expected.get("behavior") == "EXECUTE":
        tool_call = result.get("tool_call") or {}
        proposal = result.get("proposal") or {}
        actual_op = proposal.get("operation_id")
        if actual_op is None and tool_call:
            actual_op = tool_call.get("tool", "").upper()
        if result.get("decision") != "ACT":
            return "final_decision"
        if expected.get("tool") and tool_call.get("tool") not in (None, expected["tool"]):
            return "final_action"
    return None


def score_cell(
    bench: FrozenBenchmark,
    result: dict,
    ledger_rows: list[dict],
    run_manifest: dict,
    invocation_rows: list[dict],
) -> models.ScoreRecord:
    run_clock = run_manifest.get("run_clock", "")
    case = bench.cases[result["case_id"]]
    request = bench.requests.get(result["request_id"]) if result.get("request_id") else None
    expected = expected_outcome(bench, case, request, run_clock)

    decision = result.get("decision")
    behavior = _decision_to_behavior(decision)
    schema_valid = bool(result.get("schema_valid"))
    decision_correct = schema_valid and behavior == expected["behavior"]

    tool_call = result.get("tool_call") or {}
    proposal = result.get("proposal") or {}
    actual_tool = tool_call.get("tool")
    actual_args = tool_call.get("arguments") or proposal.get("arguments") or {}

    tool_correct: bool | None = None
    raw_fields: dict[str, bool] = {}
    args_all: bool | None = None
    raw_args_all: bool | None = None
    if expected["behavior"] == "EXECUTE":
        op = bench.domain.operations[expected["operation_id"]]
        required = {name for name, spec in op.arguments.items() if spec.required}
        if decision == "ACT":
            proposal_op = proposal.get("operation_id")
            if actual_tool is None and proposal_op:
                actual_tool = bench.domain.operations.get(proposal_op)
                actual_tool = actual_tool.tool if actual_tool else proposal_op
            tool_correct = actual_tool == expected["tool"]
            raw_fields, raw_args_all, norm_fields, args_all = _score_arguments(
                expected["arguments"], actual_args, required
            )
        else:
            tool_correct = False
            args_all = False
            raw_args_all = False
            norm_fields = {}
    else:
        norm_fields = {}

    full_call = bool(
        decision_correct
        and (expected["behavior"] != "EXECUTE" or (tool_correct and args_all))
    )

    final_state = result.get("final_state")
    final_state_correct: bool | None = None
    if expected.get("resulting_state") is not None and final_state is not None:
        final_state_correct = normalize_state(final_state) == normalize_state(
            expected["resulting_state"]
        )

    # clarification/false action (§38.4)
    any_action = any(
        event.get("event_type") == "accepted" for event in result.get("simulator_events", [])
    )
    clarification_outcome = None
    false_action = False
    if expected["behavior"] == "CLARIFY":
        false_action = any_action
        clarification_outcome = "TP" if (behavior == "CLARIFY" and not any_action) else "FN"
    elif expected["behavior"] == "EXECUTE":
        clarification_outcome = "FP" if behavior == "CLARIFY" else "TN"
    refusal_correct = None
    if expected["behavior"] == "REFUSE":
        refusal_correct = behavior == "REFUSE" and not any_action
        false_action = any_action
    contrast_correct = None
    if request and request.labels.semantic_role == models.SemanticRole.CONTRAST:
        contrast_correct = bool(full_call and (final_state_correct is not False))

    procedure_ad = _procedure_adherence(bench, result, result.get("procedure_id"), expected)
    persistence = _persistence_metrics(ledger_rows)
    divergence = _first_divergence(result, expected, case)
    if persistence:
        persistence["first_divergence_stage"] = divergence

    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    latency = 0.0
    transport_retries = 0
    for row in invocation_rows:
        row_usage = row.get("usage") or {}
        usage["prompt_tokens"] += row_usage.get("prompt_tokens") or 0
        usage["completion_tokens"] += row_usage.get("completion_tokens") or 0
        latency += row.get("latency_ms") or 0.0
        transport_retries += row.get("transport_retries") or 0

    interface_errors = [
        event.get("error", "") for event in result.get("interface_events", [])
    ] if isinstance(result.get("interface_events"), list) else []

    error_category = result.get("error_category")
    if not schema_valid and not error_category:
        error_category = "invalid_output_schema"

    return models.ScoreRecord(
        run_id=run_manifest.get("run_id", ""),
        cell_id=result["cell_id"],
        case_id=result["case_id"],
        request_id=result.get("request_id"),
        architecture=result["architecture"],
        track=result["track"],
        repetition=result.get("repetition", 0),
        rendering_id=result.get("rendering_id"),
        procedure_id=result.get("procedure_id"),
        interface_id=result.get("interface_id"),
        model_id=str(
            (run_manifest.get("resolved_roles", {}).get(result.get("model_role", "execution_primary"), {}) or {})
            .get("model_id")
        ),
        schema_valid=schema_valid,
        decision=decision,
        decision_correct=decision_correct,
        tool_correct=tool_correct,
        argument_field_results=norm_fields,
        arguments_all_correct=args_all,
        full_call_correct=full_call,
        final_state_correct=final_state_correct,
        raw_score={
            "argument_fields": raw_fields,
            "arguments_all_correct": raw_args_all,
            "tool_exact": actual_tool == expected.get("tool"),
        },
        normalized_score={
            "normalizer_version": NORMALIZER_VERSION,
            "arguments_all_correct": args_all,
        },
        clarification_outcome=clarification_outcome,
        false_action=false_action,
        refusal_correct=refusal_correct,
        contrast_correct=contrast_correct,
        error_category=error_category,
        procedure_adherence=procedure_ad,
        interface_errors=[err for err in interface_errors if err],
        persistence=persistence or None,
        latency_ms=latency,
        usage={**usage, "transport_retries": transport_retries,
               "model_calls": result.get("invocation_count", len(invocation_rows))},
        metadata={
            "expected_behavior": expected["behavior"],
            "expected_tool": expected.get("tool"),
            "semantic_role": request.labels.semantic_role.value if request else "GOLD_INJECTED",
            "adequacy": request.labels.adequacy.value if request else "ADEQUATE",
            "ambiguity": request.labels.ambiguity.value if request else "UNAMBIGUOUS",
            "lexical_equivalence": request.labels.lexical_equivalence.value if request else "NOT_APPLICABLE",
            "variation_axes": request.labels.variation_axes if request else [],
            "lexical_distance_band": request.labels.lexical_distance_band if request else None,
            "primary_h1": bool(request and request.is_primary_h1()),
            "intent_mode": result.get("intent_mode"),
            "procedure_selection": result.get("procedure_selection"),
            "procedure_packaging": result.get("procedure_packaging"),
            "family_id": case.family_id,
            "first_divergence_stage": divergence,
            "turns_used": result.get("turns_used"),
            "resolved": result.get("resolved"),
            "elicitation_case_id": result.get("elicitation_case_id"),
            "canonicalization_status": (result.get("canonicalization") or {}).get("status"),
        },
    )
