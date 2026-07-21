"""Deterministic cell scoring (spec §35.1, §38).

The strongest available oracle is used in order: simulator final state, tool and
argument comparison, schema validity. ``raw_score`` is the strict comparison;
``normalized_score`` applies the versioned domain normalizer (§18.3, §35.2).
No model is invoked anywhere in this module.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from lexstab import domaintext, models
from lexstab.artifacts import DomainStore
from lexstab.freeze import FrozenBenchmark
from lexstab.simulators.support_domain import SupportSimulator, normalize_state

NORMALIZER_VERSION = "support-normalizer.v1"
VERBATIM_COMPARISON_VERSION = "deterministic-token-sequence.v1"
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


def _verbatim_tokens(value: Any) -> list[str]:
    """Deterministic, case-sensitive word-and-punctuation tokenization."""
    return re.findall(r"\w+|[^\w\s]", str(value), flags=re.UNICODE)


def _contains_verbatim_tokens(container: str, literal: Any) -> bool:
    expected = _verbatim_tokens(literal)
    observed = _verbatim_tokens(container)
    if not expected:
        return True
    width = len(expected)
    return any(
        observed[index:index + width] == expected
        for index in range(len(observed) - width + 1)
    )


def _score_arguments(
    gold_arguments: dict[str, Any], actual_arguments: dict[str, Any], required: set[str],
    specs: dict[str, models.ArgumentSpec],
) -> tuple[dict[str, bool], bool, dict[str, bool], bool, dict[str, Any]]:
    raw_fields, norm_fields = {}, {}
    preservation_fields = {}
    for name, gold_value in gold_arguments.items():
        actual_value = actual_arguments.get(name)
        raw_fields[name] = actual_value == gold_value
        spec = specs.get(name)
        mode = (
            spec.preservation
            if spec is not None else models.ArgumentPreservation.SEMANTIC
        )
        norm_fields[name] = raw_fields[name] if mode == models.ArgumentPreservation.VERBATIM else (
            normalize_argument(name, actual_value) == normalize_argument(name, gold_value)
        )
        preservation_fields[name] = {
            "mode": mode.value,
            "correct": norm_fields[name],
            "raw_exact": raw_fields[name],
        }
    raw_all = all(raw_fields.get(name, False) for name in required | set(gold_arguments))
    norm_all = all(norm_fields.get(name, False) for name in required | set(gold_arguments))
    return raw_fields, raw_all, norm_fields, norm_all, preservation_fields


def expected_outcome(
    bench: FrozenBenchmark,
    case: models.CanonicalCase,
    request: models.NLRequest | None,
    run_clock: str,
    *,
    gold_injected: bool = False,
) -> dict[str, Any]:
    """Resolve the gold expectation for one cell from frozen labels only."""
    domain = bench.domain
    if gold_injected:
        request = None
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
        "UNRELATED_STATE_UNCHANGED": (
            expected.get("resulting_state") is None
            or (
                result.get("final_state") is not None
                and normalize_state(result["final_state"])
                == normalize_state(expected["resulting_state"])
            )
        ),
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


def _first_divergences(
    bench: FrozenBenchmark,
    result: dict,
    expected: dict,
    case: models.CanonicalCase,
) -> dict[str, str | None]:
    """Locate deterministic entity, operation, and argument divergence.

    Diagnostic stage-result schemas are checked only for fields they are
    designed to carry. Free-form handoffs are checked for exact VERBATIM
    literals because their prompts make the handoff authoritative and require
    supplied arguments to survive. Semantic equivalence is never guessed.
    """
    gold_entity = case.canonical.entity_id
    gold_op = expected.get("operation_id")
    expected_args = expected.get("arguments") or {}
    operation = bench.domain.operations.get(gold_op or "")
    specs = operation.arguments if operation else {}
    entity_divergence = None
    operation_divergence = None
    argument_divergence = None
    verbatim_divergence = None

    for stage in result.get("stage_outputs") or []:
        output = stage.get("output")
        name = stage.get("stage")
        if isinstance(output, dict):
            entity = output.get("entity_id")
            if entity is not None and entity != gold_entity and entity_divergence is None:
                entity_divergence = name
            op = output.get("operation_id")
            if op is not None and op != gold_op and operation_divergence is None:
                operation_divergence = name
            arguments = output.get("arguments")
            if isinstance(arguments, dict):
                for arg_name, gold_value in expected_args.items():
                    spec = specs.get(arg_name)
                    mode = (
                        spec.preservation
                        if spec is not None else models.ArgumentPreservation.SEMANTIC
                    )
                    actual_value = arguments.get(arg_name)
                    equal = (
                        actual_value == gold_value
                        if mode == models.ArgumentPreservation.VERBATIM
                        else normalize_argument(arg_name, actual_value)
                        == normalize_argument(arg_name, gold_value)
                    )
                    if not equal and argument_divergence is None:
                        argument_divergence = name
                    if (
                        mode == models.ArgumentPreservation.VERBATIM
                        and actual_value != gold_value
                        and verbatim_divergence is None
                    ):
                        verbatim_divergence = name
        elif isinstance(output, str) and isinstance(name, str) and name.endswith("_handoff"):
            if gold_entity and gold_entity not in output and entity_divergence is None:
                entity_divergence = name
            for arg_name, gold_value in expected_args.items():
                spec = specs.get(arg_name)
                if (
                    spec is not None
                    and spec.preservation == models.ArgumentPreservation.VERBATIM
                    and not _contains_verbatim_tokens(output, gold_value)
                ):
                    if argument_divergence is None:
                        argument_divergence = name
                    if verbatim_divergence is None:
                        verbatim_divergence = name

    if expected.get("behavior") == "EXECUTE":
        tool_call = result.get("tool_call") or {}
        proposal = result.get("proposal") or {}
        actual_op = proposal.get("operation_id")
        if actual_op is None and tool_call:
            actual_op = bench.domain.tool_to_operation().get(tool_call.get("tool", ""))
        if result.get("decision") != "ACT":
            operation_divergence = operation_divergence or "final_decision"
            argument_divergence = argument_divergence or "final_decision"
            if any(
                spec.preservation == models.ArgumentPreservation.VERBATIM
                for spec in specs.values()
            ):
                verbatim_divergence = verbatim_divergence or "final_decision"
        else:
            if actual_op != gold_op and operation_divergence is None:
                operation_divergence = "final_action"
            actual_args = tool_call.get("arguments") or proposal.get("arguments") or {}
            for arg_name, gold_value in expected_args.items():
                spec = specs.get(arg_name)
                mode = (
                    spec.preservation
                    if spec is not None else models.ArgumentPreservation.SEMANTIC
                )
                actual_value = actual_args.get(arg_name)
                equal = (
                    actual_value == gold_value
                    if mode == models.ArgumentPreservation.VERBATIM
                    else normalize_argument(arg_name, actual_value)
                    == normalize_argument(arg_name, gold_value)
                )
                if not equal and argument_divergence is None:
                    argument_divergence = "final_action"
                if (
                    mode == models.ArgumentPreservation.VERBATIM
                    and actual_value != gold_value
                    and verbatim_divergence is None
                ):
                    verbatim_divergence = "final_action"

    stages = [
        stage.get("stage") for stage in result.get("stage_outputs") or []
        if stage.get("stage")
    ] + ["final_decision", "final_action"]
    rank = {name: index for index, name in enumerate(stages)}
    present = [
        value for value in (
            entity_divergence, operation_divergence,
            argument_divergence, verbatim_divergence,
        ) if value is not None
    ]
    return {
        "first_entity_divergence": entity_divergence,
        "first_operation_divergence": operation_divergence,
        "first_argument_divergence": argument_divergence,
        "first_verbatim_argument_divergence": verbatim_divergence,
        "first_divergence_stage": (
            min(present, key=lambda value: rank.get(value, len(rank)))
            if present else None
        ),
    }


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
    gold_injected = result.get("intent_mode") == "gold"
    expected = expected_outcome(
        bench, case, request, run_clock, gold_injected=gold_injected
    )
    # An elicitation cell is scored against the resolved task only after the
    # scripted user has supplied the missing information. Before resolution,
    # the original CLARIFY expectation remains authoritative.
    if result.get("track") == "intent_elicitation" and result.get("resolved"):
        expected = expected_outcome(bench, case, None, run_clock)

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
    preservation_fields: dict[str, Any] = {}
    if expected["behavior"] == "EXECUTE":
        op = bench.domain.operations[expected["operation_id"]]
        required = {name for name, spec in op.arguments.items() if spec.required}
        if decision == "ACT":
            proposal_op = proposal.get("operation_id")
            if actual_tool is None and proposal_op:
                actual_tool = bench.domain.operations.get(proposal_op)
                actual_tool = actual_tool.tool if actual_tool else proposal_op
            tool_correct = actual_tool == expected["tool"]
        else:
            tool_correct = False
        raw_fields, raw_args_all, norm_fields, args_all, preservation_fields = _score_arguments(
            expected["arguments"], actual_args, required, op.arguments
        )
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
        event.get("event_type") == "attempted"
        for event in result.get("simulator_events", [])
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
    selection_events = result.get("procedure_events") or []
    selection_correct = None
    if result.get("procedure_selection") == "runtime":
        runtime_events = [event for event in selection_events if event.get("mode") == "runtime"]
        if runtime_events:
            selection_correct = all(bool(event.get("correct")) for event in runtime_events)
    persistence = _persistence_metrics(ledger_rows)
    divergences = _first_divergences(bench, result, expected, case)
    divergence = divergences["first_divergence_stage"]
    if persistence:
        persistence.update(divergences)

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

    parity_evidence = next(
        (
            stage.get("output")
            for stage in result.get("stage_outputs") or []
            if stage.get("stage") == "information_parity"
        ),
        None,
    )
    assessment = next(
        (
            trace.get("assessment")
            for trace in result.get("elicitation_trace") or []
            if isinstance(trace.get("assessment"), dict)
        ),
        None,
    )
    adequacy_assessment_correct = None
    if assessment is not None and request is not None:
        adequacy_assessment_correct = bool(
            assessment.get("adequacy") == request.labels.adequacy.value
            and assessment.get("ambiguity") == request.labels.ambiguity.value
            and set(assessment.get("missing_information") or [])
            == set(request.labels.missing_information)
        )

    rendering_category = None
    rendering_lexically_distinct = None
    rendering_text = result.get("rendering_text")
    canonical_rendering_text = None
    rendering_id = result.get("rendering_id")
    if rendering_id and rendering_id in bench.renderings:
        rendering = bench.renderings[rendering_id]
        operation = bench.domain.operations[expected["operation_id"]]
        entity_id = next(
            (
                value for name, value in (expected.get("arguments") or {}).items()
                if name.endswith("_id")
            ),
            case.canonical.entity_id,
        )
        intent = {
            "entity_type": operation.entity_type,
            "entity_id": entity_id,
            "operation_id": expected["operation_id"],
            "arguments": expected.get("arguments") or {},
        }
        rendering_text = rendering_text or domaintext.rendering_text(rendering, intent)
        rendering_category = rendering.category.value
        canonical_rendering = bench.rendering_for_operation(
            expected["operation_id"], "CANONICAL_LABEL"
        )
        if canonical_rendering:
            canonical_rendering_text = domaintext.rendering_text(canonical_rendering, intent)
            rendering_lexically_distinct = (
                " ".join(rendering_text.casefold().split())
                != " ".join(canonical_rendering_text.casefold().split())
            )

    verbatim_arguments_correct = (
        all(
            detail["correct"]
            for detail in preservation_fields.values()
            if detail["mode"] == "VERBATIM"
        )
        if any(
            detail["mode"] == "VERBATIM"
            for detail in preservation_fields.values()
        ) else None
    )

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
        actual_operation_id=(
            proposal.get("operation_id")
            or bench.domain.tool_to_operation().get(actual_tool or "")
        ),
        actual_tool=actual_tool,
        actual_arguments=actual_args,
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
        argument_preservation={
            "comparison_method": VERBATIM_COMPARISON_VERSION,
            "fields": preservation_fields,
            "verbatim_all_correct": verbatim_arguments_correct,
        },
        verbatim_arguments_correct=verbatim_arguments_correct,
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
            "semantic_role": "GOLD_INJECTED" if gold_injected else (
                request.labels.semantic_role.value if request else "GOLD_INJECTED"
            ),
            "adequacy": "ADEQUATE" if gold_injected else (
                request.labels.adequacy.value if request else "ADEQUATE"
            ),
            "ambiguity": "UNAMBIGUOUS" if gold_injected else (
                request.labels.ambiguity.value if request else "UNAMBIGUOUS"
            ),
            "lexical_equivalence": "NOT_APPLICABLE" if gold_injected else (
                request.labels.lexical_equivalence.value if request else "NOT_APPLICABLE"
            ),
            "variation_axes": [] if gold_injected else (request.labels.variation_axes if request else []),
            "missing_information": [] if gold_injected else (request.labels.missing_information if request else []),
            "source_request_semantic_role": request.labels.semantic_role.value if request else None,
            "source_request_adequacy": request.labels.adequacy.value if request else None,
            "source_request_ambiguity": request.labels.ambiguity.value if request else None,
            "source_request_expected_behavior": request.labels.expected_behavior.value if request else None,
            "clarification_targets": case.gold.clarification_targets or [],
            "expected_operation_id": expected.get("operation_id"),
            "expected_arguments": expected.get("arguments") or {},
            "is_designated_canonical": bool(
                request
                and "canonical_terminology" in request.labels.variation_axes
                and request.labels.contains_canonical_entity_term
                and request.labels.contains_canonical_operation_term
            ),
            "lexical_distance_band": request.labels.lexical_distance_band if request else None,
            "primary_h1": bool(request and request.is_primary_h1()),
            "intent_mode": result.get("intent_mode"),
            "procedure_selection": result.get("procedure_selection"),
            "procedure_selection_correct": selection_correct,
            "procedure_packaging": result.get("procedure_packaging"),
            "family_id": case.family_id,
            "first_divergence_stage": divergence,
            **divergences,
            "turns_used": result.get("turns_used"),
            "resolved": result.get("resolved"),
            "elicitation_case_id": result.get("elicitation_case_id"),
            "canonicalization_status": (
                result.get("canonicalization") or {}
            ).get("mapping_outcome"),
            "canonical_grounding": (
                result.get("canonicalization") or {}
            ).get("grounding", {}),
            "rendering_category": rendering_category,
            "rendering_text": rendering_text,
            "canonical_rendering_text": canonical_rendering_text,
            "rendering_lexically_distinct": rendering_lexically_distinct,
            "adequacy_assessment_correct": adequacy_assessment_correct,
            "information_parity_verified": bool(
                parity_evidence and parity_evidence.get("verified")
                and parity_evidence.get("common_facts_hash")
            ),
            "common_facts_hash": (
                parity_evidence.get("common_facts_hash") if parity_evidence else None
            ),
        },
    )
