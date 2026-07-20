"""Deterministic model-facing text renderings of domain artifacts.

These strings are part of the assembled prompt, so they must be stable across
cells: fixed ordering, fixed formatting, no timestamps.
"""

from __future__ import annotations

import json
from typing import Any

from lexstab.artifacts import DomainStore
from lexstab.models import CanonicalCase, FrozenContext, Procedure, Rendering


def domain_summary(domain: DomainStore) -> str:
    lines = ["Operations:"]
    for op_id in sorted(domain.operations):
        op = domain.operations[op_id]
        args = ", ".join(
            f"{name}{'' if spec.required else '?'}: {spec.type}"
            for name, spec in op.arguments.items()
        )
        lines.append(f"- {op_id} (tool {op.tool}): {op.description or op.display_name}")
        lines.append(f"    arguments: {args}")
        if op.preconditions:
            lines.append(f"    preconditions: {'; '.join(op.preconditions)}")
    lines.append("")
    lines.append("Policies:")
    for policy_id in sorted(domain.policies):
        lines.append(f"- {policy_id}: {domain.policies[policy_id].text}")
    return "\n".join(lines)


def ontology_text(domain: DomainStore) -> str:
    lines = ["Entity types:"]
    for entity_type in sorted(domain.entities):
        entity = domain.entities[entity_type]
        lines.append(f"- {entity_type} (ids like {entity.id_pattern}): {entity.description}")
    lines.append("")
    lines.append(domain_summary(domain))
    return "\n".join(lines)


def state_json(state: dict[str, Any]) -> str:
    return json.dumps(state, indent=2, sort_keys=True)


def context_text(context: FrozenContext) -> str:
    if not context.messages and not context.visible_state:
        return "(no shared context)"
    parts = []
    for message in context.messages:
        parts.append(f"{message.role}: {message.content}")
    if context.visible_state:
        parts.append("visible state: " + json.dumps(context.visible_state, sort_keys=True))
    return "\n".join(parts)


def gold_canonical_resolution(case: CanonicalCase) -> dict[str, Any]:
    """Gold injection structure (spec §25.5); no canonicalizer output allowed."""
    return {
        "status": "RESOLVED",
        "entity_type": case.canonical.entity_type,
        "entity_id": case.canonical.entity_id,
        "operation_id": case.canonical.operation_id,
        "arguments": case.canonical.arguments,
    }


def operation_definitions_text(domain: DomainStore, operation_ids: list[str] | None = None) -> str:
    ids = sorted(operation_ids) if operation_ids else sorted(domain.operations)
    lines = []
    for op_id in ids:
        op = domain.operations[op_id]
        lines.append(
            json.dumps(
                {
                    "operation_id": op.operation_id,
                    "tool": op.tool,
                    "arguments": {
                        name: {"type": spec.type, "required": spec.required}
                        for name, spec in op.arguments.items()
                    },
                    "preconditions": op.preconditions,
                },
                sort_keys=True,
            )
        )
    return "\n".join(lines)


def rendering_text(rendering: Rendering, resolution: dict[str, Any]) -> str:
    """Instantiate a rendering template from a canonical resolution (§15.3)."""
    values = {"entity_id": resolution.get("entity_id"), "entity_type": resolution.get("entity_type"),
              "operation_id": resolution.get("operation_id")}
    values.update(resolution.get("arguments", {}))
    text = rendering.template
    for name, value in values.items():
        text = text.replace("{" + str(name) + "}", str(value))
    return text


def procedure_text(procedure: Procedure, packaging: str = "inline") -> str:
    body = {
        "procedure_id": procedure.procedure_id,
        "procedure_version": procedure.procedure_version,
        "title": procedure.title,
        "applies_to_operation_ids": procedure.applies_to_operation_ids,
        "required_inputs": procedure.required_inputs,
        "steps": [step.model_dump() for step in procedure.steps],
        "forbidden_behaviors": procedure.forbidden_behaviors,
    }
    content = json.dumps(body, indent=2, sort_keys=True)
    if packaging == "packaged":
        # Byte-equivalent instruction content behind a skill-invocation wrapper
        # (§33.9 ablation 5; §46.29).
        return (
            f"SKILL INVOCATION: {procedure.procedure_id} v{procedure.procedure_version}\n"
            "The following packaged skill content governs this operation:\n" + content
        )
    return content


def procedure_fact_control_text(procedure: Procedure) -> str:
    """Render procedure content without its name, handle, steps, or ordering.

    This is the P2F information-parity control. It preserves the unordered
    inputs, constraints, and behavioral content that P3 receives, but removes
    the named procedure and sequential structure whose incremental effect the
    P2F-to-P3 comparison is intended to estimate.
    """
    body = {
        "applicable_operations": sorted(procedure.applies_to_operation_ids),
        "required_inputs": sorted(procedure.required_inputs),
        "unordered_task_constraints": sorted(
            step.instruction for step in procedure.steps
        ),
        "forbidden_behaviors": sorted(procedure.forbidden_behaviors),
        "output_contract": procedure.output_contract,
    }
    return json.dumps(body, indent=2, sort_keys=True)


def glossary_text(records: list[Any]) -> str:
    lines = []
    for record in records:
        mapping = record.canonical_mapping
        target = mapping.operation_id or mapping.entity_type
        lines.append(f'- "{record.surface_form}" means {target}')
    return "\n".join(lines) if lines else "(no glossary entries)"
