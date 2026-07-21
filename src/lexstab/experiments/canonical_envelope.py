"""Controlled diagnostic for lexical collisions in canonical envelopes.

This experiment is intentionally outside the frozen benchmark matrix and its
headline metrics. It varies one envelope field while holding canonical intent,
state, tools, prompt, and execution model fixed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lexstab import domaintext
from lexstab.artifacts import jsonl_write
from lexstab.config import load_models_config
from lexstab.freeze import FrozenBenchmark
from lexstab.prompts import PromptLibrary
from lexstab.providers.registry import build_provider

CONDITIONS = {
    "LEGACY_STATUS_RESOLVED": {"status": "RESOLVED"},
    "MAPPING_OUTCOME_MAPPED": {"mapping_outcome": "MAPPED"},
    "NO_ENVELOPE_OUTCOME": {},
}


def run_canonical_envelope_diagnostic(
    root: Path,
    manifest_path: Path,
    models_path: Path,
    output: Path,
    *,
    case_ids: list[str] | None = None,
) -> dict[str, Any]:
    bench = FrozenBenchmark(root, manifest_path)
    config = load_models_config(
        models_path, strict_env=True, strict_roles={"execution_primary"}
    )
    role = config.role("execution_primary")
    provider = build_provider(role)
    prompt = PromptLibrary(root / "prompts").get("canonical-executor.v1")
    interface = bench.interfaces["TYPED_SUPPORT_TOOLS_V1"]
    tools = [
        {"name": tool["name"], "description": tool["description"], "input_schema": tool["input_schema"]}
        for tool in interface.tools
    ]
    selected = case_ids or [
        case_id for case_id, case in sorted(bench.cases.items())
        if case.gold.decision.value == "ACT"
    ]
    rows = []
    for case_id in selected:
        case = bench.cases[case_id]
        intent = case.canonical.model_dump(mode="json")
        for condition, envelope in CONDITIONS.items():
            payload = {**envelope, **intent}
            record = provider.invoke(
                role="execution_primary",
                model_id=role.model_id or "",
                messages=[{
                    "role": "system",
                    "content": prompt.render(
                        canonical_resolution=json.dumps(payload, indent=2, sort_keys=True),
                        operation_definitions=domaintext.operation_definitions_text(bench.domain),
                        known_state=domaintext.state_json(case.initial_state),
                    ),
                }],
                tools=tools,
                response_schema=None,
                parameters=role.parameters,
                metadata={
                    "run_id": "canonical-envelope-diagnostic",
                    "cell_id": f"{case_id}:{condition}",
                    "timestamp": "",
                    "response_kind": "canonical_executor",
                    "response_schema_id": prompt.response_schema,
                },
            )
            call = record.tool_calls[0] if record.tool_calls else None
            expected_tool = case.gold.tool
            expected_args = case.gold.arguments or {}
            correct = bool(
                call
                and call.get("tool") == expected_tool
                and call.get("arguments") == expected_args
            )
            rows.append({
                "case_id": case_id,
                "condition": condition,
                "payload": payload,
                "expected_tool": expected_tool,
                "expected_arguments": expected_args,
                "actual_tool_call": call,
                "correct": correct,
                "finish_reason": record.finish_reason,
                "reported_model_id": record.reported_model_id,
                "invocation": record.model_dump(mode="json"),
            })
    jsonl_write(output, rows)
    return {
        "diagnostic": "canonical-envelope-field-label",
        "headline_eligible": False,
        "output": str(output),
        "n": len(rows),
        "accuracy_by_condition": {
            condition: (
                sum(1 for row in rows if row["condition"] == condition and row["correct"])
                / sum(1 for row in rows if row["condition"] == condition)
            )
            for condition in CONDITIONS
        },
    }
