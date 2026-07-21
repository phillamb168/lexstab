"""Exact non-action contracts for P4 and LP3 typed boundaries."""

import json

from lexstab import models
from lexstab.runner import _parse_decision, _validate_proposal


def _record(*, obj=None, tool_calls=None):
    text = json.dumps(obj) if obj is not None else None
    return models.InvocationRecord(
        run_id="test",
        cell_id="cell-test",
        role="execution_primary",
        provider="mock",
        requested_model_id="mock",
        timestamp="2026-07-20T00:00:00Z",
        messages=[],
        requested_parameters={},
        raw_response=obj or tool_calls or {},
        normalized_text=text,
        tool_calls=tool_calls or [],
        tool_call_mode="mock",
    )


def test_strict_typed_boundary_accepts_exact_clarification_and_refusal():
    clarify = _parse_decision(
        _record(obj={"decision": "CLARIFY", "question": "Which tier?", "reason_code": None}),
        strict_typed_boundary=True,
    )
    refuse = _parse_decision(
        _record(obj={"decision": "REFUSE", "question": None, "reason_code": "CLOSED"}),
        strict_typed_boundary=True,
    )
    assert clarify == ("CLARIFY", None, "Which tier?", None, True)
    assert refuse == ("REFUSE", None, None, "CLOSED", True)


def test_strict_typed_boundary_rejects_incomplete_or_wrapped_non_actions():
    missing_null = _parse_decision(
        _record(obj={"decision": "CLARIFY", "question": "Which tier?"}),
        strict_typed_boundary=True,
    )
    wrapped = _parse_decision(
        _record(obj={
            "decision": "REFUSE",
            "question": None,
            "reason_code": "CLOSED",
            "proposal": {},
        }),
        strict_typed_boundary=True,
    )
    assert missing_null[-1] is False
    assert wrapped[-1] is False


def test_strict_typed_boundary_requires_exactly_one_tool_call_for_action():
    one = _parse_decision(
        _record(tool_calls=[{"tool": "close_incident", "arguments": {"incident_id": "INC-2450"}}]),
        strict_typed_boundary=True,
    )
    two = _parse_decision(
        _record(tool_calls=[
            {"tool": "close_incident", "arguments": {"incident_id": "INC-2450"}},
            {"tool": "close_incident", "arguments": {"incident_id": "INC-2450"}},
        ]),
        strict_typed_boundary=True,
    )
    assert one[0] == "ACT" and one[-1] is True
    assert two[-1] is False


def test_generic_proposal_contract_accepts_all_decisions_and_rejects_wrapper():
    act = {
        "decision": "ACT",
        "operation_id": "ESCALATE_INCIDENT",
        "arguments": {"incident_id": "INC-1047", "destination_tier": 2},
        "question": None,
        "reason_code": None,
    }
    clarify = {
        "decision": "CLARIFY",
        "operation_id": None,
        "arguments": {},
        "question": "Which support tier?",
        "reason_code": None,
    }
    refuse = {
        "decision": "REFUSE",
        "operation_id": None,
        "arguments": {},
        "question": None,
        "reason_code": "INCIDENT_CLOSED",
    }
    for proposal in (act, clarify, refuse):
        parsed, error = _validate_proposal(proposal)
        assert parsed == proposal
        assert error is None

    wrapped, error = _validate_proposal({"proposal": act})
    assert wrapped is None
    assert error and error.startswith("proposal_schema:")
