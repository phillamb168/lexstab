"""Deterministic support-domain state simulator (spec §11.5).

The simulator is the primary oracle for whether a requested operation
succeeded. It applies only registered operations, validates preconditions
through the safe expression language, records every attempted call, and has no
external side effects. ``run_clock`` is the deterministic clock from the run
manifest (decision D-012).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from lexstab.artifacts import DomainStore
from lexstab.hashing import sha256_text, canonical_json
from lexstab.models import Operation
from lexstab.simulators.safe_expr import (
    SafeExprError,
    apply_effect,
    eval_condition,
    parse_condition,
    parse_effect,
)


@dataclass
class SimulatorEvent:
    event_type: str  # attempted | accepted | rejected | state_transition
    tool: str | None
    operation_id: str | None
    arguments: dict[str, Any]
    detail: str
    state_hash_before: str
    state_hash_after: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "tool": self.tool,
            "operation_id": self.operation_id,
            "arguments": self.arguments,
            "detail": self.detail,
            "state_hash_before": self.state_hash_before,
            "state_hash_after": self.state_hash_after,
        }


@dataclass
class ToolResult:
    accepted: bool
    detail: str
    error_category: str | None = None


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Deterministic normalized snapshot (sorted keys via canonical JSON)."""
    return json.loads(canonical_json(state))


def state_hash(state: dict[str, Any]) -> str:
    return sha256_text(canonical_json(state))


class SupportSimulator:
    """One simulator instance per matrix cell; always reset before reuse."""

    def __init__(self, domain: DomainStore, initial_state: dict[str, Any], run_clock: str):
        self.domain = domain
        self._initial_state = copy.deepcopy(initial_state)
        self.run_clock = run_clock
        self.state: dict[str, Any] = copy.deepcopy(initial_state)
        self.events: list[SimulatorEvent] = []
        self._tool_map = {op.tool: op for op in domain.operations.values()}

    # ------------------------------------------------------------ lifecycle

    def reset(self) -> None:
        self.state = copy.deepcopy(self._initial_state)
        self.events = []

    def snapshot(self) -> dict[str, Any]:
        return normalize_state(self.state)

    # ------------------------------------------------------------ scope

    def _entity_scope(self, op: Operation, entity_id: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        entity = self.domain.entities[op.entity_type]
        collection = self.state.get(entity.collection, {})
        if entity_id not in collection:
            return None
        scope: dict[str, Any] = dict(arguments)
        scope[entity.state_alias] = collection[entity_id]
        scope["run_clock"] = self.run_clock
        return scope

    def _entity_id_argument(self, op: Operation) -> str | None:
        entity = self.domain.entities[op.entity_type]
        expected = f"{entity.state_alias}_id"
        if expected in op.arguments:
            return expected
        for name, spec in op.arguments.items():
            if name.endswith("_id") and spec.type == "string":
                return name
        return None

    # ------------------------------------------------------------ execution

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        before = state_hash(self.state)
        self._record("attempted", tool, None, arguments, "tool call attempted", before, before)

        op = self._tool_map.get(tool)
        if op is None:
            self._record("rejected", tool, None, arguments, "unknown tool", before, before)
            return ToolResult(False, f"unknown tool {tool!r}", "unknown_tool")

        # argument validation against the operation contract
        problems = self._validate_arguments(op, arguments)
        if problems:
            detail = "; ".join(problems)
            self._record("rejected", tool, op.operation_id, arguments, detail, before, before)
            return ToolResult(False, detail, "invalid_arguments")

        id_arg = self._entity_id_argument(op)
        entity_id = arguments.get(id_arg) if id_arg else None
        if entity_id is None:
            detail = "entity id argument missing"
            self._record("rejected", tool, op.operation_id, arguments, detail, before, before)
            return ToolResult(False, detail, "invalid_arguments")

        scope = self._entity_scope(op, entity_id, arguments)
        if scope is None:
            detail = f"unknown entity {entity_id!r}"
            self._record("rejected", tool, op.operation_id, arguments, detail, before, before)
            return ToolResult(False, detail, "unknown_entity")

        try:
            for cond_text in op.invalid_when:
                if eval_condition(parse_condition(cond_text), scope):
                    detail = f"invalid_when: {cond_text}"
                    self._record("rejected", tool, op.operation_id, arguments, detail, before, before)
                    return ToolResult(False, detail, "precondition_failed")
            for cond_text in op.preconditions:
                if not eval_condition(parse_condition(cond_text), scope):
                    detail = f"precondition failed: {cond_text}"
                    self._record("rejected", tool, op.operation_id, arguments, detail, before, before)
                    return ToolResult(False, detail, "precondition_failed")
            for effect_text in op.effects:
                apply_effect(parse_effect(effect_text), scope)
        except SafeExprError as exc:
            detail = f"expression error: {exc}"
            self._record("rejected", tool, op.operation_id, arguments, detail, before, before)
            return ToolResult(False, detail, "expression_error")

        after = state_hash(self.state)
        self._record("accepted", tool, op.operation_id, arguments, "applied", before, after)
        self._record("state_transition", tool, op.operation_id, arguments, "effects applied", before, after)
        return ToolResult(True, "applied")

    def _validate_arguments(self, op: Operation, arguments: dict[str, Any]) -> list[str]:
        problems = []
        for name, spec in op.arguments.items():
            if spec.required and name not in arguments:
                problems.append(f"missing required argument {name}")
        for name, value in arguments.items():
            spec = op.arguments.get(name)
            if spec is None:
                problems.append(f"unknown argument {name}")
                continue
            expected = {
                "string": str,
                "integer": int,
                "number": (int, float),
                "boolean": bool,
                "array": list,
                "object": dict,
            }[spec.type]
            if spec.type == "integer" and isinstance(value, bool):
                problems.append(f"argument {name} must be an integer")
                continue
            if not isinstance(value, expected):
                problems.append(f"argument {name} has wrong type")
                continue
            if spec.pattern and isinstance(value, str):
                import re

                if not re.match(spec.pattern, value):
                    problems.append(f"argument {name} does not match pattern")
            if spec.minimum is not None and isinstance(value, (int, float)) and value < spec.minimum:
                problems.append(f"argument {name} below minimum")
            if spec.maximum is not None and isinstance(value, (int, float)) and value > spec.maximum:
                problems.append(f"argument {name} above maximum")
            if spec.enum is not None and value not in spec.enum:
                problems.append(f"argument {name} not in enum")
        return problems

    def _record(
        self,
        event_type: str,
        tool: str | None,
        operation_id: str | None,
        arguments: dict[str, Any],
        detail: str,
        before: str,
        after: str,
    ) -> None:
        self.events.append(
            SimulatorEvent(
                event_type=event_type,
                tool=tool,
                operation_id=operation_id,
                arguments=copy.deepcopy(arguments),
                detail=detail,
                state_hash_before=before,
                state_hash_after=after,
            )
        )


def recompute_gold_state(
    domain: DomainStore, case_initial_state: dict, gold_tool: str, gold_arguments: dict, run_clock: str
) -> tuple[bool, dict[str, Any], str]:
    """Recompute the gold transition; used at freeze time (spec §16.2 item 3)."""
    sim = SupportSimulator(domain, case_initial_state, run_clock)
    result = sim.call_tool(gold_tool, gold_arguments)
    return result.accepted, sim.snapshot(), result.detail
