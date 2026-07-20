"""Action-interface artifact construction and comparison (spec §15.5, §42.9).

Both action boundaries are generated from the one canonical operation registry
so they cannot drift apart (spec §46.30). ``compare_interfaces`` verifies
operation coverage, argument equivalence, and simulator mappings, and measures
description/terminology overlap (spec §15.6).
"""

from __future__ import annotations

import re
from typing import Any

from lexstab.artifacts import DomainStore
from lexstab.hashing import canonical_json, sha256_text
from lexstab.models import SCHEMA_VERSION

GENERIC_INTERFACE_ID = "GENERIC_ACTION_PROPOSAL_V1"
TYPED_INTERFACE_ID = "TYPED_SUPPORT_TOOLS_V1"
MCP_INTERFACE_ID = "MCP_SUPPORT_CAPABILITIES_V1"

GENERIC_PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "operation_id", "arguments", "question", "reason_code"],
    "properties": {
        "decision": {"enum": ["ACT", "CLARIFY", "REFUSE"]},
        "operation_id": {"type": ["string", "null"]},
        "arguments": {"type": "object"},
        "question": {"type": ["string", "null"]},
        "reason_code": {"type": ["string", "null"]},
    },
}


def _argument_json_schema(domain: DomainStore, operation_id: str) -> dict[str, Any]:
    op = domain.operations[operation_id]
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, spec in op.arguments.items():
        prop: dict[str, Any] = {"type": spec.type}
        if spec.pattern:
            prop["pattern"] = spec.pattern
        if spec.minimum is not None:
            prop["minimum"] = spec.minimum
        if spec.maximum is not None:
            prop["maximum"] = spec.maximum
        if spec.enum is not None:
            prop["enum"] = spec.enum
        if spec.description:
            prop["description"] = spec.description
        properties[name] = prop
        if spec.required:
            required.append(name)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(required),
        "properties": properties,
    }


def build_generic_interface(domain: DomainStore) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "interface_id": GENERIC_INTERFACE_ID,
        "interface_version": "1.0.0",
        "kind": "GENERIC_PROPOSAL",
        "operation_ids": sorted(domain.operations),
        "tools": [],
        "argument_schema_hash": sha256_text(canonical_json(GENERIC_PROPOSAL_SCHEMA)),
        "tool_description_hash": None,
        "transport": "inline_json",
        "adapter_version": "1",
        "validation_behavior": "reject_invalid",
        "discovery_behavior": None,
        "provenance": {"source": "generated_from_operation_registry"},
    }


def _tool_definition(domain: DomainStore, operation_id: str, namespace: str | None = None) -> dict[str, Any]:
    op = domain.operations[operation_id]
    name = f"{namespace}.{op.tool}" if namespace else op.tool
    return {
        "name": name,
        "description": op.description or op.display_name,
        "input_schema": _argument_json_schema(domain, operation_id),
        "operation_id": operation_id,
    }


def build_typed_interface(domain: DomainStore) -> dict[str, Any]:
    tools = [_tool_definition(domain, op_id) for op_id in sorted(domain.operations)]
    return {
        "schema_version": SCHEMA_VERSION,
        "interface_id": TYPED_INTERFACE_ID,
        "interface_version": "1.0.0",
        "kind": "NATIVE_TOOL",
        "operation_ids": sorted(domain.operations),
        "tools": tools,
        "argument_schema_hash": sha256_text(
            canonical_json([tool["input_schema"] for tool in tools])
        ),
        "tool_description_hash": sha256_text(
            canonical_json([tool["description"] for tool in tools])
        ),
        "transport": "local",
        "adapter_version": "1",
        "validation_behavior": "reject_invalid",
        "discovery_behavior": None,
        "provenance": {"source": "generated_from_operation_registry"},
    }


def build_mcp_interface(domain: DomainStore, namespace: str = "support") -> dict[str, Any]:
    """MCP-compatible capability export (optional condition; D-023)."""
    tools = [_tool_definition(domain, op_id, namespace) for op_id in sorted(domain.operations)]
    return {
        "schema_version": SCHEMA_VERSION,
        "interface_id": MCP_INTERFACE_ID,
        "interface_version": "1.0.0",
        "kind": "MCP_CAPABILITY",
        "operation_ids": sorted(domain.operations),
        "tools": tools,
        "argument_schema_hash": sha256_text(
            canonical_json([tool["input_schema"] for tool in tools])
        ),
        "tool_description_hash": sha256_text(
            canonical_json([tool["description"] for tool in tools])
        ),
        "transport": "mcp_local_export",
        "adapter_version": "1",
        "validation_behavior": "reject_invalid",
        "discovery_behavior": "capability_list",
        "provenance": {"source": "generated_from_operation_registry"},
    }


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def compare_interfaces(
    domain: DomainStore, generic: dict[str, Any], typed: dict[str, Any]
) -> dict[str, Any]:
    """Verify equivalence between the generic and typed boundaries (§15.6)."""
    problems: list[str] = []
    generic_ops = set(generic.get("operation_ids", []))
    typed_ops = set(typed.get("operation_ids", []))
    if generic_ops != typed_ops:
        problems.append(
            f"operation coverage differs: generic-only={sorted(generic_ops - typed_ops)}, "
            f"typed-only={sorted(typed_ops - generic_ops)}"
        )
    tool_map = {tool.get("operation_id"): tool for tool in typed.get("tools", [])}
    overlap_report = {}
    for op_id in sorted(typed_ops & set(domain.operations)):
        op = domain.operations[op_id]
        tool = tool_map.get(op_id)
        if tool is None:
            problems.append(f"{op_id}: no typed tool definition")
            continue
        expected_schema = _argument_json_schema(domain, op_id)
        if tool.get("input_schema") != expected_schema:
            problems.append(f"{op_id}: typed tool argument schema differs from registry")
        base_name = tool["name"].split(".")[-1]
        if base_name != op.tool:
            problems.append(
                f"{op_id}: tool name {tool['name']} does not map to simulator tool {op.tool}"
            )
        description_tokens = _tokens(tool.get("description", ""))
        canonical_tokens = _tokens(op.display_name) | _tokens(op.operation_id.replace("_", " "))
        overlap = (
            len(description_tokens & canonical_tokens) / len(canonical_tokens)
            if canonical_tokens
            else 0.0
        )
        overlap_report[op_id] = round(overlap, 3)
    for op_id in sorted(set(domain.operations) - typed_ops):
        problems.append(f"{op_id}: missing from typed interface")
    return {
        "equivalent": not problems,
        "problems": problems,
        "tool_description_terminology_overlap": overlap_report,
    }
