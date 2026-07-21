"""Typed canonical-resolution parsing and deterministic grounding policy.

The model may propose a mapping, but this module decides whether the mapping is
grounded strongly enough to cross the action boundary. Hidden application
state may validate an anchored entity. It may not originate an entity merely
because only one candidate happens to exist in state.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from lexstab import models
from lexstab.artifacts import DomainStore


def _legacy_to_v2(obj: dict[str, Any]) -> dict[str, Any]:
    status = obj.get("status")
    if status == "RESOLVED":
        return {
            "mapping_outcome": "MAPPED",
            "canonical_intent": {
                "entity_type": obj.get("entity_type"),
                "entity_id": obj.get("entity_id"),
                "operation_id": obj.get("operation_id"),
                "arguments": obj.get("arguments") or {},
            },
            "candidate_mappings": [],
            "question": None,
            "preserved_user_terms": obj.get("preserved_user_terms") or [],
            "uncertainties": obj.get("uncertainties") or [],
            "grounding": {},
        }
    if status == "CLARIFY":
        return {
            "mapping_outcome": "NEEDS_CLARIFICATION",
            "canonical_intent": None,
            "candidate_mappings": obj.get("candidate_mappings") or [],
            "question": obj.get("question") or "What information should be used to resolve this request?",
            "preserved_user_terms": obj.get("preserved_user_terms") or [],
            "uncertainties": obj.get("uncertainties") or [],
            "grounding": {},
        }
    return obj


def parse_resolution(
    obj: dict[str, Any] | None, *, allow_legacy: bool = False
) -> tuple[models.CanonicalResolution | None, str | None]:
    if obj is None:
        return None, "canonicalizer returned no JSON object"
    candidate = _legacy_to_v2(obj) if allow_legacy and "mapping_outcome" not in obj else obj
    try:
        return models.CanonicalResolution.model_validate(candidate), None
    except ValidationError as exc:
        return None, str(exc)


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [item for child in value.values() for item in _flatten_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _flatten_strings(child)]
    return [str(value)] if value is not None else []


def _entity_anchors(domain: DomainStore, text: str) -> set[str]:
    """Return entity IDs present anywhere in a user-visible text artifact.

    Domain patterns are full-value validators such as ``^INC-[0-9]{4}$``.
    Removing only their outer anchors lets the same reviewed pattern find IDs
    embedded in prose without weakening its internal constraints.
    """
    anchors: set[str] = set()
    for entity in domain.entities.values():
        try:
            search_pattern = entity.id_pattern
            if search_pattern.startswith("^"):
                search_pattern = search_pattern[1:]
            if search_pattern.endswith("$"):
                search_pattern = search_pattern[:-1]
            bounded = rf"(?<![A-Za-z0-9])(?:{search_pattern})(?![A-Za-z0-9])"
            anchors.update(
                match.group(0).upper() for match in re.finditer(bounded, text, re.I)
            )
        except re.error:
            continue
    return anchors


def _value_is_explicit(value: Any, text: str) -> bool:
    if isinstance(value, bool):
        return str(value).lower() in text.lower()
    if isinstance(value, (int, float)):
        rendered = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(rendered)}(?![A-Za-z0-9])", text) is not None
    rendered = str(value).strip()
    if not rendered:
        return False
    alternatives = {rendered.lower(), rendered.lower().replace("_", " ")}
    lowered = text.lower()
    return any(term in lowered for term in alternatives)


_NOT_DERIVED = object()


def _derive_state_argument(
    intent: models.CanonicalIntent, name: str, known_state: dict[str, Any]
) -> Any:
    if intent.operation_id != "REFUND_DUPLICATE_CHARGE" or name != "amount_usd":
        return _NOT_DERIVED
    order = (known_state.get("orders") or {}).get(intent.entity_id)
    if not isinstance(order, dict) or not order.get("duplicate_charge_confirmed"):
        return _NOT_DERIVED
    value = order.get("duplicate_charge_amount_usd", _NOT_DERIVED)
    return value if value is not None else _NOT_DERIVED


def enforce_grounding(
    resolution: models.CanonicalResolution,
    *,
    domain: DomainStore,
    user_request: str,
    shared_context_text: str,
    visible_state: dict[str, Any],
    known_state: dict[str, Any],
) -> models.CanonicalResolution:
    """Apply the versioned support-domain grounding policy.

    A mapped result that violates grounding becomes a safe clarification. The
    original model proposal remains available in the invocation trace.
    """
    if resolution.mapping_outcome != models.MappingOutcome.MAPPED:
        return resolution
    intent = resolution.canonical_intent
    assert intent is not None
    operation = domain.operations.get(intent.operation_id)
    request_anchors = _entity_anchors(domain, user_request)
    shared_context_anchors = _entity_anchors(domain, shared_context_text)
    visible_state_anchors = _entity_anchors(
        domain, "\n".join(_flatten_strings(visible_state))
    )
    anchors = request_anchors | shared_context_anchors | visible_state_anchors
    missing: list[str] = []
    grounding: dict[str, str] = {}
    grounded_arguments = dict(intent.arguments)

    if operation is None or operation.entity_type != intent.entity_type:
        missing.append("valid_operation_mapping")
    if intent.entity_id.upper() not in anchors:
        missing.append("entity_reference")
    else:
        if intent.entity_id.upper() in request_anchors:
            grounding["entity_id"] = "request"
        elif intent.entity_id.upper() in shared_context_anchors:
            grounding["entity_id"] = "shared_context"
        else:
            grounding["entity_id"] = "visible_context_state"

    if operation is not None:
        entity_arg_names = {
            name for name, spec in operation.arguments.items()
            if spec.required and name.endswith("_id")
        }
        for name, spec in operation.arguments.items():
            if not spec.required or name in entity_arg_names:
                continue
            if name not in grounded_arguments:
                derived = _derive_state_argument(intent, name, known_state)
                if intent.entity_id.upper() in anchors and derived is not _NOT_DERIVED:
                    grounded_arguments[name] = derived
                    grounding[name] = "known_state:state-derivation.v1"
                    continue
                missing.append(name)
                continue
            value = grounded_arguments[name]
            if _value_is_explicit(value, user_request):
                grounding[name] = "request"
            elif _value_is_explicit(value, shared_context_text):
                grounding[name] = "shared_context"
            elif intent.entity_id.upper() in anchors:
                derived = _derive_state_argument(intent, name, known_state)
                try:
                    matches_derived = (
                        derived is not _NOT_DERIVED
                        and round(float(derived), 2) == round(float(value), 2)
                    )
                except (TypeError, ValueError):
                    matches_derived = derived == value
                if matches_derived:
                    grounding[name] = "known_state:state-derivation.v1"
                else:
                    missing.append(name)
            else:
                missing.append(name)

    if not missing:
        grounded_intent = intent.model_copy(update={"arguments": grounded_arguments})
        return resolution.model_copy(update={
            "canonical_intent": grounded_intent,
            "grounding": grounding,
        })

    unique_missing = sorted(set(missing))
    candidate = models.CandidateMapping(
        entity_type=intent.entity_type,
        operation_id=intent.operation_id,
        missing_or_ambiguous=unique_missing,
    )
    return models.CanonicalResolution(
        mapping_outcome=models.MappingOutcome.NEEDS_CLARIFICATION,
        canonical_intent=None,
        candidate_mappings=[candidate],
        question=(
            "Please provide or identify the following before I act: "
            + ", ".join(unique_missing)
            + "."
        ),
        preserved_user_terms=resolution.preserved_user_terms,
        uncertainties=sorted(set(resolution.uncertainties + unique_missing)),
        grounding=grounding,
    )


def intent_payload(resolution: models.CanonicalResolution) -> dict[str, Any]:
    if resolution.mapping_outcome != models.MappingOutcome.MAPPED or resolution.canonical_intent is None:
        raise ValueError("canonical resolution is not mapped")
    return resolution.canonical_intent.model_dump(mode="json")


def resolution_json(resolution: models.CanonicalResolution) -> str:
    return json.dumps(resolution.model_dump(mode="json"), indent=2, sort_keys=True)
