"""Deterministic mock provider (D-009).

Implements the full adapter contract with zero network access. Behavior is a
pure function of the assembled prompt plus an optional scripted-response table
used by tests and fixtures. Every record it returns is stamped
``provider="mock"``; run manifests using it are marked mocked and
baseline-ineligible.
"""

from __future__ import annotations

import json
from typing import Any

from lexstab.providers import mockbrain as brain
from lexstab.providers.base import BaseAdapter, ProviderResponse, TransportError


def _json_response(obj: dict, usage_tokens: int = 60) -> ProviderResponse:
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return ProviderResponse(
        raw={"mock": True, "content": text},
        text=text,
        tool_calls=[],
        tool_call_mode="mock",
        usage={"prompt_tokens": usage_tokens, "completion_tokens": len(text) // 4 + 1},
        finish_reason="stop",
        reported_model_id="mock",
        cost_estimate=0.0,
    )


def _tool_response(tool: str, arguments: dict, usage_tokens: int = 60) -> ProviderResponse:
    call = {"tool": tool, "arguments": arguments}
    return ProviderResponse(
        raw={"mock": True, "tool_call": call},
        text=None,
        tool_calls=[call],
        tool_call_mode="mock",
        usage={"prompt_tokens": usage_tokens, "completion_tokens": 24},
        finish_reason="tool_use",
        reported_model_id="mock",
        cost_estimate=0.0,
    )


def _text_response(text: str) -> ProviderResponse:
    return ProviderResponse(
        raw={"mock": True, "content": text},
        text=text,
        tool_calls=[],
        tool_call_mode="mock",
        usage={"prompt_tokens": 60, "completion_tokens": len(text) // 4 + 1},
        finish_reason="stop",
        reported_model_id="mock",
        cost_estimate=0.0,
    )


class MockProvider(BaseAdapter):
    """Deterministic offline provider. ``script`` maps mock keys to canned
    payloads: {"__transport_error__": n} raises n transport errors first;
    {"__text__": "..."} returns raw text; {"__tool__": {...}} returns a tool
    call; any other dict is returned as a JSON response."""

    def __init__(self, script: dict[str, Any] | None = None):
        super().__init__(name="mock", backoff_base_seconds=0.0, sleeper=lambda _s: None)
        self.script = dict(script or {})
        self._transport_failures: dict[str, int] = {}

    # ------------------------------------------------------------ dispatch

    def _call_once(
        self,
        *,
        model_id: str,
        messages: list[dict],
        tools: list[dict] | None,
        response_schema: dict | None,
        parameters: dict,
        metadata: dict,
    ) -> ProviderResponse:
        key = metadata.get("mock_key") or f"{metadata.get('role', '')}:{metadata.get('cell_id', '')}"
        fallback_key = f"{metadata.get('role', '')}:{metadata.get('cell_id', '')}"
        scripted = self.script.get(key)
        if scripted is None and fallback_key != key:
            scripted = self.script.get(fallback_key)
            key = fallback_key if scripted is not None else key
        if scripted is not None:
            if isinstance(scripted, dict) and "__transport_error__" in scripted:
                remaining = self._transport_failures.get(key, int(scripted["__transport_error__"]))
                if remaining > 0:
                    self._transport_failures[key] = remaining - 1
                    raise TransportError(f"scripted transport failure ({key})")
                fallback = {k: v for k, v in scripted.items() if k != "__transport_error__"}
                if fallback:
                    scripted = fallback
                else:
                    scripted = None
            if scripted is not None:
                if isinstance(scripted, dict) and "__text__" in scripted:
                    return _text_response(str(scripted["__text__"]))
                if isinstance(scripted, dict) and "__tool__" in scripted:
                    call = scripted["__tool__"]
                    return _tool_response(call["tool"], call.get("arguments", {}))
                return _json_response(scripted)

        kind = metadata.get("response_kind", "")
        text = brain.prompt_text(messages)
        handler = getattr(self, f"_kind_{kind}", None)
        if handler is None:
            return _text_response("Handled.")
        return handler(text, metadata)

    # ------------------------------------------------------------ execution kinds

    def _interpret(self, text: str) -> dict[str, Any]:
        request = brain.extract_section(text, "USER REQUEST") or brain.extract_section(
            text, "TASK INPUT"
        )
        if not request:
            # Direct executors put the request in the final user message.
            request = text.splitlines()[-1] if text.splitlines() else ""
        context = brain.extract_section(text, "SHARED CONTEXT")
        known_state = brain.extract_json_from_section(
            brain.extract_section(text, "KNOWN STATE")
            or brain.extract_section(text, "KNOWN APPLICATION STATE")
        )
        ops = brain.match_operations(request)
        result: dict[str, Any] = {
            "request": request,
            "context": context,
            "known_state": known_state,
            "ops": ops,
        }
        if len(ops) >= 1:
            arguments, missing = brain.build_arguments(ops[0], request, context)
            result["arguments"] = arguments
            result["missing"] = missing
        return result

    def _precondition_refusal(self, op_id: str, arguments: dict, known_state: dict | None) -> bool:
        entity_arg = brain.ID_ARG_FOR_OP.get(op_id)
        entity_id = arguments.get(entity_arg) if entity_arg else None
        if op_id in ("ESCALATE_INCIDENT", "CLOSE_INCIDENT", "REASSIGN_INCIDENT"):
            if brain.known_state_shows_closed(known_state, entity_id):
                return True
        if op_id == "ESCALATE_INCIDENT" and known_state and entity_id:
            incident = known_state.get("incidents", {}).get(entity_id, {})
            tier = incident.get("support_tier")
            dest = arguments.get("destination_tier")
            if isinstance(tier, int) and isinstance(dest, int) and dest <= tier:
                return True
        return False

    def _kind_direct_executor(self, text: str, metadata: dict) -> ProviderResponse:
        info = self._interpret(text)
        ops = info["ops"]
        if not ops:
            entity_ids = brain.find_entity_ids(info["request"] + info["context"])
            if entity_ids and entity_ids[0].startswith("INC"):
                ops = ["ESCALATE_INCIDENT" if "tier" in info["request"].lower() else "CLOSE_INCIDENT"]
            else:
                return _text_response("I have handled the request as best I could.")
            info["arguments"], info["missing"] = brain.build_arguments(
                ops[0], info["request"], info["context"]
            )
        op_id = ops[0]
        arguments = dict(info.get("arguments", {}))
        # A0 has no clarification policy: guess defaults instead of asking.
        if op_id == "ESCALATE_INCIDENT" and "destination_tier" not in arguments:
            arguments["destination_tier"] = 2
        if op_id == "REASSIGN_INCIDENT" and "destination_team" not in arguments:
            arguments["destination_team"] = "SERVICE_DESK"
        if op_id == "REFUND_DUPLICATE_CHARGE" and "amount_usd" not in arguments:
            arguments["amount_usd"] = 100.0
        return _tool_response(brain.OPERATION_TOOLS[op_id], arguments)

    def _kind_direct_clarify_executor(self, text: str, metadata: dict) -> ProviderResponse:
        info = self._interpret(text)
        ops = info["ops"]
        if not ops:
            return _json_response(
                {"decision": "CLARIFY", "question": "Which operation should be performed, and on which record?"}
            )
        if len(ops) > 1:
            names = " or ".join(op.replace("_", " ").lower() for op in ops)
            return _json_response(
                {"decision": "CLARIFY", "question": f"Should this be handled as {names}?"}
            )
        op_id = ops[0]
        arguments = info.get("arguments", {})
        missing = info.get("missing", [])
        if missing:
            return _json_response(
                {"decision": "CLARIFY", "question": f"Please provide: {', '.join(missing)}."}
            )
        if self._precondition_refusal(op_id, arguments, info["known_state"]):
            return _json_response({"decision": "REFUSE", "reason_code": "FAILED_PRECONDITION"})
        return _tool_response(brain.OPERATION_TOOLS[op_id], arguments)

    def _kind_canonical_executor(self, text: str, metadata: dict) -> ProviderResponse:
        resolution = brain.extract_json_from_section(
            brain.extract_section(text, "CANONICAL RESOLUTION")
            or brain.extract_section(text, "CANONICAL INTENT")
        )
        if not resolution or "operation_id" not in resolution:
            return _text_response("No canonical resolution found.")
        op_id = resolution["operation_id"]
        tool = brain.OPERATION_TOOLS.get(op_id)
        if tool is None:
            return _text_response(f"Unknown operation {op_id}.")
        arguments = dict(resolution.get("arguments", {}))
        id_arg = brain.ID_ARG_FOR_OP.get(op_id)
        if id_arg and id_arg not in arguments and resolution.get("entity_id"):
            arguments[id_arg] = resolution["entity_id"]
        known_state = brain.extract_json_from_section(
            brain.extract_section(text, "KNOWN APPLICATION STATE")
            or brain.extract_section(text, "KNOWN STATE")
        )
        if self._precondition_refusal(op_id, arguments, known_state):
            return _json_response({"decision": "REFUSE", "reason_code": "FAILED_PRECONDITION"})
        return _tool_response(tool, arguments)

    _kind_rendered_executor = _kind_canonical_executor
    _kind_procedure_tool = _kind_canonical_executor

    def _kind_canonical_resolution(self, text: str, metadata: dict) -> ProviderResponse:
        info = self._interpret(text)
        ops = info["ops"]
        if len(ops) != 1 or info.get("missing"):
            candidates = [
                {"entity_type": brain.ENTITY_PREFIX_FOR_OP.get(op, ""), "operation_id": op,
                 "missing_or_ambiguous": info.get("missing", [])}
                for op in (ops or ["UNKNOWN"])
            ]
            return _json_response(
                {
                    "status": "CLARIFY",
                    "candidate_mappings": candidates,
                    "question": "Which operation is intended, and what are the missing details?",
                }
            )
        op_id = ops[0]
        arguments = dict(info.get("arguments", {}))
        id_arg = brain.ID_ARG_FOR_OP[op_id]
        entity_id = arguments.pop(id_arg, None)
        entity_type = {
            "INC": "INCIDENT", "ORD": "ORDER", "ACC": "ACCOUNT", "APR": "APPROVAL_REQUEST",
        }.get(brain.ENTITY_PREFIX_FOR_OP[op_id], "INCIDENT")
        return _json_response(
            {
                "status": "RESOLVED",
                "entity_type": entity_type,
                "entity_id": entity_id,
                "operation_id": op_id,
                "arguments": arguments,
                "preserved_user_terms": [],
                "uncertainties": [],
            }
        )

    def _kind_adequacy_result(self, text: str, metadata: dict) -> ProviderResponse:
        info = self._interpret(text)
        ops = info["ops"]
        missing = info.get("missing", ["operation"]) if ops else ["operation"]
        adequate = bool(ops) and len(ops) == 1 and not missing
        ambiguous = len(ops) > 1
        return _json_response(
            {
                "adequacy": "ADEQUATE" if adequate else "INADEQUATE",
                "ambiguity": "AMBIGUOUS" if ambiguous else "UNAMBIGUOUS",
                "candidate_operation_ids": ops,
                "resolved_fields": info.get("arguments", {}),
                "missing_information": [] if adequate else missing,
                "contradictions": [],
                "recommended_behavior": "EXECUTE" if adequate and not ambiguous else "CLARIFY",
            }
        )

    def _kind_clarification_question(self, text: str, metadata: dict) -> ProviderResponse:
        adequacy = brain.extract_json_from_section(
            brain.extract_section(text, "ADEQUACY RESULT")
        ) or {}
        targets = adequacy.get("missing_information") or ["intended operation"]
        question = "Could you tell me: " + " and ".join(
            target.replace("_", " ") for target in targets[:2]
        ) + "?"
        return _json_response({"decision": "CLARIFY", "targets": targets[:2], "question": question})

    def _kind_generic_action_proposal(self, text: str, metadata: dict) -> ProviderResponse:
        task_input = brain.extract_section(text, "TASK INPUT") or brain.extract_section(
            text, "CANONICAL INTENT"
        )
        policy = brain.extract_section(text, "CONDITION-SPECIFIC DECISION POLICY")
        clarify_allowed = "use CLARIFY" in policy or "CANONICAL INTENT" in text
        canonical = brain.extract_json_from_section(task_input)
        if canonical and "operation_id" not in canonical:
            nested = canonical.get("canonical_state")
            if isinstance(nested, dict) and nested.get("operation_id"):
                canonical = nested
        known_state = brain.extract_json_from_section(brain.extract_section(text, "KNOWN STATE"))
        if canonical and canonical.get("operation_id"):
            op_id = canonical["operation_id"]
            arguments = dict(canonical.get("arguments", {}))
            id_arg = brain.ID_ARG_FOR_OP.get(op_id)
            if id_arg and id_arg not in arguments and canonical.get("entity_id"):
                arguments[id_arg] = canonical["entity_id"]
            if self._precondition_refusal(op_id, arguments, known_state):
                return _json_response(
                    {"decision": "REFUSE", "operation_id": None, "arguments": {},
                     "question": None, "reason_code": "FAILED_PRECONDITION"}
                )
            return _json_response(
                {"decision": "ACT", "operation_id": op_id, "arguments": arguments,
                 "question": None, "reason_code": None}
            )
        info = self._interpret(text)
        ops = info["ops"]
        missing = info.get("missing", [])
        if (not ops or len(ops) > 1 or missing) and clarify_allowed:
            return _json_response(
                {"decision": "CLARIFY", "operation_id": None, "arguments": {},
                 "question": "Please identify the record and intended operation.",
                 "reason_code": None}
            )
        if not ops:
            return _json_response(
                {"decision": "ACT", "operation_id": "CLOSE_INCIDENT",
                 "arguments": info.get("arguments", {}), "question": None, "reason_code": None}
            )
        op_id = ops[0]
        arguments = dict(info.get("arguments", {}))
        if op_id == "ESCALATE_INCIDENT" and "destination_tier" not in arguments:
            arguments["destination_tier"] = 2
        if self._precondition_refusal(op_id, arguments, info["known_state"]):
            return _json_response(
                {"decision": "REFUSE", "operation_id": None, "arguments": {},
                 "question": None, "reason_code": "FAILED_PRECONDITION"}
            )
        return _json_response(
            {"decision": "ACT", "operation_id": op_id, "arguments": arguments,
             "question": None, "reason_code": None}
        )

    def _kind_plain_text_handoff(self, text: str, metadata: dict) -> ProviderResponse:
        incoming = brain.extract_section(text, "INCOMING TASK HANDOFF")
        stage_result = brain.extract_section(text, "THIS STAGE'S RESULT")
        combined = incoming + "\n" + stage_result
        entity_ids = brain.find_entity_ids(combined)
        ops = brain.match_operations(combined)
        op_label = ops[0].replace("_", " ").lower() if ops else "the requested handling"
        # Deterministic lexical drift: sometimes rewrite the operation label.
        if brain.stable_int(combined, 3) == 0 and ops:
            op_label = brain.rotate_label(op_label, [])
        tier = brain.TIER_RE.search(combined)
        detail = f" to tier {tier.group(1)}" if tier else ""
        if brain.stable_int(combined, 7) == 0:
            detail = " to a higher tier" if tier else detail
        entity = entity_ids[0] if entity_ids else "the record under discussion"
        handoff = (
            f"Next stage: continue {op_label} for {entity}{detail}. "
            f"No unresolved questions." if ops else
            f"Next stage: determine correct handling for {entity}. Operation still unclear."
        )
        return _text_response(handoff)

    def _kind_triage_result(self, text: str, metadata: dict) -> ProviderResponse:
        section = brain.extract_section(text, "INPUT")
        lowered = section.lower()
        entity_ids = brain.find_entity_ids(section)
        if "charged twice" in lowered or "duplicate" in lowered:
            classification = "DUPLICATE_CHARGE"
            preferred_prefix = "ORD"
        elif "dispute" in lowered:
            classification = "LEGITIMATE_CHARGE_DISPUTE"
            preferred_prefix = "ORD"
        elif not entity_ids:
            classification = "MISSING_INFORMATION"
            preferred_prefix = ""
        else:
            classification = "OTHER"
            preferred_prefix = entity_ids[0][:3]
        chosen = next((eid for eid in entity_ids if eid.startswith(preferred_prefix)), None)
        entity_type = {"ORD": "ORDER", "INC": "INCIDENT", "CUS": "CUSTOMER"}.get(
            (chosen or "  ?")[:3], "OTHER"
        )
        return _json_response(
            {
                "entity_type": entity_type,
                "entity_id": chosen,
                "classification": classification,
                "confidence_band": "HIGH" if chosen else "LOW",
                "uncertainties": [] if chosen else ["entity identity"],
            }
        )

    OP_POLICY_MAP = {
        "ESCALATE_INCIDENT": "P-20", "REASSIGN_INCIDENT": "P-20", "CLOSE_INCIDENT": "P-21",
        "REQUEST_MORE_INFORMATION": "P-19", "REFUND_DUPLICATE_CHARGE": "P-17",
        "REQUEST_MANAGER_REVIEW": "P-18", "SUSPEND_ACCOUNT": "P-23", "REQUEST_APPROVAL": "P-22",
    }

    def _kind_policy_result(self, text: str, metadata: dict) -> ProviderResponse:
        triage = brain.extract_json_from_section(brain.extract_section(text, "TRIAGE RESULT")) or {}
        known_state = brain.extract_json_from_section(brain.extract_section(text, "KNOWN STATE")) or {}
        canonical = triage.get("canonical_state") or {}
        if canonical.get("operation_id") and canonical["operation_id"] != "REFUND_DUPLICATE_CHARGE":
            policy_id = self.OP_POLICY_MAP.get(canonical["operation_id"])
            return _json_response({"decision": "SELECT", "policy_id": policy_id, "missing_fact": None})
        if isinstance(triage.get("triage"), dict):
            triage = {**triage["triage"], "canonical_state": canonical}
        classification = triage.get("classification")
        entity_id = triage.get("entity_id") or canonical.get("entity_id")
        order = known_state.get("orders", {}).get(entity_id or "", {})
        if classification == "DUPLICATE_CHARGE":
            if order.get("duplicate_charge_confirmed"):
                return _json_response({"decision": "SELECT", "policy_id": "P-17", "missing_fact": None})
            return _json_response({"decision": "SELECT", "policy_id": "P-19", "missing_fact": None})
        if classification == "LEGITIMATE_CHARGE_DISPUTE":
            return _json_response({"decision": "SELECT", "policy_id": "P-18", "missing_fact": None})
        return _json_response(
            {"decision": "CLARIFY", "policy_id": None, "missing_fact": "business situation"}
        )

    def _kind_plan_result(self, text: str, metadata: dict) -> ProviderResponse:
        triage = brain.extract_json_from_section(brain.extract_section(text, "TRIAGE RESULT")) or {}
        policy = brain.extract_json_from_section(brain.extract_section(text, "POLICY RESULT")) or {}
        known_state = brain.extract_json_from_section(brain.extract_section(text, "KNOWN STATE")) or {}
        canonical = triage.get("canonical_state") or {}
        if canonical.get("operation_id"):
            op_id = canonical["operation_id"]
            arguments = dict(canonical.get("arguments", {}))
            id_arg = brain.ID_ARG_FOR_OP.get(op_id)
            if id_arg and id_arg not in arguments and canonical.get("entity_id"):
                arguments[id_arg] = canonical["entity_id"]
            return _json_response(
                {"decision": "ACT", "operation_id": op_id, "arguments": arguments, "question": None}
            )
        if isinstance(triage.get("triage"), dict):
            triage = triage["triage"]
        entity_id = triage.get("entity_id")
        policy_id = policy.get("policy_id")
        if policy.get("decision") == "CLARIFY" or not entity_id:
            return _json_response(
                {"decision": "CLARIFY", "operation_id": None, "arguments": {},
                 "question": policy.get("missing_fact") or "Which record is affected?"}
            )
        if policy_id == "P-17":
            amount = known_state.get("orders", {}).get(entity_id, {}).get(
                "duplicate_charge_amount_usd", 100.0
            )
            return _json_response(
                {"decision": "ACT", "operation_id": "REFUND_DUPLICATE_CHARGE",
                 "arguments": {"order_id": entity_id, "amount_usd": amount}, "question": None}
            )
        if policy_id == "P-18":
            return _json_response(
                {"decision": "ACT", "operation_id": "REQUEST_MANAGER_REVIEW",
                 "arguments": {"order_id": entity_id, "reason_code": "DISPUTED_CHARGE"},
                 "question": None}
            )
        return _json_response(
            {"decision": "CLARIFY", "operation_id": None, "arguments": {},
             "question": "Additional transaction information is required to confirm the duplicate."}
        )

    def _kind_plan_executor(self, text: str, metadata: dict) -> ProviderResponse:
        plan = brain.extract_json_from_section(brain.extract_section(text, "PLAN")) or {}
        if plan.get("decision") == "ACT" and plan.get("operation_id"):
            tool = brain.OPERATION_TOOLS.get(plan["operation_id"])
            if tool:
                return _tool_response(tool, plan.get("arguments", {}))
        return _json_response(
            {"decision": "CLARIFY", "question": plan.get("question") or "Plan did not authorize action."}
        )

    # ------------------------------------------------------------ authoring kinds

    def _kind_generated_requests(self, text: str, metadata: dict) -> ProviderResponse:
        case = brain.extract_json_from_section(brain.extract_section(text, "CANONICAL CASE")) or {}
        canonical = case.get("canonical", {})
        entity_id = canonical.get("entity_id", "INC-0000")
        op_id = canonical.get("operation_id", "ESCALATE_INCIDENT")
        tier = canonical.get("arguments", {}).get("destination_tier", 2)
        templates = {
            "ESCALATE_INCIDENT": [
                (f"Elevate incident {entity_id} to Tier {tier}.", ["operation_synonym"]),
                (f"Escalate ticket {entity_id} to Tier {tier}.", ["entity_synonym"]),
                (f"Please move {entity_id} up to Tier {tier}.", ["conversational", "syntactic_paraphrase"]),
                (f"Can you escalate {entity_id} to Tier {tier}?", ["question_form"]),
            ],
            "REASSIGN_INCIDENT": [
                (f"Transfer {entity_id} to the {canonical.get('arguments', {}).get('destination_team', 'BILLING').title()} team without changing its tier.", ["operation_synonym"]),
                (f"Please assign {entity_id} to the {canonical.get('arguments', {}).get('destination_team', 'BILLING').title()} team, keeping its current tier.", ["conversational"]),
            ],
        }.get(op_id, [(f"Please handle {op_id.replace('_', ' ').lower()} for {entity_id}.", ["syntactic_paraphrase"])])
        candidates = [
            {
                "text": text_variant,
                "intended_axes": axes,
                "terms_changed": [],
                "self_check": {
                    "same_entity": True, "same_operation": True, "same_arguments": True,
                    "same_constraints": True, "same_resulting_state": True,
                },
            }
            for text_variant, axes in templates
        ]
        return _json_response({"case_id": case.get("case_id", "?"), "candidates": candidates})

    def _kind_equivalence_judgment(self, text: str, metadata: dict) -> ProviderResponse:
        case = brain.extract_json_from_section(brain.extract_section(text, "CANONICAL CASE")) or {}
        candidate = brain.extract_section(text, "CANDIDATE REQUEST")
        canonical = case.get("canonical", {})
        ops = brain.match_operations(candidate)
        arguments, missing = (
            brain.build_arguments(ops[0], candidate, "") if ops else ({}, ["operation"])
        )
        same_operation = ops == [canonical.get("operation_id")]
        same_entity = canonical.get("entity_id", "") in candidate
        gold_args = canonical.get("arguments", {})
        args_match = all(
            arguments.get(key) == value
            for key, value in gold_args.items()
        ) and not missing
        equivalent = same_operation and same_entity and args_match
        verdict = "SAME" if same_operation else ("UNCLEAR" if not ops else "DIFFERENT")
        return _json_response(
            {
                "equivalent": equivalent,
                "confidence_band": "HIGH" if same_operation and same_entity else "LOW",
                "component_checks": {
                    "entity": "SAME" if same_entity else "UNCLEAR",
                    "operation": verdict,
                    "arguments": "SAME" if args_match else "UNCLEAR",
                    "constraints": "SAME",
                    "resulting_state": "SAME" if equivalent else "UNCLEAR",
                },
                "material_difference": None if equivalent else "operation or arguments unclear",
                "possible_alternative_mappings": [op for op in ops if op != canonical.get("operation_id")],
            }
        )

    def _kind_adversarial_judgment(self, text: str, metadata: dict) -> ProviderResponse:
        candidate = brain.extract_section(text, "CANDIDATE REQUEST")
        ops = brain.match_operations(candidate)
        challenged = len(ops) != 1
        return _json_response(
            {
                "material_challenge_found": challenged,
                "challenge_type": "OPERATION" if challenged else "NONE",
                "alternative_interpretation": (
                    "wording may support a different operation" if challenged else None
                ),
                "why_reasonable": "keyword evidence is weak" if challenged else None,
                "recommended_disposition": "HUMAN_REVIEW" if challenged else "ACCEPT",
            }
        )

    def _kind_adequacy_judgment(self, text: str, metadata: dict) -> ProviderResponse:
        candidate = brain.extract_section(text, "CANDIDATE REQUEST")
        context = brain.extract_section(text, "FROZEN CONTEXT AVAILABLE TO THE TESTED SYSTEM")
        ops = brain.match_operations(candidate)
        arguments, missing = (
            brain.build_arguments(ops[0], candidate, context) if ops else ({}, ["operation"])
        )
        adequate = bool(ops) and len(ops) == 1 and not missing
        return _json_response(
            {
                "adequacy": "ADEQUATE" if adequate else "INADEQUATE",
                "ambiguity": "AMBIGUOUS" if len(ops) > 1 else "UNAMBIGUOUS",
                "expected_behavior": "EXECUTE" if adequate else "CLARIFY",
                "missing_information": [] if adequate else missing,
                "contradictions": [],
                "reasonable_candidate_mappings": ops,
                "confidence_band": "HIGH" if adequate else "MEDIUM",
                "recommended_disposition": "ACCEPT",
            }
        )

    def _kind_ambiguity_judgment(self, text: str, metadata: dict) -> ProviderResponse:
        candidate = brain.extract_section(text, "CANDIDATE REQUEST")
        ops = brain.match_operations(candidate)
        ambiguous = len(ops) > 1
        return _json_response(
            {
                "ambiguity": "AMBIGUOUS" if ambiguous else "UNAMBIGUOUS",
                "reasonable_interpretations": [
                    {"operation_id": op, "why_reasonable": "keyword evidence"} for op in ops
                ],
                "discriminating_fact_needed": "intended operation" if ambiguous else None,
                "confidence_band": "MEDIUM",
                "recommended_disposition": "HUMAN_REVIEW" if ambiguous else "ACCEPT",
            }
        )

    def _kind_coverage_plan(self, text: str, metadata: dict) -> ProviderResponse:
        case = brain.extract_json_from_section(brain.extract_section(text, "CANONICAL CASE")) or {}
        axes_section = brain.extract_section(text, "REQUIRED VARIATION AXES")
        existing = brain.extract_section(text, "EXISTING REQUEST SUMMARIES")
        gaps = []
        for axis in [line.strip("- ").strip() for line in axes_section.splitlines() if line.strip()]:
            if axis and axis not in existing:
                gaps.append(
                    {"axis": axis, "current_count": 0, "target_count": 2,
                     "priority": "HIGH", "generation_constraint": "preserve canonical meaning"}
                )
        return _json_response(
            {"case_id": case.get("case_id", "?"), "coverage_gaps": gaps,
             "do_not_generate": [], "notes_for_human": []}
        )

    def _kind_contrast_request(self, text: str, metadata: dict) -> ProviderResponse:
        case = brain.extract_json_from_section(brain.extract_section(text, "CANONICAL CASE")) or {}
        contrast_op = brain.extract_section(text, "CONTRAST OPERATION").strip().splitlines()
        contrast_id = contrast_op[0].strip() if contrast_op else "REASSIGN_INCIDENT"
        entity_id = case.get("canonical", {}).get("entity_id", "INC-0000")
        if contrast_id == "REASSIGN_INCIDENT":
            request_text = f"Reassign {entity_id} to the Billing team without changing its support tier."
            arguments = {"incident_id": entity_id, "destination_team": "BILLING"}
        else:
            request_text = f"Perform {contrast_id.replace('_', ' ').lower()} for {entity_id}."
            arguments = {}
        return _json_response(
            {
                "text": request_text,
                "changed_semantic_component": "operation",
                "gold_operation_id": contrast_id,
                "gold_arguments": arguments,
                "expected_resulting_state_difference": "different operation effect",
            }
        )

    def _kind_failure_hypotheses(self, text: str, metadata: dict) -> ProviderResponse:
        return _json_response(
            {
                "hypotheses": [
                    {
                        "statement": "Indirect operation verbs correlate with wrong tool selection.",
                        "observable_prediction": "idiomatic axis error rate exceeds canonical axis error rate",
                        "required_comparison": "error rate by variation axis within case",
                        "possible_confounds": ["lexical distance", "prompt length"],
                        "candidate_red_team_axes": ["idiomatic", "indirect_request"],
                    }
                ],
                "coverage_gaps": ["organizational_jargon"],
                "cases_for_human_inspection": [],
            }
        )

    # ------------------------------------------------------------ discovery / judge

    def _kind_lexical_name(self, text: str, metadata: dict) -> ProviderResponse:
        definition = brain.extract_section(text, "DEFINITION").lower()
        table = [
            ("escalat", ("escalate incident", ["raise incident tier", "tier escalation"])),
            ("higher support tier", ("escalate incident", ["tier escalation", "elevate incident"])),
            ("responsibility for an open incident", ("escalate incident", ["tier escalation"])),
            ("definite noun phrase", ("unintroduced definite reference", ["novel definite", "false definite"])),
            ("assigned team", ("reassign incident", ["team transfer"])),
            ("owning team", ("reassign incident", ["team transfer", "incident reassignment"])),
            ("duplicate", ("refund duplicate charge", ["duplicate charge refund"])),
        ]
        sample_index = int(metadata.get("sample_index", 0))
        for needle, (term, alternatives) in table:
            if needle in definition:
                # Deterministic dispersion: a minority of samples yield an alternative.
                if alternatives and brain.stable_int(f"{definition}:{sample_index}", 5) == 0:
                    term = alternatives[brain.stable_int(str(sample_index), len(alternatives))]
                return _json_response(
                    {"preferred_term": term, "alternative_terms": alternatives,
                     "one_sentence_definition": definition.split(".")[0][:160] or term}
                )
        return _json_response(
            {"preferred_term": "DEFINITION_ONLY", "alternative_terms": [],
             "one_sentence_definition": definition.split(".")[0][:160]}
        )

    def _kind_judge_result(self, text: str, metadata: dict) -> ProviderResponse:
        reference = brain.extract_section(text, "REFERENCE")
        candidate = brain.extract_section(text, "CANDIDATE OUTPUT")
        normalized_ref = " ".join(reference.lower().split())
        normalized_cand = " ".join(candidate.lower().split())
        passed = bool(normalized_ref) and normalized_ref in normalized_cand
        uncertain = not normalized_ref
        return _json_response(
            {
                "criterion": "reference_containment",
                "score": "UNCERTAIN" if uncertain else ("PASS" if passed else "FAIL"),
                "evidence": [normalized_cand[:80]] if normalized_cand else [],
                "reason": "deterministic mock containment check",
                "human_review_required": uncertain,
            }
        )

    def _kind_grammar_correction(self, text: str, metadata: dict) -> ProviderResponse:
        import re as _re

        body = brain.extract_section(text, "TEXT")
        instances = []
        corrected = body
        for match in _re.finditer(r"\b[Tt]he (\w+)\b", body):
            noun = match.group(1)
            preceding = body[: match.start()].lower()
            introduced = _re.search(rf"\ba(?:n)? {noun.lower()}\b", preceding) or (
                noun.lower() in preceding.split()
            )
            if not introduced:
                article = "A" if match.group(0)[0] == "T" else "a"
                replacement = f"{article} {noun}"
                instances.append({
                    "original_span": body[match.start():match.end()],
                    "start_character": match.start(),
                    "end_character": match.end(),
                    "replacement": replacement,
                })
        for instance in reversed(instances):
            corrected = (
                corrected[: instance["start_character"]]
                + instance["replacement"]
                + corrected[instance["end_character"]:]
            )
        return _json_response({
            "phenomenon_present": bool(instances),
            "instances": instances,
            "corrected_text": corrected,
        })

    def _kind_source_code(self, text: str, metadata: dict) -> ProviderResponse:
        import re as _re

        code = brain.extract_section(text, "CODE")
        requirement = brain.extract_section(text, "REQUIREMENT")
        if "429" in requirement:
            match = _re.search(
                r"( +)if (\w+) >= self\.(\w+):\n +return False\n( +)return (\w+) >= 500",
                code,
            )
            if match:
                indent, attempts, limit, indent2, status = match.groups()
                patched = (
                    f"{indent}if {attempts} >= self.{limit}:\n{indent}    return False\n"
                    f"{indent2}if {status} == 429:\n{indent2}    return True\n"
                    f"{indent2}return {status} >= 500"
                )
                code = code[: match.start()] + patched + code[match.end():]
        return _text_response(code)

    def _kind_engineering_resolution(self, text: str, metadata: dict) -> ProviderResponse:
        request = brain.extract_section(text, "USER REQUEST").lower()
        if "retrieval" in request or "rag" in request:
            return _json_response({
                "status": "RESOLVED", "operation_id": "CONFIGURE_RAG",
                "knowledge_source": "SUPPORT_KNOWLEDGE_BASE",
                "preserved_original_terms": [], "candidate_interpretations": [],
                "question": None,
            })
        if "fine-tun" in request or "fine tun" in request or "additional training" in request:
            return _json_response({
                "status": "RESOLVED", "operation_id": "CONFIGURE_FINE_TUNING",
                "knowledge_source": "MODEL_PARAMETERS",
                "preserved_original_terms": [], "candidate_interpretations": [],
                "question": None,
            })
        if "resource augmented" in request or "know our support policies" in request or (
            "make the model know" in request
        ):
            return _json_response({
                "status": "CLARIFY", "operation_id": None, "knowledge_source": None,
                "preserved_original_terms": ["resource augmented generation"]
                if "resource augmented" in request else [],
                "candidate_interpretations": ["CONFIGURE_RAG", "CONFIGURE_FINE_TUNING"],
                "question": "Should the documentation be retrieved at inference time, or "
                            "used to modify the model through training?",
            })
        if "web" in request or "search" in request:
            return _json_response({
                "status": "RESOLVED", "operation_id": "CONFIGURE_WEB_SEARCH",
                "knowledge_source": "WEB", "preserved_original_terms": [],
                "candidate_interpretations": [], "question": None,
            })
        return _json_response({
            "status": "CLARIFY", "operation_id": None, "knowledge_source": None,
            "preserved_original_terms": [], "candidate_interpretations": [],
            "question": "Which capability should be configured?",
        })

    def _kind_procedure_selection(self, text: str, metadata: dict) -> ProviderResponse:
        intent = brain.extract_json_from_section(brain.extract_section(text, "CANONICAL INTENT")) or {}
        registry = brain.extract_section(text, "PROCEDURE REGISTRY")
        op_id = intent.get("operation_id", "")
        selected = None
        for line in registry.splitlines():
            if op_id and op_id in line and line.strip().startswith("-"):
                selected = line.strip("- ").split(":")[0].strip()
                break
        return _json_response(
            {"procedure_id": selected, "reason": "registry lookup by resolved operation"}
        )

    def _kind_drifted_label(self, text: str, metadata: dict) -> ProviderResponse:
        current = brain.extract_section(text, "CURRENT LABEL").strip()
        forbidden_section = brain.extract_section(text, "FORBIDDEN LABELS")
        forbidden = [line.strip("- ").strip() for line in forbidden_section.splitlines() if line.strip()]
        canonical_id = brain.extract_section(text, "CANONICAL ID").strip()
        return _json_response(
            {"canonical_id": canonical_id, "alternate_label": brain.rotate_label(current, forbidden)}
        )
