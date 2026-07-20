"""Unit tests: content hashing (D-006) and the safe expression language (D-005)."""

import pytest

from lexstab.hashing import (
    canonical_json,
    hash_json_artifact,
    root_hash,
    stamp_content_hash,
    verify_content_hash,
)
from lexstab.simulators.safe_expr import (
    SafeExprError,
    apply_effect,
    eval_condition,
    parse_condition,
    parse_effect,
)


class TestHashing:
    def test_canonical_json_is_order_insensitive(self):
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})

    def test_hash_ignores_embedded_content_hash(self):
        base = {"x": 1, "provenance": {"content_hash": None}}
        stamped = stamp_content_hash(base)
        assert stamped["provenance"]["content_hash"].startswith("sha256:")
        assert hash_json_artifact(stamped) == hash_json_artifact(base)

    def test_verify_content_hash_detects_tamper(self):
        stamped = stamp_content_hash({"x": 1, "content_hash": None})
        assert verify_content_hash(stamped)
        stamped["x"] = 2
        assert not verify_content_hash(stamped)

    def test_root_hash_stable_under_ordering(self):
        inventory = {"b.json": "sha256:bb", "a.json": "sha256:aa"}
        assert root_hash(inventory) == root_hash(dict(reversed(list(inventory.items()))))


class TestSafeExpr:
    def test_condition_evaluation(self):
        scope = {"incident": {"status": "OPEN", "support_tier": 1}, "destination_tier": 2}
        assert eval_condition(parse_condition("incident.status == 'OPEN'"), scope)
        assert eval_condition(parse_condition("destination_tier > incident.support_tier"), scope)
        assert not eval_condition(parse_condition("incident.support_tier >= 3"), scope)

    def test_effects(self):
        scope = {"incident": {"support_tier": 1, "escalation_count": 0},
                 "destination_tier": 3, "run_clock": "T0"}
        apply_effect(parse_effect("incident.support_tier = destination_tier"), scope)
        apply_effect(parse_effect("incident.escalation_count += 1"), scope)
        apply_effect(parse_effect("incident.updated_at = run_clock"), scope)
        assert scope["incident"] == {"support_tier": 3, "escalation_count": 1, "updated_at": "T0"}

    @pytest.mark.parametrize("expr", [
        "__import__('os').system('true')",
        "incident.status == open()",
        "incident.status ; drop",
        "incident.status == 'OPEN' or true",
        "len(incident)",
    ])
    def test_arbitrary_code_rejected(self, expr):
        with pytest.raises(SafeExprError):
            parse_condition(expr)

    def test_increment_requires_numeric_literal(self):
        with pytest.raises(SafeExprError):
            parse_effect("incident.count += destination_tier")

    def test_unresolvable_path_raises(self):
        with pytest.raises(SafeExprError):
            eval_condition(parse_condition("missing.field == 1"), {})
