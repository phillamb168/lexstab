"""Cell execution for every architecture condition (spec §9.3, §18.2, §33).

``run_cell`` executes one matrix cell: fresh simulator, fresh model context,
prompt assembly, invocation, single-pass parsing, simulator application, and
representation-ledger capture. Both the LangGraph runner and the procedural
baseline call these functions, so orchestration cannot change behavior (D-008).
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from lexstab import canonical, domaintext, models
from lexstab.config import ModelsConfig
from lexstab.freeze import FrozenBenchmark
from lexstab.hashing import canonical_json, sha256_text
from lexstab.interfaces import GENERIC_PROPOSAL_SCHEMA
from lexstab.matrix import MatrixCell
from lexstab.prompts import PromptLibrary
from lexstab.providers.base import BaseAdapter, extract_json_object, provider_failure_category
from lexstab.simulators.support_domain import SupportSimulator


@dataclass
class RunContext:
    root: Any
    bench: FrozenBenchmark
    prompts: PromptLibrary
    models_config: ModelsConfig
    providers: dict[str, BaseAdapter]
    run_id: str
    run_clock: str
    mocked: bool = False

    def provider_for(self, role: str) -> tuple[BaseAdapter, str, dict]:
        role_config = self.models_config.role(role)
        adapter = self.providers[role]
        if not role_config.model_id:
            raise ValueError(f"enabled model role {role!r} has no resolved model ID")
        return adapter, role_config.model_id, dict(role_config.parameters)


@dataclass
class CellResult:
    cell: MatrixCell
    invocations: list[models.InvocationRecord] = field(default_factory=list)
    ledger: list[models.RepresentationLedgerRecord] = field(default_factory=list)
    simulator_events: list[dict] = field(default_factory=list)
    procedure_events: list[dict] = field(default_factory=list)
    interface_events: list[dict] = field(default_factory=list)
    stage_outputs: list[dict] = field(default_factory=list)
    decision: str | None = None
    tool_call: dict | None = None
    proposal: dict | None = None
    question: str | None = None
    reason_code: str | None = None
    final_state: dict | None = None
    schema_valid: bool = True
    error_category: str | None = None
    canonicalization: dict | None = None
    elicitation_trace: list[dict] = field(default_factory=list)
    turns_used: int = 0
    resolved: bool | None = None
    actual_rendering_id: str | None = None
    actual_rendering_category: str | None = None
    actual_rendering_text: str | None = None
    actual_procedure_id: str | None = None

    def summary(self) -> dict:
        summary = {
            **self.cell.to_dict(),
            "decision": self.decision,
            "tool_call": self.tool_call,
            "proposal": self.proposal,
            "question": self.question,
            "reason_code": self.reason_code,
            "final_state": self.final_state,
            "schema_valid": self.schema_valid,
            "error_category": self.error_category,
            "canonicalization": self.canonicalization,
            "invocation_count": len(self.invocations),
            "turns_used": self.turns_used,
            "resolved": self.resolved,
            "elicitation_trace": self.elicitation_trace,
            "stage_outputs": self.stage_outputs,
            "rendering_id": self.actual_rendering_id or self.cell.rendering_id,
            "rendering_category": (
                self.actual_rendering_category or self.cell.rendering_category
            ),
            "rendering_text": self.actual_rendering_text,
            "procedure_id": self.actual_procedure_id or self.cell.procedure_id,
        }
        return summary


class ProviderInvocationFailure(RuntimeError):
    """A terminal provider failure that retains the partially recorded cell."""

    def __init__(self, result: CellResult, category: str, detail: str):
        super().__init__(detail)
        self.result = result
        self.category = category


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _invoke(
    ctx: RunContext,
    result: CellResult,
    *,
    role: str,
    prompt_id: str,
    variables: dict[str, str],
    response_kind: str,
    stage_id: str,
    tools: list[dict] | None = None,
    user_message: str | None = None,
    representation: str = "FREE_FORM_LANGUAGE",
    canonical_ids_present: bool = False,
    procedure_id_present: bool = False,
    typed_schema_present: bool = False,
) -> models.InvocationRecord:
    adapter, model_id, parameters = ctx.provider_for(role)
    prompt = ctx.prompts.get(prompt_id)
    system_text = prompt.render(**variables)
    messages = [{"role": "system", "content": system_text}]
    if user_message is not None:
        messages.append({"role": "user", "content": user_message})
    response_schema = None
    schema_path = ctx.root / "schemas" / prompt.response_schema
    if prompt.response_schema.endswith(".json") and schema_path.is_file():
        response_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    record = adapter.invoke(
        role=role,
        model_id=model_id,
        messages=messages,
        tools=tools,
        response_schema=response_schema,
        parameters=parameters,
        metadata={
            "run_id": ctx.run_id,
            "cell_id": result.cell.cell_id,
            "timestamp": _now(),
            "response_kind": response_kind,
            "response_schema_id": prompt.response_schema,
            "mock_key": f"{role}:{result.cell.cell_id}:{stage_id}",
            "stage_id": stage_id,
        },
    )
    result.invocations.append(record)
    output_payload = record.normalized_text or canonical_json(record.tool_calls)
    result.ledger.append(
        models.RepresentationLedgerRecord(
            run_id=ctx.run_id,
            cell_id=result.cell.cell_id,
            stage_id=stage_id,
            stage_index=len(result.ledger),
            authoritative_representation=representation,
            canonical_ids_present=canonical_ids_present,
            procedure_id_present=procedure_id_present,
            typed_schema_present=typed_schema_present,
            input_content_hash=sha256_text(system_text + (user_message or "")),
            output_content_hash=sha256_text(output_payload),
        )
    )
    failure_category = provider_failure_category(record.finish_reason)
    if failure_category:
        result.schema_valid = False
        result.error_category = failure_category
        result.stage_outputs.append({
            "stage_id": stage_id,
            "status": "PROVIDER_FAILURE",
            "role": role,
            "provider": record.provider,
            "model_id": record.requested_model_id,
            "finish_reason": record.finish_reason,
            "error": record.parse_error,
        })
        raise ProviderInvocationFailure(
            result,
            failure_category,
            record.parse_error or failure_category,
        )
    return record


def _parse_decision(
    record: models.InvocationRecord, *, strict_typed_boundary: bool = False
) -> tuple[str | None, dict | None, str | None, str | None, bool]:
    """Return (decision, tool_call, question, reason_code, schema_valid)."""
    if record.tool_calls:
        if strict_typed_boundary and len(record.tool_calls) != 1:
            return None, None, None, None, False
        return "ACT", record.tool_calls[0], None, None, True
    obj, err = extract_json_object(record.normalized_text)
    if obj is None:
        return None, None, None, None, False
    decision = obj.get("decision")
    if decision == "ACT" and obj.get("tool"):
        return "ACT", {"tool": obj["tool"], "arguments": obj.get("arguments", {})}, None, None, True
    if decision in ("CLARIFY", "REFUSE"):
        question = obj.get("question")
        reason = obj.get("reason_code")
        if strict_typed_boundary:
            if set(obj) != {"decision", "question", "reason_code"}:
                return None, None, None, None, False
            if decision == "CLARIFY" and (
                not isinstance(question, str) or not question.strip() or reason is not None
            ):
                return None, None, None, None, False
            if decision == "REFUSE" and (
                question is not None or not isinstance(reason, str) or not reason.strip()
            ):
                return None, None, None, None, False
        return decision, None, question, reason, True
    return None, None, None, None, False


def _fresh_simulator(ctx: RunContext, case: models.CanonicalCase) -> SupportSimulator:
    return SupportSimulator(ctx.bench.domain, case.initial_state, ctx.run_clock)


def _typed_tools(ctx: RunContext) -> list[dict]:
    interface = ctx.bench.interfaces.get("TYPED_SUPPORT_TOOLS_V1")
    if interface is None:
        return []
    return [
        {"name": tool["name"], "description": tool["description"], "input_schema": tool["input_schema"]}
        for tool in interface.tools
    ]


def _apply_tool_call(ctx: RunContext, result: CellResult, sim: SupportSimulator) -> None:
    if result.decision == "ACT" and result.tool_call:
        tool_result = sim.call_tool(result.tool_call["tool"], result.tool_call.get("arguments", {}))
        if not tool_result.accepted:
            result.error_category = tool_result.error_category
    result.final_state = sim.snapshot()
    result.simulator_events = [event.to_dict() for event in sim.events]


def _common_vars(ctx: RunContext, case: models.CanonicalCase, context: models.FrozenContext) -> dict[str, str]:
    return {
        "domain_summary": domaintext.domain_summary(ctx.bench.domain),
        "known_state": domaintext.state_json(case.initial_state),
        "shared_context": domaintext.context_text(context),
    }


# ---------------------------------------------------------------- direct (A0/A1, M*)


def run_direct(ctx: RunContext, cell: MatrixCell, *, clarify_policy: bool,
               extra_context: str | None = None) -> CellResult:
    result = CellResult(cell=cell)
    case = ctx.bench.cases[cell.case_id]
    request = ctx.bench.requests[cell.request_id]
    context = ctx.bench.context_for_request(request)
    sim = _fresh_simulator(ctx, case)
    variables = _common_vars(ctx, case, context)
    if extra_context:
        variables["shared_context"] = variables["shared_context"] + "\n\n" + extra_context
    prompt_id = "direct-clarify-executor.v1" if clarify_policy else "direct-executor.v1"
    record = _invoke(
        ctx, result,
        role=cell.model_role,
        prompt_id=prompt_id,
        variables=variables,
        response_kind="direct_clarify_executor" if clarify_policy else "direct_executor",
        stage_id="executor",
        tools=_typed_tools(ctx),
        user_message=request.text,
        representation="FREE_FORM_LANGUAGE",
    )
    decision, tool_call, question, reason, valid = _parse_decision(record)
    result.decision, result.tool_call = decision, tool_call
    result.question, result.reason_code, result.schema_valid = question, reason, valid
    _apply_tool_call(ctx, result, sim)
    return result


# ---------------------------------------------------------------- canonical (B/C/D/E)


def _gold_resolution(case: models.CanonicalCase) -> models.CanonicalResolution:
    return models.CanonicalResolution.model_validate(domaintext.gold_canonical_resolution(case))


def _runtime_canonicalize(
    ctx: RunContext, result: CellResult, case, request, context, *,
    user_text: str | None = None,
    shared_context_text: str | None = None,
    stage_id: str = "canonicalizer",
) -> models.CanonicalResolution | None:
    request_text = user_text if user_text is not None else request.text
    shared_text = (
        shared_context_text
        if shared_context_text is not None
        else domaintext.context_text(context)
    )
    record = _invoke(
        ctx, result,
        role="boundary_canonicalizer",
        prompt_id="canonicalizer.v2",
        variables={
            "ontology": domaintext.ontology_text(ctx.bench.domain),
            "user_request": request_text,
            "shared_context": shared_text,
            "known_state": domaintext.state_json(case.initial_state),
        },
        response_kind="canonical_resolution",
        stage_id=stage_id,
        representation="FREE_FORM_LANGUAGE",
    )
    obj, parse_error = extract_json_object(record.normalized_text)
    resolution, validation_error = canonical.parse_resolution(obj)
    if resolution is None:
        result.canonicalization = obj
        result.schema_valid = False
        result.error_category = "invalid_canonical_resolution"
        result.interface_events.append({
            "kind": "canonical_resolution",
            "error": validation_error or parse_error or "invalid canonical resolution",
        })
        return None
    resolution = canonical.enforce_grounding(
        resolution,
        domain=ctx.bench.domain,
        user_request=request_text,
        shared_context_text=shared_text,
        visible_state=context.visible_state,
        known_state=case.initial_state,
    )
    result.canonicalization = resolution.model_dump(mode="json")
    return resolution


def run_canonical(ctx: RunContext, cell: MatrixCell) -> CellResult:
    """B_RUNTIME, B_GOLD, C_RUNTIME, C_GOLD, D_DEFINITION_ONLY, E_ORGANIZATION_TERM."""
    result = CellResult(cell=cell)
    case = ctx.bench.cases[cell.case_id]
    arch = cell.architecture
    gold_mode = cell.intent_mode == "gold"
    if gold_mode:
        resolution = _gold_resolution(case)
        context = ctx.bench.contexts.get("CTX-EMPTY-001")
        sim = _fresh_simulator(ctx, case)
    else:
        request = ctx.bench.requests[cell.request_id]
        context = ctx.bench.context_for_request(request)
        sim = _fresh_simulator(ctx, case)
        resolution = _runtime_canonicalize(ctx, result, case, request, context)
        if resolution is None:
            result.final_state = sim.snapshot()
            result.simulator_events = [event.to_dict() for event in sim.events]
            return result
        if resolution.mapping_outcome == models.MappingOutcome.NEEDS_CLARIFICATION:
            result.decision = "CLARIFY"
            result.question = resolution.question
            result.schema_valid = True
            result.final_state = sim.snapshot()
            result.simulator_events = [event.to_dict() for event in sim.events]
            return result
    intent = canonical.intent_payload(resolution)

    variables = {
        "canonical_resolution": json.dumps(intent, indent=2, sort_keys=True),
        "operation_definitions": domaintext.operation_definitions_text(ctx.bench.domain),
        "known_state": domaintext.state_json(case.initial_state),
    }
    rendered = arch in (
        "C_RUNTIME",
        "C_GOLD",
        "D_DEFINITION_ONLY",
        "E_ORGANIZATION_TERM",
        "F_MODEL_DISCOVERED",
    )
    if rendered:
        rendering = (
            ctx.bench.renderings.get(cell.rendering_id or "")
            if cell.rendering_id
            else ctx.bench.rendering_for_operation(
                intent["operation_id"], cell.rendering_category or "CANONICAL_LABEL"
            )
        )
        if rendering is None:
            result.schema_valid = False
            result.error_category = "runtime_rendering_not_found"
            result.final_state = sim.snapshot()
            result.simulator_events = [event.to_dict() for event in sim.events]
            return result
        rendered_text = domaintext.rendering_text(rendering, intent)
        result.actual_rendering_id = rendering.rendering_id
        result.actual_rendering_category = rendering.category.value
        result.actual_rendering_text = rendered_text
        variables["model_facing_rendering"] = rendered_text
        prompt_id, kind = "rendered-executor.v1", "rendered_executor"
    else:
        prompt_id, kind = "canonical-executor.v1", "canonical_executor"
    record = _invoke(
        ctx, result,
        role=cell.model_role,
        prompt_id=prompt_id,
        variables=variables,
        response_kind=kind,
        stage_id="executor",
        tools=_typed_tools(ctx),
        representation="CANONICAL_STATE",
        canonical_ids_present=True,
    )
    decision, tool_call, question, reason, valid = _parse_decision(record)
    result.decision, result.tool_call = decision, tool_call
    result.question, result.reason_code, result.schema_valid = question, reason, valid
    _apply_tool_call(ctx, result, sim)
    return result


# ---------------------------------------------------------------- memory (M0-M4)


def _select_memory_records(ctx: RunContext, request_text: str, *, personalized: bool,
                           user_id: str = "user-phillip", top_k: int = 2) -> tuple[list, list[dict]]:
    """Deterministic lexical retrieval with scope/status/effective-date checks (§32.5-32.6)."""
    scored = []
    events = []
    text_tokens = set(request_text.lower().split())
    for record in sorted(ctx.bench.memory.values(), key=lambda r: r.memory_id):
        surface_tokens = set(record.surface_form.lower().split())
        overlap = len(surface_tokens & text_tokens)
        valid_scope = record.scope.user_id is None or (personalized and record.scope.user_id == user_id)
        valid_status = record.status == "CONFIRMED"
        valid_date = record.effective_to is None
        event = {
            "memory_id": record.memory_id, "overlap": overlap,
            "valid_scope": valid_scope, "valid_status": valid_status, "valid_date": valid_date,
            "injected": False,
        }
        if overlap > 0 and valid_scope and valid_status and valid_date:
            scored.append((overlap, record.memory_id, record))
        events.append(event)
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [record for _o, _i, record in scored[:top_k]]
    selected_ids = {record.memory_id for record in selected}
    for event in events:
        event["injected"] = event["memory_id"] in selected_ids
    return selected, events


def run_memory(ctx: RunContext, cell: MatrixCell) -> CellResult:
    condition = cell.architecture
    if condition == "M0_NO_MEMORY":
        return run_direct(ctx, cell, clarify_policy=True)
    if condition == "M3_CANONICAL_RESOLVER":
        # Explicit canonical resolution before execution (§32.2 M3) = B_RUNTIME path.
        cell_like = cell
        result = run_canonical(ctx, MatrixCell(**{**cell.to_dict(), "intent_mode": "runtime"}))
        result.cell = cell_like
        return result
    request = ctx.bench.requests[cell.request_id]
    if condition == "M1_STATIC_GLOSSARY":
        records = [rec for rec in sorted(ctx.bench.memory.values(), key=lambda r: r.memory_id)
                   if rec.status == "CONFIRMED" and rec.scope.user_id is None]
        extra = "ORGANIZATION GLOSSARY\n" + domaintext.glossary_text(records)
        result = run_direct(ctx, cell, clarify_policy=True, extra_context=extra)
        return result
    personalized = condition == "M4_PERSONALIZED_MEMORY"
    selected, events = _select_memory_records(ctx, request.text, personalized=personalized)
    extra = "RETRIEVED ORGANIZATION MAPPINGS\n" + domaintext.glossary_text(selected)
    result = run_direct(ctx, cell, clarify_policy=True, extra_context=extra)
    result.procedure_events = []  # unused
    result.interface_events = []
    result.stage_outputs.append({"stage": "memory_retrieval", "events": events})
    return result


# ---------------------------------------------------------------- proposals (P0-P4)


def _validate_proposal(obj: dict | None) -> tuple[dict | None, str | None]:
    if obj is None:
        return None, "parse_error"
    try:
        jsonschema.validate(obj, GENERIC_PROPOSAL_SCHEMA)
    except jsonschema.ValidationError as exc:
        return None, f"proposal_schema: {exc.message}"
    return obj, None


P0_POLICY = (
    "Satisfy the request using your best judgment. Select the decision value that "
    "best represents your response. No additional clarification or refusal policy "
    "is supplied in this condition."
)
P1_POLICY = (
    "When exactly one operation is supported, every required argument is known, and "
    "the operation is permitted, use ACT.\n"
    "When required information is missing or more than one interpretation remains "
    "reasonable, use CLARIFY and do not propose an action.\n"
    "When exactly one requested operation is understood but a domain rule or state "
    "precondition prohibits it, use REFUSE.\n"
    "Do not invent missing identifiers or arguments."
)


def _apply_proposal(ctx: RunContext, result: CellResult, sim: SupportSimulator, obj: dict | None) -> None:
    proposal, error = _validate_proposal(obj)
    if proposal is None:
        result.schema_valid = False
        result.error_category = "proposal_parse_error"
        result.interface_events.append({"kind": "generic_proposal", "error": error})
        result.final_state = sim.snapshot()
        result.simulator_events = [event.to_dict() for event in sim.events]
        return
    result.proposal = proposal
    result.decision = proposal["decision"]
    result.question = proposal.get("question")
    result.reason_code = proposal.get("reason_code")
    if proposal["decision"] == "ACT":
        op_id = proposal.get("operation_id")
        op = ctx.bench.domain.operations.get(op_id or "")
        if op is None:
            result.error_category = "unknown_operation_mapping"
            result.interface_events.append({"kind": "generic_proposal", "error": f"unknown operation {op_id}"})
        else:
            result.tool_call = {"tool": op.tool, "arguments": proposal.get("arguments", {})}
            tool_result = sim.call_tool(op.tool, proposal.get("arguments", {}))
            if not tool_result.accepted:
                result.error_category = tool_result.error_category
                result.interface_events.append({"kind": "generic_proposal", "error": tool_result.detail})
    result.final_state = sim.snapshot()
    result.simulator_events = [event.to_dict() for event in sim.events]


def _select_procedure(ctx: RunContext, result: CellResult, case: models.CanonicalCase,
                      resolution: dict) -> models.Procedure | None:
    """Gold: deterministic registry lookup. Runtime: procedure_router role (§33.8)."""
    if result.cell.procedure_selection != "runtime":
        procedure = ctx.bench.procedure_for_operation(resolution.get("operation_id", ""))
        result.actual_procedure_id = procedure.procedure_id if procedure else None
        result.procedure_events.append({
            "mode": "gold", "operation_id": resolution.get("operation_id"),
            "selected": procedure.procedure_id if procedure else None, "correct": procedure is not None,
        })
        return procedure
    registry = "\n".join(
        f"- {proc.procedure_id}: applies to {', '.join(proc.applies_to_operation_ids)}"
        for proc in sorted(ctx.bench.procedures.values(), key=lambda p: p.procedure_id)
    )
    record = _invoke(
        ctx, result,
        role="procedure_router",
        prompt_id="procedure-router.v1",
        variables={"canonical_intent": json.dumps(resolution, sort_keys=True), "procedure_registry": registry},
        response_kind="procedure_selection",
        stage_id="procedure_router",
        representation="CANONICAL_STATE",
        canonical_ids_present=True,
    )
    obj, _err = extract_json_object(record.normalized_text)
    selected_id = (obj or {}).get("procedure_id")
    procedure = ctx.bench.procedures.get(selected_id or "")
    result.actual_procedure_id = procedure.procedure_id if procedure else None
    gold = ctx.bench.procedure_for_operation(resolution.get("operation_id", ""))
    result.procedure_events.append({
        "mode": "runtime", "operation_id": resolution.get("operation_id"),
        "selected": selected_id, "correct": bool(procedure and gold and selected_id == gold.procedure_id),
    })
    return procedure


def run_formalization(ctx: RunContext, cell: MatrixCell) -> CellResult:
    result = CellResult(cell=cell)
    case = ctx.bench.cases[cell.case_id]
    request = ctx.bench.requests[cell.request_id]
    context = ctx.bench.context_for_request(request)
    sim = _fresh_simulator(ctx, case)
    condition = cell.architecture
    domain_rules = domaintext.domain_summary(ctx.bench.domain)
    known_state = domaintext.state_json(case.initial_state)
    shared_context = domaintext.context_text(context)
    common_facts = {
        "domain_rules": domain_rules,
        "known_state": known_state,
        "shared_context": shared_context,
    }
    # This fingerprint is identical for all P-ladder conditions for a given
    # request. It makes the information-parity control inspectable instead of
    # merely asserting that interface IDs look plausible.
    result.stage_outputs.append({
        "stage": "information_parity",
        "output": {
            "verified": True,
            "common_facts_hash": sha256_text(canonical_json(common_facts)),
            "fact_fields": sorted(common_facts),
        },
    })

    if condition in ("P0_RAW_PROPOSAL", "P1_CLARIFY_PROPOSAL"):
        policy = P0_POLICY if condition == "P0_RAW_PROPOSAL" else P1_POLICY
        record = _invoke(
            ctx, result,
            role=cell.model_role,
            prompt_id="action-proposal-executor.v1",
            variables={
                "task_input": request.text,
                "domain_rules": domain_rules,
                "known_state": known_state,
                "shared_context": shared_context,
                "clarification_policy": policy,
            },
            response_kind="generic_action_proposal",
            stage_id="proposal_executor",
            representation="FREE_FORM_LANGUAGE",
        )
        obj, _err = extract_json_object(record.normalized_text)
        _apply_proposal(ctx, result, sim, obj)
        return result

    # P2-P4 need canonical intent (runtime or gold).
    if cell.intent_mode == "gold":
        envelope: models.CanonicalResolution | None = _gold_resolution(case)
    else:
        envelope = _runtime_canonicalize(ctx, result, case, request, context)
        if envelope is None:
            result.final_state = sim.snapshot()
            result.simulator_events = [event.to_dict() for event in sim.events]
            return result
    assert envelope is not None
    if envelope.mapping_outcome == models.MappingOutcome.NEEDS_CLARIFICATION:
        result.decision = "CLARIFY"
        result.question = envelope.question
        result.schema_valid = True
        result.final_state = sim.snapshot()
        result.simulator_events = [event.to_dict() for event in sim.events]
        return result
    resolution = canonical.intent_payload(envelope)

    if condition == "P2_CANONICAL_PROPOSAL":
        record = _invoke(
            ctx, result,
            role=cell.model_role,
            prompt_id="action-proposal-executor.v1",
            variables={
                "task_input": json.dumps(resolution, indent=2, sort_keys=True),
                "domain_rules": domain_rules,
                "known_state": known_state,
                "shared_context": shared_context,
                "clarification_policy": P1_POLICY,
            },
            response_kind="generic_action_proposal",
            stage_id="proposal_executor",
            representation="CANONICAL_STATE",
            canonical_ids_present=True,
        )
        obj, _err = extract_json_object(record.normalized_text)
        _apply_proposal(ctx, result, sim, obj)
        return result

    if condition == "P2F_CANONICAL_FACTS_PROPOSAL":
        fact_source = ctx.bench.procedure_for_operation(
            resolution.get("operation_id", "")
        )
        if fact_source is None:
            result.error_category = "procedure_fact_control_unavailable"
            result.decision = "CLARIFY"
            result.final_state = sim.snapshot()
            result.simulator_events = [event.to_dict() for event in sim.events]
            return result
        fact_control = domaintext.procedure_fact_control_text(fact_source)
        record = _invoke(
            ctx, result,
            role=cell.model_role,
            prompt_id="action-proposal-executor.v1",
            variables={
                "task_input": json.dumps(resolution, indent=2, sort_keys=True),
                "domain_rules": domain_rules + "\n\nUNORDERED TASK FACTS\n" + fact_control,
                "known_state": known_state,
                "shared_context": shared_context,
                "clarification_policy": P1_POLICY,
            },
            response_kind="generic_action_proposal",
            stage_id="fact_control_executor",
            representation="CANONICAL_STATE",
            canonical_ids_present=True,
        )
        obj, _err = extract_json_object(record.normalized_text)
        _apply_proposal(ctx, result, sim, obj)
        return result

    procedure = _select_procedure(ctx, result, case, resolution)
    if procedure is None:
        result.error_category = "procedure_selection_failed"
        result.decision = "CLARIFY"
        result.final_state = sim.snapshot()
        result.simulator_events = [event.to_dict() for event in sim.events]
        return result
    procedure_content = domaintext.procedure_text(procedure, cell.procedure_packaging)

    if condition == "P3_CANONICAL_PROCEDURE_PROPOSAL":
        record = _invoke(
            ctx, result,
            role=cell.model_role,
            prompt_id="procedure-proposal-executor.v2",
            variables={
                "canonical_intent": json.dumps(resolution, indent=2, sort_keys=True),
                "frozen_procedure": procedure_content,
                "domain_rules": domain_rules,
                "known_state": known_state + "\n\nSHARED CONTEXT\n" + shared_context,
            },
            response_kind="generic_action_proposal",
            stage_id="procedure_executor",
            representation="CANONICAL_STATE_PLUS_PROCEDURE",
            canonical_ids_present=True,
            procedure_id_present=True,
        )
        obj, _err = extract_json_object(record.normalized_text)
        _apply_proposal(ctx, result, sim, obj)
        return result

    # P4: typed tool interface
    record = _invoke(
        ctx, result,
        role=cell.model_role,
        prompt_id="procedure-tool-executor.v2",
        variables={
            "canonical_intent": json.dumps(resolution, indent=2, sort_keys=True),
            "frozen_procedure": procedure_content,
            "domain_rules": domain_rules,
            "known_state": known_state + "\n\nSHARED CONTEXT\n" + shared_context,
        },
        response_kind="procedure_tool",
        stage_id="procedure_executor",
        tools=_typed_tools(ctx),
        representation="TYPED_ACTION_INTERFACE",
        canonical_ids_present=True,
        procedure_id_present=True,
        typed_schema_present=True,
    )
    decision, tool_call, question, reason, valid = _parse_decision(
        record, strict_typed_boundary=True
    )
    result.decision, result.question, result.reason_code = decision, question, reason
    result.schema_valid = valid
    if decision == "ACT" and tool_call:
        interface = ctx.bench.interfaces["TYPED_SUPPORT_TOOLS_V1"]
        tool_def = next((t for t in interface.tools if t["name"] == tool_call["tool"]), None)
        if tool_def is None:
            result.error_category = "typed_tool_selection_error"
            result.interface_events.append({"kind": "typed_tool", "error": f"unknown tool {tool_call['tool']}"})
        else:
            try:
                jsonschema.validate(tool_call.get("arguments", {}), tool_def["input_schema"])
                result.tool_call = tool_call
                tool_result = sim.call_tool(tool_call["tool"], tool_call.get("arguments", {}))
                if not tool_result.accepted:
                    result.error_category = tool_result.error_category
            except jsonschema.ValidationError as exc:
                result.error_category = "typed_tool_validation_error"
                result.interface_events.append({"kind": "typed_tool", "error": exc.message})
    result.final_state = sim.snapshot()
    result.simulator_events = [event.to_dict() for event in sim.events]
    return result


# ---------------------------------------------------------------- persistence (LP*)


STAGES = ("triage", "policy", "planner")


def _policies_text(ctx: RunContext) -> str:
    return "\n".join(
        f"POLICY {policy_id}: {ctx.bench.domain.policies[policy_id].text}"
        for policy_id in sorted(ctx.bench.domain.policies)
    )


def run_persistence(ctx: RunContext, cell: MatrixCell) -> CellResult:
    result = CellResult(cell=cell)
    case = ctx.bench.cases[cell.case_id]
    request = ctx.bench.requests[cell.request_id]
    context = ctx.bench.context_for_request(request)
    sim = _fresh_simulator(ctx, case)
    condition = cell.architecture
    known_state = domaintext.state_json(case.initial_state)

    prose_mode = condition in (
        "LP0_LANGUAGE_THROUGHOUT",
        "LP0G_GOLD_START_LANGUAGE",
        "LP0B_GOLD_START_LANGUAGE_BALANCED",
        "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM",
    )
    balanced_prose = condition in (
        "LP0B_GOLD_START_LANGUAGE_BALANCED",
        "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM",
    )
    visible_verbatim_contract = (
        condition == "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM"
    )
    procedure = None
    if condition in ("LP2_CANONICAL_PROCEDURE", "LP3_CANONICAL_PROCEDURE_TOOL"):
        procedure = ctx.bench.procedure_for_operation(case.canonical.operation_id)
        result.actual_procedure_id = procedure.procedure_id if procedure else None
        result.procedure_events.append({
            "mode": "gold", "operation_id": case.canonical.operation_id,
            "selected": procedure.procedure_id if procedure else None, "correct": procedure is not None,
        })

    # ---- resolve starting representation
    if condition == "LP0_LANGUAGE_THROUGHOUT":
        working = request.text  # raw user language stays authoritative
        resolution = None
    elif condition in (
        "LP0G_GOLD_START_LANGUAGE",
        "LP0B_GOLD_START_LANGUAGE_BALANCED",
        "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM",
    ):
        resolution = None
        op = ctx.bench.domain.operations[case.canonical.operation_id]
        args = ", ".join(f"{k}={v}" for k, v in sorted(case.canonical.arguments.items()))
        working = (
            f"Please perform this task: {op.display_name.lower()} for "
            f"{case.canonical.entity_id}" + (f" with {args}" if args else "") + "."
        )
    else:
        if cell.intent_mode == "gold":
            envelope = _gold_resolution(case)
        else:
            envelope = _runtime_canonicalize(ctx, result, case, request, context)
            if envelope is None:
                result.final_state = sim.snapshot()
                result.simulator_events = [event.to_dict() for event in sim.events]
                return result
        if envelope.mapping_outcome == models.MappingOutcome.NEEDS_CLARIFICATION:
            result.decision = "CLARIFY"
            result.question = envelope.question
            result.schema_valid = True
            result.final_state = sim.snapshot()
            result.simulator_events = [event.to_dict() for event in sim.events]
            return result
        resolution = canonical.intent_payload(envelope)
        working = json.dumps(resolution, indent=2, sort_keys=True)

    representation = (
        "FREE_FORM_LANGUAGE" if prose_mode
        else ("CANONICAL_STATE_PLUS_PROCEDURE" if procedure else "CANONICAL_STATE")
    )

    stage_kinds = {"triage": "triage_result", "policy": "policy_result", "planner": "plan_result"}
    stage_prompts = {"triage": "triage.v1", "policy": "policy.v2", "planner": "planner.v2"}
    typed_outputs: dict[str, dict] = {}
    preservation_contract = domaintext.preservation_contract_text(
        ctx.bench.domain.operations[case.canonical.operation_id]
    )
    for stage in STAGES:
        if stage == "triage":
            variables = {
                "request_or_canonical_input": working,
                "canonical_entity_definitions": domaintext.ontology_text(ctx.bench.domain),
                "known_state": known_state,
            }
        elif stage == "policy":
            triage_payload = (
                working if prose_mode
                else json.dumps(
                    {"canonical_state": resolution, "triage": typed_outputs.get("triage", {})},
                    sort_keys=True,
                )
            )
            variables = {
                "triage_result": triage_payload,
                "policies": _policies_text(ctx),
                "known_state": known_state,
            }
        else:
            triage_payload = (
                working if prose_mode
                else json.dumps(
                    {"canonical_state": resolution, "triage": typed_outputs.get("triage", {})},
                    sort_keys=True,
                )
            )
            variables = {
                "triage_result": triage_payload,
                "policy_result": working if prose_mode else json.dumps(typed_outputs.get("policy", {}), sort_keys=True),
                "allowed_operations": domaintext.operation_definitions_text(ctx.bench.domain),
                "known_state": known_state,
            }
            if procedure:
                variables["allowed_operations"] += "\n\nFROZEN PROCEDURE\n" + domaintext.procedure_text(procedure)
        selected_prompt = (
            {
                "triage": (
                    "triage-language-handoff-verbatim.v1"
                    if visible_verbatim_contract else "triage-language-handoff.v1"
                ),
                "policy": (
                    "policy-language-handoff-verbatim.v1"
                    if visible_verbatim_contract else "policy-language-handoff.v2"
                ),
                "planner": (
                    "planner-language-handoff-verbatim.v1"
                    if visible_verbatim_contract else "planner-language-handoff.v2"
                ),
            }[stage]
            if balanced_prose
            else stage_prompts[stage]
        )
        if visible_verbatim_contract:
            variables["preservation_contract"] = preservation_contract
        record = _invoke(
            ctx, result,
            role=cell.model_role,
            prompt_id=selected_prompt,
            variables=variables,
            response_kind="stage_language_handoff" if balanced_prose else stage_kinds[stage],
            stage_id=stage,
            representation=representation,
            canonical_ids_present=not prose_mode,
            procedure_id_present=procedure is not None,
        )
        obj, _err = extract_json_object(record.normalized_text)
        if balanced_prose:
            envelope_obj = obj or {}
            stage_result = envelope_obj.get("stage_result")
            handoff_text = envelope_obj.get("handoff_text")
            if (
                set(envelope_obj) != {"stage_result", "handoff_text"}
                or not isinstance(stage_result, dict)
                or not isinstance(handoff_text, str)
                or not handoff_text.strip()
            ):
                result.schema_valid = False
                result.error_category = "invalid_stage_language_handoff"
                result.stage_outputs.append({"stage": stage, "output": obj})
                result.final_state = sim.snapshot()
                result.simulator_events = [event.to_dict() for event in sim.events]
                return result
            typed_outputs[stage] = stage_result
            working = handoff_text.strip()
            result.stage_outputs.append({"stage": stage, "output": stage_result})
            result.stage_outputs.append({"stage": f"{stage}_handoff", "output": working})
        else:
            typed_outputs[stage] = obj or {}
            result.stage_outputs.append({"stage": stage, "output": obj})
        if prose_mode and not balanced_prose:
            handoff_record = _invoke(
                ctx, result,
                role=cell.model_role,
                prompt_id="language-handoff.v1",
                variables={
                    "stage_name": stage,
                    "incoming_handoff": working,
                    "stage_result": json.dumps(obj or {}, sort_keys=True),
                    "known_state": known_state,
                },
                response_kind="plain_text_handoff",
                stage_id=f"{stage}_handoff",
                representation="FREE_FORM_LANGUAGE",
            )
            working = handoff_record.normalized_text or working
            result.stage_outputs.append({"stage": f"{stage}_handoff", "output": working})

    # ---- final action boundary
    if condition == "LP3_CANONICAL_PROCEDURE_TOOL":
        plan = typed_outputs.get("planner", {})
        record = _invoke(
            ctx, result,
            role=cell.model_role,
            prompt_id="executor.v2",
            variables={
                "plan_result": json.dumps(plan, sort_keys=True),
                "operation_definitions": domaintext.operation_definitions_text(ctx.bench.domain),
                "known_state": known_state,
            },
            response_kind="plan_executor",
            stage_id="executor",
            tools=_typed_tools(ctx),
            representation="TYPED_ACTION_INTERFACE",
            canonical_ids_present=True,
            procedure_id_present=procedure is not None,
            typed_schema_present=True,
        )
        decision, tool_call, question, reason, valid = _parse_decision(
            record, strict_typed_boundary=True
        )
        result.decision, result.tool_call = decision, tool_call
        result.question, result.reason_code, result.schema_valid = question, reason, valid
        _apply_tool_call(ctx, result, sim)
        return result

    # LP0/LP0G/LP1/LP2 end in the generic action proposal (§33.6).
    task_input = (
        working if prose_mode
        else json.dumps(
            {"canonical_state": resolution, "plan": typed_outputs.get("planner", {})},
            sort_keys=True,
        )
    )
    record = _invoke(
        ctx, result,
        role=cell.model_role,
        prompt_id=(
            "action-proposal-executor-verbatim.v1"
            if visible_verbatim_contract else "action-proposal-executor.v1"
        ),
        variables={
            "task_input": task_input,
            "domain_rules": domaintext.domain_summary(ctx.bench.domain),
            "known_state": known_state,
            "shared_context": domaintext.context_text(context),
            "clarification_policy": P1_POLICY,
            **(
                {"preservation_contract": preservation_contract}
                if visible_verbatim_contract else {}
            ),
        },
        response_kind="generic_action_proposal",
        stage_id="final_proposal",
        representation="FREE_FORM_LANGUAGE" if prose_mode else representation,
        canonical_ids_present=not prose_mode,
        procedure_id_present=procedure is not None,
    )
    obj, _err = extract_json_object(record.normalized_text)
    _apply_proposal(ctx, result, sim, obj)
    return result


# ---------------------------------------------------------------- agent loop (Experiment 3)


def run_agent_loop(ctx: RunContext, cell: MatrixCell) -> CellResult:
    result = CellResult(cell=cell)
    case = ctx.bench.cases[cell.case_id]
    request = ctx.bench.requests[cell.request_id]
    sim = _fresh_simulator(ctx, case)
    condition = cell.architecture
    known_state = domaintext.state_json(case.initial_state)

    canonical_intent = None
    if condition != "AL_RAW":
        if cell.intent_mode == "gold":
            envelope = _gold_resolution(case)
        elif cell.intent_mode == "runtime":
            context = ctx.bench.context_for_request(request)
            envelope = _runtime_canonicalize(ctx, result, case, request, context)
            if envelope is None:
                result.final_state = sim.snapshot()
                return result
        else:
            raise ValueError(f"{condition} requires gold or runtime canonical intent")
        if envelope.mapping_outcome == models.MappingOutcome.NEEDS_CLARIFICATION:
            result.decision = "CLARIFY"
            result.question = envelope.question
            result.schema_valid = True
            result.final_state = sim.snapshot()
            return result
        canonical_intent = canonical.intent_payload(envelope)
    label = ctx.bench.domain.operations[case.canonical.operation_id].display_name.lower()
    rendering_line = ""
    if condition == "AL_RENDERED":
        rendering = (
            ctx.bench.renderings.get(cell.rendering_id or "")
            if cell.rendering_id
            else ctx.bench.rendering_for_operation(
                canonical_intent["operation_id"],
                cell.rendering_category or "CANONICAL_LABEL",
            )
        )
        if rendering is None:
            result.schema_valid = False
            result.error_category = "runtime_rendering_not_found"
            result.final_state = sim.snapshot()
            return result
        rendered_text = domaintext.rendering_text(rendering, canonical_intent)
        result.actual_rendering_id = rendering.rendering_id
        result.actual_rendering_category = rendering.category.value
        result.actual_rendering_text = rendered_text
        rendering_line = "\nMODEL-FACING RENDERING: " + rendered_text

    typed_outputs: dict[str, dict] = {}
    used_labels = [label]
    stage_kinds = {"triage": "triage_result", "policy": "policy_result", "planner": "plan_result"}
    stage_prompts = {"triage": "triage.v1", "policy": "policy.v2", "planner": "planner.v2"}
    for stage in STAGES:
        extra = f"\nOPERATION LABEL IN USE: {label}" if condition == "AL_DRIFT" else ""
        raw_suffix = f"\nORIGINAL USER WORDING: {request.text}" if condition == "AL_RAW" else ""
        # Canonical ID propagation (§26.8): later stages receive canonical IDs and
        # definitions in AL_CANONICAL/AL_RENDERED/AL_DRIFT; AL_RAW re-passes prose.
        triage_payload = json.dumps(
            typed_outputs.get("triage", {}) if condition == "AL_RAW"
            else {"canonical_state": canonical_intent, "triage": typed_outputs.get("triage", {})},
            sort_keys=True,
        )
        if stage == "triage":
            variables = {
                "request_or_canonical_input": (
                    request.text if condition == "AL_RAW"
                    else json.dumps(canonical_intent, sort_keys=True) + extra + rendering_line
                ),
                "canonical_entity_definitions": domaintext.ontology_text(ctx.bench.domain),
                "known_state": known_state,
            }
        elif stage == "policy":
            variables = {
                "triage_result": triage_payload + extra + raw_suffix,
                "policies": _policies_text(ctx),
                "known_state": known_state,
            }
        else:
            variables = {
                "triage_result": triage_payload + raw_suffix,
                "policy_result": json.dumps(typed_outputs.get("policy", {}), sort_keys=True) + extra,
                "allowed_operations": domaintext.operation_definitions_text(ctx.bench.domain) + rendering_line,
                "known_state": known_state,
            }
        record = _invoke(
            ctx, result,
            role=cell.model_role,
            prompt_id=stage_prompts[stage],
            variables=variables,
            response_kind=stage_kinds[stage],
            stage_id=stage,
            representation="FREE_FORM_LANGUAGE" if condition == "AL_RAW" else "CANONICAL_STATE",
            canonical_ids_present=condition != "AL_RAW",
        )
        obj, _err = extract_json_object(record.normalized_text)
        typed_outputs[stage] = obj or {}
        result.stage_outputs.append({"stage": stage, "output": obj})
        if condition == "AL_DRIFT":
            drift_record = _invoke(
                ctx, result,
                role="authoring_generator",
                prompt_id="lexical-drift.v1",
                variables={
                    "canonical_id": canonical_intent["operation_id"],
                    "definition": ctx.bench.domain.operations[canonical_intent["operation_id"]].description,
                    "current_label": label,
                    "forbidden_labels": "\n".join(f"- {label}" for label in used_labels),
                },
                response_kind="drifted_label",
                stage_id=f"{stage}_drift",
                representation="CANONICAL_STATE",
                canonical_ids_present=True,
            )
            drift_obj, _err = extract_json_object(drift_record.normalized_text)
            alternate = (drift_obj or {}).get("alternate_label")
            valid_drift = bool(
                drift_obj
                and drift_obj.get("canonical_id") == canonical_intent["operation_id"]
                and isinstance(alternate, str)
                and alternate.strip()
                and alternate.casefold() not in {item.casefold() for item in used_labels}
            )
            result.stage_outputs.append({
                "stage": f"{stage}_drift",
                "output": drift_obj,
                "valid": valid_drift,
            })
            if not valid_drift:
                result.schema_valid = False
                result.error_category = "drift_generation_validation_error"
                result.final_state = sim.snapshot()
                return result
            label = alternate.strip()
            used_labels.append(label)

    record = _invoke(
        ctx, result,
        role=cell.model_role,
        prompt_id="executor.v2",
        variables={
            "plan_result": json.dumps(typed_outputs.get("planner", {}), sort_keys=True),
            "operation_definitions": (
                domaintext.operation_definitions_text(ctx.bench.domain)
                + (f"\nOPERATION LABEL IN USE: {label}" if condition == "AL_DRIFT" else "")
                + rendering_line
            ),
            "known_state": known_state,
        },
        response_kind="plan_executor",
        stage_id="executor",
        tools=_typed_tools(ctx),
        representation="FREE_FORM_LANGUAGE" if condition == "AL_RAW" else "CANONICAL_STATE",
        canonical_ids_present=condition != "AL_RAW",
    )
    decision, tool_call, question, reason, valid = _parse_decision(record)
    result.decision, result.tool_call = decision, tool_call
    result.question, result.reason_code, result.schema_valid = question, reason, valid
    _apply_tool_call(ctx, result, sim)
    return result


# ---------------------------------------------------------------- intent elicitation


ANSWER_KEYWORDS = {
    "entity_reference": ("incident", "record", "which", "id", "identify"),
    "destination_tier": ("tier", "level", "destination"),
    "destination_team": ("team",),
    "amount_usd": ("amount", "usd", "charge"),
    "approver_role": ("approver", "role", "manager"),
    "message": ("message", "comment", "ask", "information", "details"),
    "operation_choice": ("operation", "escalat", "reassign", "handled as"),
}


def _match_answer(ecase: models.ElicitationCase, question: str | None, targets: list[str] | None) -> tuple[str | None, list[str]]:
    answers = ecase.scripted_user_answers
    keys = targets or []
    if not keys and question:
        lowered = question.lower()
        for key, needles in ANSWER_KEYWORDS.items():
            if any(needle in lowered for needle in needles):
                keys.append(key)
    keys = [key for key in keys if any(key in answer_key for answer_key in answers)]
    # Combined answers match on the set of parts, order-independent.
    key_set = set(keys)
    for answer_key, answer in sorted(answers.items()):
        if "_and_" in answer_key and set(answer_key.split("_and_")) == key_set:
            return answer, keys
    for key in keys:
        if key in answers:
            return answers[key], [key]
    return None, keys


def run_elicitation(ctx: RunContext, cell: MatrixCell) -> CellResult:
    result = CellResult(cell=cell)
    ecase = ctx.bench.elicitation[cell.elicitation_case_id]
    case = ctx.bench.cases[cell.case_id]
    request = ctx.bench.requests[cell.request_id]
    base_context = ctx.bench.context_for_request(request)
    sim = _fresh_simulator(ctx, case)
    arch = cell.architecture

    current_text = request.text
    context_lines = [domaintext.context_text(base_context)]
    max_turns = ecase.maximum_clarification_turns
    resolved = False

    for turn in range(max_turns + 1):
        result.turns_used = turn + 1
        shared = "\n".join(context_lines)
        if arch in ("A0_DIRECT", "A1_DIRECT_CLARIFY"):
            prompt_id = "direct-clarify-executor.v1" if arch == "A1_DIRECT_CLARIFY" else "direct-executor.v1"
            record = _invoke(
                ctx, result,
                role=cell.model_role,
                prompt_id=prompt_id,
                variables={
                    "domain_summary": domaintext.domain_summary(ctx.bench.domain),
                    "known_state": domaintext.state_json(case.initial_state),
                    "shared_context": shared,
                },
                response_kind="direct_clarify_executor" if arch == "A1_DIRECT_CLARIFY" else "direct_executor",
                stage_id=f"turn{turn}_executor",
                tools=_typed_tools(ctx),
                user_message=current_text,
                representation="FREE_FORM_LANGUAGE",
            )
            decision, tool_call, question, reason, valid = _parse_decision(record)
            targets = None
        else:
            if arch == "B_EXTERNAL_GATE_GOLD" and turn == 0:
                gold = ecase.gold_initial_labels
                assessment = {
                    "adequacy": gold.get("adequacy"), "ambiguity": gold.get("ambiguity"),
                    "missing_information": gold.get("missing_information", []),
                    "recommended_behavior": gold.get("expected_behavior"),
                }
            else:
                assess_record = _invoke(
                    ctx, result,
                    role="adequacy_assessor",
                    prompt_id="adequacy-assessor.v1",
                    variables={
                        "user_request": current_text,
                        "shared_context": shared,
                        "domain_requirements": domaintext.domain_summary(ctx.bench.domain),
                        "known_state": domaintext.state_json(case.initial_state),
                    },
                    response_kind="adequacy_result",
                    stage_id=f"turn{turn}_assessor",
                    representation="FREE_FORM_LANGUAGE",
                )
                assessment, _err = extract_json_object(assess_record.normalized_text)
                assessment = assessment or {}
            result.elicitation_trace.append({"turn": turn, "assessment": assessment})
            if assessment.get("recommended_behavior") == "EXECUTE" or (
                assessment.get("adequacy") == "ADEQUATE"
                and assessment.get("ambiguity") == "UNAMBIGUOUS"
            ):
                envelope = _runtime_canonicalize(
                    ctx,
                    result,
                    case,
                    request,
                    base_context,
                    user_text=current_text,
                    shared_context_text=shared,
                    stage_id=f"turn{turn}_canonicalizer",
                )
                if envelope and envelope.mapping_outcome == models.MappingOutcome.MAPPED:
                    intent = canonical.intent_payload(envelope)
                    exec_record = _invoke(
                        ctx, result,
                        role=cell.model_role,
                        prompt_id="canonical-executor.v1",
                        variables={
                            "canonical_resolution": json.dumps(intent, indent=2, sort_keys=True),
                            "operation_definitions": domaintext.operation_definitions_text(ctx.bench.domain),
                            "known_state": domaintext.state_json(case.initial_state),
                        },
                        response_kind="canonical_executor",
                        stage_id=f"turn{turn}_executor",
                        tools=_typed_tools(ctx),
                        representation="CANONICAL_STATE",
                        canonical_ids_present=True,
                    )
                    decision, tool_call, question, reason, valid = _parse_decision(exec_record)
                    targets = None
                else:
                    decision, tool_call, question, reason, valid = (
                        "CLARIFY",
                        None,
                        envelope.question if envelope else None,
                        None,
                        envelope is not None,
                    )
                    targets = None
            else:
                clarify_record = _invoke(
                    ctx, result,
                    role="adequacy_assessor",
                    prompt_id="clarification-resolver.v1",
                    variables={
                        "user_request": current_text,
                        "shared_context": shared,
                        "adequacy_result": json.dumps(assessment, sort_keys=True),
                        "domain_requirements": domaintext.domain_summary(ctx.bench.domain),
                    },
                    response_kind="clarification_question",
                    stage_id=f"turn{turn}_clarifier",
                    representation="FREE_FORM_LANGUAGE",
                )
                obj, _err = extract_json_object(clarify_record.normalized_text)
                decision = "CLARIFY"
                tool_call, reason = None, None
                question = (obj or {}).get("question")
                targets = (obj or {}).get("targets")
                valid = obj is not None

        result.elicitation_trace.append({
            "turn": turn, "decision": decision, "question": question,
            "tool_call": tool_call,
        })
        if decision == "ACT" and tool_call:
            result.decision, result.tool_call, result.schema_valid = decision, tool_call, valid
            _apply_tool_call(ctx, result, sim)
            resolved = True
            break
        if decision == "REFUSE":
            result.decision, result.reason_code, result.schema_valid = decision, reason, valid
            break
        # CLARIFY: turn-limit check happens before another model invocation (§31.7)
        if turn >= max_turns:
            break
        answer, matched = _match_answer(ecase, question, targets)
        if answer is None:
            result.elicitation_trace.append({"turn": turn, "note": "no scripted answer matched"})
            break
        context_lines.append(f"user answered: {answer}")
        result.elicitation_trace.append({"turn": turn, "user_answer": answer, "targets": matched})
        result.decision = "CLARIFY"
        result.question = question

    result.resolved = resolved
    if result.final_state is None:
        result.final_state = sim.snapshot()
        result.simulator_events = [event.to_dict() for event in sim.events]
    return result


# ---------------------------------------------------------------- dispatch


def run_cell(ctx: RunContext, cell: MatrixCell) -> CellResult:
    arch = cell.architecture
    track = cell.track
    if track == "intent_elicitation":
        return run_elicitation(ctx, cell)
    if track == "agent_loop":
        return run_agent_loop(ctx, cell)
    if arch == "A0_DIRECT":
        return run_direct(ctx, cell, clarify_policy=False)
    if arch == "A1_DIRECT_CLARIFY":
        return run_direct(ctx, cell, clarify_policy=True)
    if arch in (
        "B_RUNTIME", "B_GOLD", "C_RUNTIME", "C_GOLD",
        "D_DEFINITION_ONLY", "E_ORGANIZATION_TERM", "F_MODEL_DISCOVERED",
    ):
        return run_canonical(ctx, cell)
    if arch.startswith("M"):
        return run_memory(ctx, cell)
    if arch.startswith("P"):
        return run_formalization(ctx, cell)
    if arch.startswith("LP"):
        return run_persistence(ctx, cell)
    raise ValueError(f"unknown architecture {arch}")
