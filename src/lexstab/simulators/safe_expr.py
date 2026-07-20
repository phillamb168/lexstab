"""Restricted expression language for operation contracts (spec §11.4; D-005).

Grammar (whitespace-tolerant):

    condition := path CMP value
    effect    := path "=" value | path "+=" number | path "-=" number
    path      := IDENT ("." IDENT)*
    value     := path | literal | "run_clock"
    literal   := quoted string | integer | float | true | false | null
    CMP       := == | != | <= | >= | < | >

Paths resolve against a scope dict mapping root names (entity alias, argument
names, ``run_clock``) to values. Anything outside this grammar raises
``SafeExprError`` at parse time — dataset files can never execute code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_PATH_RE = re.compile(rf"^{_IDENT}(\.{_IDENT})*$")
_CMP_RE = re.compile(r"(==|!=|<=|>=|<|>)")
_ASSIGN_RE = re.compile(r"(\+=|-=|=)")
_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


class SafeExprError(ValueError):
    """Raised when an expression is outside the permitted grammar."""


@dataclass(frozen=True)
class Condition:
    left: str
    op: str
    right: Any  # ("path", str) | ("lit", value)
    source: str


@dataclass(frozen=True)
class Effect:
    target: str
    op: str  # "=", "+=", "-="
    value: Any  # ("path", str) | ("lit", value)
    source: str


def _parse_value(token: str) -> tuple[str, Any]:
    token = token.strip()
    if not token:
        raise SafeExprError("empty value")
    if (token.startswith("'") and token.endswith("'") and len(token) >= 2) or (
        token.startswith('"') and token.endswith('"') and len(token) >= 2
    ):
        return ("lit", token[1:-1])
    if token == "true":
        return ("lit", True)
    if token == "false":
        return ("lit", False)
    if token == "null":
        return ("lit", None)
    if _NUM_RE.match(token):
        return ("lit", float(token) if "." in token else int(token))
    if _PATH_RE.match(token):
        return ("path", token)
    raise SafeExprError(f"invalid value token: {token!r}")


def parse_condition(text: str) -> Condition:
    parts = _CMP_RE.split(text, maxsplit=1)
    if len(parts) != 3:
        raise SafeExprError(f"not a comparison: {text!r}")
    left, op, right = (part.strip() for part in parts)
    if not _PATH_RE.match(left):
        raise SafeExprError(f"invalid path on left side: {left!r}")
    return Condition(left=left, op=op, right=_parse_value(right), source=text)


def parse_effect(text: str) -> Effect:
    parts = _ASSIGN_RE.split(text, maxsplit=1)
    if len(parts) != 3:
        raise SafeExprError(f"not an assignment: {text!r}")
    target, op, value = parts[0].strip(), parts[1], parts[2].strip()
    if not _PATH_RE.match(target):
        raise SafeExprError(f"invalid assignment target: {target!r}")
    parsed = _parse_value(value)
    if op in ("+=", "-=") and not (
        parsed[0] == "lit" and isinstance(parsed[1], (int, float))
    ):
        raise SafeExprError(f"{op} requires a numeric literal: {text!r}")
    return Effect(target=target, op=op, value=parsed, source=text)


def resolve_path(scope: dict[str, Any], path: str) -> Any:
    node: Any = scope
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise SafeExprError(f"unresolvable path: {path!r}")
    return node


def _value_of(scope: dict[str, Any], value: tuple[str, Any]) -> Any:
    kind, payload = value
    return resolve_path(scope, payload) if kind == "path" else payload


def eval_condition(cond: Condition, scope: dict[str, Any]) -> bool:
    left = resolve_path(scope, cond.left)
    right = _value_of(scope, cond.right)
    if cond.op == "==":
        return left == right
    if cond.op == "!=":
        return left != right
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        raise SafeExprError(
            f"ordered comparison on non-numeric values: {cond.source!r}"
        )
    return {
        "<": left < right,
        "<=": left <= right,
        ">": left > right,
        ">=": left >= right,
    }[cond.op]


def apply_effect(effect: Effect, scope: dict[str, Any]) -> None:
    *parents, leaf = effect.target.split(".")
    node: Any = scope
    for part in parents:
        if not (isinstance(node, dict) and part in node):
            raise SafeExprError(f"unresolvable target: {effect.target!r}")
        node = node[part]
    if not isinstance(node, dict):
        raise SafeExprError(f"target is not assignable: {effect.target!r}")
    if effect.op == "=":
        node[leaf] = _value_of(scope, effect.value)
        return
    current = node.get(leaf)
    if not isinstance(current, (int, float)):
        raise SafeExprError(f"{effect.op} on non-numeric field: {effect.target!r}")
    delta = effect.value[1]
    node[leaf] = current + delta if effect.op == "+=" else current - delta


def validate_expressions(
    conditions: list[str], effects: list[str]
) -> tuple[list[Condition], list[Effect]]:
    """Parse all expressions, raising SafeExprError on the first invalid one."""
    return (
        [parse_condition(cond) for cond in conditions],
        [parse_effect(eff) for eff in effects],
    )
