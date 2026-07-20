"""Build the starter support-domain dataset (decision D-011).

Generates domain files, canonical cases (gold states recomputed through the
simulator), labeled requests, frozen-context sources, renderings, procedures,
interfaces, memory records, elicitation cases, and splits — all in *approved*
status. `lexstab benchmark freeze` turns approved artifacts into the frozen,
hashed benchmark. Deterministic: rerunning produces identical bytes.

Run:  uv run python scripts/build_starter_dataset.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lexstab import models  # noqa: E402
from lexstab.artifacts import (  # noqa: E402
    DomainStore,
    json_write,
    jsonl_write,
    load_cases,
    referential_integrity,
    load_requests,
    load_contexts,
    load_renderings,
    load_procedures,
    load_interfaces,
)
from lexstab.interfaces import (  # noqa: E402
    build_generic_interface,
    build_mcp_interface,
    build_typed_interface,
)
from lexstab.simulators.support_domain import recompute_gold_state  # noqa: E402

CREATED_AT = "2026-07-20T00:00:00Z"
RUN_CLOCK_PLACEHOLDER = "<run_clock>"
REVIEWER = "starter-fixture-reviewer"

SPEC_VERSION = models.SCHEMA_VERSION

# ---------------------------------------------------------------- domain

ENTITIES = [
    {
        "schema_version": SPEC_VERSION,
        "entity_type": "INCIDENT",
        "id_pattern": "^INC-[0-9]{4}$",
        "state_alias": "incident",
        "collection": "incidents",
        "required_state": {
            "status": {"type": "string", "required": True, "enum": ["OPEN", "CLOSED", "PENDING_INFO"]},
            "severity": {"type": "string", "required": True, "enum": ["SEV-1", "SEV-2", "SEV-3"]},
            "support_tier": {"type": "integer", "required": True, "minimum": 1, "maximum": 4},
            "assigned_team": {"type": "string", "required": True},
            "information_complete": {"type": "boolean", "required": True},
            "escalation_count": {"type": "integer", "required": True, "minimum": 0},
            "updated_at": {"type": "string", "required": False},
        },
        "description": "A support incident with status, severity, support tier, assigned team, and information completeness.",
    },
    {
        "schema_version": SPEC_VERSION,
        "entity_type": "CUSTOMER",
        "id_pattern": "^CUS-[0-9]{4}$",
        "state_alias": "customer",
        "collection": "customers",
        "required_state": {
            "status": {"type": "string", "required": True, "enum": ["ACTIVE", "AT_RISK", "CHURNED"]},
            "risk_flag": {"type": "boolean", "required": True},
            "linked_accounts": {"type": "array", "required": True},
        },
        "description": "A customer with status, risk flag, and linked accounts.",
    },
    {
        "schema_version": SPEC_VERSION,
        "entity_type": "ORDER",
        "id_pattern": "^ORD-[0-9]{4}$",
        "state_alias": "order",
        "collection": "orders",
        "required_state": {
            "charge_count": {"type": "integer", "required": True, "minimum": 0},
            "duplicate_charge_confirmed": {"type": "boolean", "required": True},
            "duplicate_charge_amount_usd": {"type": "number", "required": False, "minimum": 0},
            "refund_state": {"type": "string", "required": True, "enum": ["NONE", "REFUNDED", "PENDING_REVIEW"]},
            "payment_state": {"type": "string", "required": True, "enum": ["PAID", "PARTIAL_REFUND", "REFUNDED"]},
            "fulfillment_state": {"type": "string", "required": True, "enum": ["PENDING", "SHIPPED", "DELIVERED"]},
            "refunded_amount_usd": {"type": "number", "required": False, "minimum": 0},
            "updated_at": {"type": "string", "required": False},
        },
        "description": "An order with charge records, payment state, and fulfillment state.",
    },
    {
        "schema_version": SPEC_VERSION,
        "entity_type": "ACCOUNT",
        "id_pattern": "^ACC-[0-9]{4}$",
        "state_alias": "account",
        "collection": "accounts",
        "required_state": {
            "status": {"type": "string", "required": True, "enum": ["ACTIVE", "SUSPENDED", "CLOSED"]},
            "suspension_state": {"type": "string", "required": True, "enum": ["NONE", "SUSPENDED"]},
            "owner": {"type": "string", "required": True},
            "suspension_reason": {"type": "string", "required": False},
            "updated_at": {"type": "string", "required": False},
        },
        "description": "An account with status, suspension state, and owner.",
    },
    {
        "schema_version": SPEC_VERSION,
        "entity_type": "APPROVAL_REQUEST",
        "id_pattern": "^APR-[0-9]{4}$",
        "state_alias": "approval",
        "collection": "approvals",
        "required_state": {
            "operation_requested": {"type": "string", "required": True},
            "amount_usd": {"type": "number", "required": True, "minimum": 0},
            "status": {"type": "string", "required": True, "enum": ["PENDING", "ROUTED", "APPROVED", "DENIED"]},
            "approver_role": {"type": "string", "required": False},
            "updated_at": {"type": "string", "required": False},
        },
        "description": "An approval request with the operation requested, amount, status, and approver role.",
    },
]

OPERATIONS = [
    {
        "schema_version": SPEC_VERSION,
        "operation_id": "ESCALATE_INCIDENT",
        "display_name": "Escalate incident",
        "entity_type": "INCIDENT",
        "tool": "escalate_incident",
        "arguments": {
            "incident_id": {"type": "string", "required": True, "pattern": "^INC-[0-9]{4}$"},
            "destination_tier": {"type": "integer", "required": True, "minimum": 2, "maximum": 4},
        },
        "preconditions": ["incident.status == 'OPEN'", "destination_tier > incident.support_tier"],
        "effects": [
            "incident.support_tier = destination_tier",
            "incident.escalation_count += 1",
            "incident.updated_at = run_clock",
        ],
        "invalid_when": ["incident.status == 'CLOSED'"],
        "primary_contrast": "REASSIGN_INCIDENT",
        "description": "Transfer responsibility for an open incident to a higher support tier.",
    },
    {
        "schema_version": SPEC_VERSION,
        "operation_id": "REASSIGN_INCIDENT",
        "display_name": "Reassign incident",
        "entity_type": "INCIDENT",
        "tool": "reassign_incident",
        "arguments": {
            "incident_id": {"type": "string", "required": True, "pattern": "^INC-[0-9]{4}$"},
            "destination_team": {
                "type": "string",
                "required": True,
                "enum": ["SERVICE_DESK", "BILLING", "SECURITY", "PAYMENTS", "FRAUD"],
            },
        },
        "preconditions": ["incident.status == 'OPEN'"],
        "effects": ["incident.assigned_team = destination_team", "incident.updated_at = run_clock"],
        "invalid_when": ["incident.status == 'CLOSED'"],
        "primary_contrast": "ESCALATE_INCIDENT",
        "description": "Move an open incident to a different owning team without changing its support tier.",
    },
    {
        "schema_version": SPEC_VERSION,
        "operation_id": "CLOSE_INCIDENT",
        "display_name": "Close incident",
        "entity_type": "INCIDENT",
        "tool": "close_incident",
        "arguments": {
            "incident_id": {"type": "string", "required": True, "pattern": "^INC-[0-9]{4}$"},
        },
        "preconditions": ["incident.status == 'OPEN'", "incident.information_complete == true"],
        "effects": ["incident.status = 'CLOSED'", "incident.updated_at = run_clock"],
        "invalid_when": [],
        "primary_contrast": "REQUEST_MORE_INFORMATION",
        "description": "Close an open incident whose information is complete.",
    },
    {
        "schema_version": SPEC_VERSION,
        "operation_id": "REQUEST_MORE_INFORMATION",
        "display_name": "Request more information",
        "entity_type": "INCIDENT",
        "tool": "request_more_information",
        "arguments": {
            "incident_id": {"type": "string", "required": True, "pattern": "^INC-[0-9]{4}$"},
            "topic": {"type": "string", "required": False},
        },
        "preconditions": ["incident.status == 'OPEN'"],
        "effects": ["incident.status = 'PENDING_INFO'", "incident.updated_at = run_clock"],
        "invalid_when": [],
        "primary_contrast": "CLOSE_INCIDENT",
        "description": "Ask the reporter of an open incident for additional information.",
    },
    {
        "schema_version": SPEC_VERSION,
        "operation_id": "REQUEST_APPROVAL",
        "display_name": "Request approval",
        "entity_type": "APPROVAL_REQUEST",
        "tool": "request_approval",
        "arguments": {
            "approval_id": {"type": "string", "required": True, "pattern": "^APR-[0-9]{4}$"},
            "approver_role": {"type": "string", "required": True, "enum": ["MANAGER", "DIRECTOR", "FINANCE"]},
        },
        "preconditions": ["approval.status == 'PENDING'"],
        "effects": [
            "approval.status = 'ROUTED'",
            "approval.approver_role = approver_role",
            "approval.updated_at = run_clock",
        ],
        "invalid_when": [],
        "primary_contrast": None,
        "description": "Route a pending approval request to the named approver role.",
    },
    {
        "schema_version": SPEC_VERSION,
        "operation_id": "REFUND_DUPLICATE_CHARGE",
        "display_name": "Refund duplicate charge",
        "entity_type": "ORDER",
        "tool": "refund_duplicate_charge",
        "arguments": {
            "order_id": {"type": "string", "required": True, "pattern": "^ORD-[0-9]{4}$"},
            "amount_usd": {"type": "number", "required": True, "minimum": 0.01, "maximum": 499.99},
        },
        "preconditions": [
            "order.duplicate_charge_confirmed == true",
            "order.refund_state == 'NONE'",
        ],
        "effects": [
            "order.refund_state = 'REFUNDED'",
            "order.refunded_amount_usd = amount_usd",
            "order.payment_state = 'PARTIAL_REFUND'",
            "order.updated_at = run_clock",
        ],
        "invalid_when": [],
        "primary_contrast": "REQUEST_MANAGER_REVIEW",
        "description": "Refund a confirmed duplicate charge below 500 USD on an order.",
    },
    {
        "schema_version": SPEC_VERSION,
        "operation_id": "REQUEST_MANAGER_REVIEW",
        "display_name": "Request manager review",
        "entity_type": "ORDER",
        "tool": "request_manager_review",
        "arguments": {
            "order_id": {"type": "string", "required": True, "pattern": "^ORD-[0-9]{4}$"},
            "reason_code": {
                "type": "string",
                "required": True,
                "enum": ["DISPUTED_CHARGE", "HIGH_VALUE", "OTHER"],
            },
        },
        "preconditions": ["order.refund_state == 'NONE'"],
        "effects": ["order.refund_state = 'PENDING_REVIEW'", "order.updated_at = run_clock"],
        "invalid_when": [],
        "primary_contrast": "REFUND_DUPLICATE_CHARGE",
        "description": "Send an order charge issue to a manager for review instead of acting directly.",
    },
    {
        "schema_version": SPEC_VERSION,
        "operation_id": "SUSPEND_ACCOUNT",
        "display_name": "Suspend account",
        "entity_type": "ACCOUNT",
        "tool": "suspend_account",
        "arguments": {
            "account_id": {"type": "string", "required": True, "pattern": "^ACC-[0-9]{4}$"},
            "reason_code": {"type": "string", "required": True, "enum": ["FRAUD", "ABUSE", "NON_PAYMENT"]},
        },
        "preconditions": ["account.status == 'ACTIVE'"],
        "effects": [
            "account.status = 'SUSPENDED'",
            "account.suspension_state = 'SUSPENDED'",
            "account.suspension_reason = reason_code",
            "account.updated_at = run_clock",
        ],
        "invalid_when": [],
        "primary_contrast": "CLOSE_INCIDENT",
        "description": "Suspend an active account for a fraud, abuse, or non-payment reason.",
    },
]

POLICIES = [
    {"policy_id": "P-17", "text": "A confirmed duplicate charge below 500 USD may be refunded without manager approval.", "applies_to_operation_ids": ["REFUND_DUPLICATE_CHARGE"]},
    {"policy_id": "P-18", "text": "A disputed legitimate charge requires manager review.", "applies_to_operation_ids": ["REQUEST_MANAGER_REVIEW"]},
    {"policy_id": "P-19", "text": "A refund request with an unconfirmed duplicate requires additional transaction information before any refund.", "applies_to_operation_ids": ["REFUND_DUPLICATE_CHARGE", "REQUEST_MORE_INFORMATION"]},
    {"policy_id": "P-20", "text": "A closed incident may not be escalated or reassigned.", "applies_to_operation_ids": ["ESCALATE_INCIDENT", "REASSIGN_INCIDENT"]},
    {"policy_id": "P-21", "text": "An incident may not be closed while its information is incomplete.", "applies_to_operation_ids": ["CLOSE_INCIDENT"]},
    {"policy_id": "P-22", "text": "Refunds of 500 USD or more require an approval request before execution.", "applies_to_operation_ids": ["REQUEST_APPROVAL", "REFUND_DUPLICATE_CHARGE"]},
    {"policy_id": "P-23", "text": "Account suspension requires an active account and a fraud, abuse, or non-payment reason.", "applies_to_operation_ids": ["SUSPEND_ACCOUNT"]},
]

INITIAL_STATE = {
    "incidents": {
        "INC-1047": {"status": "OPEN", "severity": "SEV-2", "support_tier": 1, "assigned_team": "SERVICE_DESK", "information_complete": True, "escalation_count": 0},
    },
    "customers": {
        "CUS-0104": {"status": "ACTIVE", "risk_flag": False, "linked_accounts": ["ACC-4002"]},
    },
    "orders": {
        "ORD-0077": {"charge_count": 2, "duplicate_charge_confirmed": True, "duplicate_charge_amount_usd": 120.0, "refund_state": "NONE", "payment_state": "PAID", "fulfillment_state": "DELIVERED"},
    },
    "accounts": {
        "ACC-4002": {"status": "ACTIVE", "suspension_state": "NONE", "owner": "CUS-0104"},
    },
    "approvals": {
        "APR-0021": {"operation_requested": "REFUND_DUPLICATE_CHARGE", "amount_usd": 750.0, "status": "PENDING"},
    },
}


# ---------------------------------------------------------------- cases


def _incident(status="OPEN", severity="SEV-2", tier=1, team="SERVICE_DESK", complete=True, escalations=0):
    return {
        "status": status, "severity": severity, "support_tier": tier,
        "assigned_team": team, "information_complete": complete,
        "escalation_count": escalations,
    }


CASES: list[dict] = []


def add_case(case_id, family, title, canonical, initial_state, gold, tags, difficulty="basic"):
    CASES.append(
        {
            "schema_version": SPEC_VERSION,
            "case_id": case_id,
            "domain": "support",
            "title": title,
            "family_id": family,
            "canonical": canonical,
            "initial_state": initial_state,
            "gold": gold,
            "tags": tags,
            "difficulty": difficulty,
            "created_by": "human",
            "created_at": CREATED_AT,
        }
    )


def act_gold(domain: DomainStore, initial_state, tool, arguments):
    accepted, resulting, detail = recompute_gold_state(
        domain, initial_state, tool, arguments, RUN_CLOCK_PLACEHOLDER
    )
    if not accepted:
        raise SystemExit(f"gold transition rejected for {tool}: {detail}")
    return {"decision": "ACT", "tool": tool, "arguments": arguments, "resulting_state": resulting}


def build_cases(domain: DomainStore) -> None:
    add_case(
        "ESCALATE_001", "ESCALATE", "Escalate an open incident from Tier 1 to Tier 2",
        {"entity_type": "INCIDENT", "entity_id": "INC-1047", "operation_id": "ESCALATE_INCIDENT", "arguments": {"destination_tier": 2}},
        {"incidents": {"INC-1047": _incident()}},
        act_gold(domain, {"incidents": {"INC-1047": _incident()}}, "escalate_incident", {"incident_id": "INC-1047", "destination_tier": 2}),
        ["single_turn", "tool_selection", "entity_operation_pair"],
    )
    add_case(
        "ESCALATE_002", "ESCALATE", "Escalate an open incident from Tier 2 to Tier 3",
        {"entity_type": "INCIDENT", "entity_id": "INC-2033", "operation_id": "ESCALATE_INCIDENT", "arguments": {"destination_tier": 3}},
        {"incidents": {"INC-2033": _incident(tier=2, severity="SEV-1", escalations=1)}},
        act_gold(domain, {"incidents": {"INC-2033": _incident(tier=2, severity="SEV-1", escalations=1)}}, "escalate_incident", {"incident_id": "INC-2033", "destination_tier": 3}),
        ["single_turn", "tool_selection"],
    )
    add_case(
        "ESCALATE_003", "ESCALATE", "Escalate with the destination described by team authority",
        {"entity_type": "INCIDENT", "entity_id": "INC-2210", "operation_id": "ESCALATE_INCIDENT", "arguments": {"destination_tier": 3}},
        {"incidents": {"INC-2210": _incident()}},
        act_gold(domain, {"incidents": {"INC-2210": _incident()}}, "escalate_incident", {"incident_id": "INC-2210", "destination_tier": 3}),
        ["single_turn", "tool_selection", "indirect_destination"],
        "intermediate",
    )
    add_case(
        "ESCALATE_004", "ESCALATE", "Escalation requested on a closed incident must be refused",
        {"entity_type": "INCIDENT", "entity_id": "INC-3001", "operation_id": "ESCALATE_INCIDENT", "arguments": {"destination_tier": 2}},
        {"incidents": {"INC-3001": _incident(status="CLOSED")}},
        {"decision": "REFUSE", "refusal_reason_code": "FAILED_PRECONDITION", "refusal_policy_id": "P-20"},
        ["single_turn", "refusal", "precondition"],
        "intermediate",
    )
    add_case(
        "ESCALATE_005", "ESCALATE", "Ambiguous upward move must trigger clarification",
        {"entity_type": "INCIDENT", "entity_id": "INC-1047", "operation_id": "ESCALATE_INCIDENT", "arguments": {"destination_tier": 2}},
        {"incidents": {"INC-1047": _incident()}},
        {"decision": "CLARIFY", "clarification_targets": ["operation_choice", "destination_tier"]},
        ["single_turn", "clarification", "ambiguity"],
        "intermediate",
    )
    add_case(
        "REASSIGN_001", "REASSIGN", "Reassign an open incident to the Billing team without changing tier",
        {"entity_type": "INCIDENT", "entity_id": "INC-1047", "operation_id": "REASSIGN_INCIDENT", "arguments": {"destination_team": "BILLING"}},
        {"incidents": {"INC-1047": _incident()}},
        act_gold(domain, {"incidents": {"INC-1047": _incident()}}, "reassign_incident", {"incident_id": "INC-1047", "destination_team": "BILLING"}),
        ["single_turn", "tool_selection", "entity_operation_pair"],
    )
    add_case(
        "CLOSE_001", "CLOSE", "Close an open incident whose information is complete",
        {"entity_type": "INCIDENT", "entity_id": "INC-2450", "operation_id": "CLOSE_INCIDENT", "arguments": {}},
        {"incidents": {"INC-2450": _incident(severity="SEV-3")}},
        act_gold(domain, {"incidents": {"INC-2450": _incident(severity="SEV-3")}}, "close_incident", {"incident_id": "INC-2450"}),
        ["single_turn", "tool_selection"],
    )
    add_case(
        "RMI_001", "RMI", "Request more information on an incomplete incident",
        {"entity_type": "INCIDENT", "entity_id": "INC-3120", "operation_id": "REQUEST_MORE_INFORMATION", "arguments": {}},
        {"incidents": {"INC-3120": _incident(complete=False)}},
        act_gold(domain, {"incidents": {"INC-3120": _incident(complete=False)}}, "request_more_information", {"incident_id": "INC-3120"}),
        ["single_turn", "tool_selection"],
    )
    refund_state = {
        "orders": {"ORD-0077": dict(INITIAL_STATE["orders"]["ORD-0077"])},
        "customers": {"CUS-0104": dict(INITIAL_STATE["customers"]["CUS-0104"])},
    }
    add_case(
        "REFUND_001", "REFUND", "Refund a confirmed duplicate charge of 120 USD",
        {"entity_type": "ORDER", "entity_id": "ORD-0077", "operation_id": "REFUND_DUPLICATE_CHARGE", "arguments": {"amount_usd": 120.0}},
        refund_state,
        act_gold(domain, refund_state, "refund_duplicate_charge", {"order_id": "ORD-0077", "amount_usd": 120.0}),
        ["single_turn", "tool_selection", "policy_dependent"],
        "intermediate",
    )
    review_state = {
        "orders": {"ORD-0912": {"charge_count": 1, "duplicate_charge_confirmed": False, "refund_state": "NONE", "payment_state": "PAID", "fulfillment_state": "DELIVERED"}},
    }
    add_case(
        "REVIEW_001", "REVIEW", "Send a disputed legitimate charge to manager review",
        {"entity_type": "ORDER", "entity_id": "ORD-0912", "operation_id": "REQUEST_MANAGER_REVIEW", "arguments": {"reason_code": "DISPUTED_CHARGE"}},
        review_state,
        act_gold(domain, review_state, "request_manager_review", {"order_id": "ORD-0912", "reason_code": "DISPUTED_CHARGE"}),
        ["single_turn", "tool_selection", "policy_dependent"],
        "intermediate",
    )
    suspend_state = {
        "accounts": {"ACC-4002": dict(INITIAL_STATE["accounts"]["ACC-4002"])},
        "incidents": {"INC-4410": _incident(severity="SEV-3")},
    }
    add_case(
        "SUSPEND_001", "SUSPEND", "Suspend an active account for confirmed fraud",
        {"entity_type": "ACCOUNT", "entity_id": "ACC-4002", "operation_id": "SUSPEND_ACCOUNT", "arguments": {"reason_code": "FRAUD"}},
        suspend_state,
        act_gold(domain, suspend_state, "suspend_account", {"account_id": "ACC-4002", "reason_code": "FRAUD"}),
        ["single_turn", "tool_selection"],
        "intermediate",
    )
    approval_state = {
        "approvals": {"APR-0021": dict(INITIAL_STATE["approvals"]["APR-0021"])},
        "orders": {"ORD-0077": {"charge_count": 2, "duplicate_charge_confirmed": True, "duplicate_charge_amount_usd": 750.0, "refund_state": "NONE", "payment_state": "PAID", "fulfillment_state": "DELIVERED"}},
    }
    add_case(
        "APPROVAL_001", "APPROVAL", "Route a 750 USD refund approval request to a manager",
        {"entity_type": "APPROVAL_REQUEST", "entity_id": "APR-0021", "operation_id": "REQUEST_APPROVAL", "arguments": {"approver_role": "MANAGER"}},
        approval_state,
        act_gold(domain, approval_state, "request_approval", {"approval_id": "APR-0021", "approver_role": "MANAGER"}),
        ["single_turn", "tool_selection", "policy_dependent"],
        "intermediate",
    )


# ---------------------------------------------------------------- contexts

CONTEXTS = [
    {
        "schema_version": SPEC_VERSION,
        "context_id": "CTX-EMPTY-001",
        "messages": [],
        "visible_state": {},
        "available_to_architectures": models.ARCHITECTURES,
        "content_hash": None,
    },
    {
        "schema_version": SPEC_VERSION,
        "context_id": "CTX-INC-1047-IDENTIFIED-001",
        "messages": [
            {"role": "user", "content": "We are discussing incident INC-1047, which is currently assigned to Tier 1."}
        ],
        "visible_state": {"active_incident_id": "INC-1047"},
        "available_to_architectures": models.ARCHITECTURES,
        "content_hash": None,
    },
]


# ---------------------------------------------------------------- requests

REQUESTS: list[dict] = []
_COUNTERS: dict[str, int] = {}


def _rid(case_id: str, kind: str) -> str:
    base = "REQ-" + case_id.replace("_", "-")
    key = f"{base}:{kind}"
    _COUNTERS[key] = _COUNTERS.get(key, 0) + 1
    suffix = f"{_COUNTERS[key]:04d}"
    return f"{base}-{suffix}" if kind == "STD" else f"{base}-{kind}-{suffix}"


def _request(case_id, kind, text, labels, source_type="human"):
    labels.setdefault("missing_information", [])
    labels.setdefault("context_id", None)
    labels.setdefault("contains_canonical_entity_term", False)
    labels.setdefault("contains_canonical_operation_term", False)
    labels.setdefault("contains_model_discovered_term", False)
    labels.setdefault("contains_organization_term", False)
    labels.setdefault("lexical_distance_band", "MEDIUM")
    REQUESTS.append(
        {
            "schema_version": SPEC_VERSION,
            "request_id": _rid(case_id, kind),
            "case_id": case_id,
            "text": text,
            "language": "en-US",
            "source": {"type": source_type, "creator": "starter-fixture", "model_provider": None, "model_id": None, "prompt_id": None, "seed": None},
            "labels": labels,
            "validation": {
                "status": "APPROVED",
                "semantic_equivalence": labels["lexical_equivalence"] == "INVARIANT" or None,
                "adequacy_verified": True,
                "ambiguity_verified": True,
                "reviewers": [
                    {"reviewer_id": REVIEWER, "decision": "APPROVE", "notes": "starter fixture", "reviewed_at": CREATED_AT}
                ],
                "approved_by": REVIEWER,
                "approved_at": CREATED_AT,
                "critic_judgments": [],
            },
            "provenance": {"created_at": CREATED_AT, "source_run_id": None, "parent_request_id": None, "content_hash": None},
            "audio_uri": None,
            "transcript_kind": "typed",
        }
    )


def inv(case_id, text, axes, band="MEDIUM", canonical_entity=False, canonical_op=False, org=False):
    _request(case_id, "STD", text, {
        "semantic_role": "INVARIANT", "adequacy": "ADEQUATE", "ambiguity": "UNAMBIGUOUS",
        "expected_behavior": "EXECUTE", "lexical_equivalence": "INVARIANT",
        "variation_axes": axes + ["typed"], "lexical_distance_band": band,
        "contains_canonical_entity_term": canonical_entity,
        "contains_canonical_operation_term": canonical_op,
        "contains_organization_term": org,
    })


def clar(case_id, text, axes, missing, context="CTX-EMPTY-001", ambiguity="AMBIGUOUS"):
    _request(case_id, "INADEQUATE", text, {
        "semantic_role": "CLARIFICATION", "adequacy": "INADEQUATE", "ambiguity": ambiguity,
        "expected_behavior": "CLARIFY", "lexical_equivalence": "NOT_APPLICABLE",
        "variation_axes": axes + ["typed"], "missing_information": missing, "context_id": context,
    })


def contrast(case_id, text, axes, op_id, arguments):
    _request(case_id, "CONTRAST", text, {
        "semantic_role": "CONTRAST", "adequacy": "ADEQUATE", "ambiguity": "UNAMBIGUOUS",
        "expected_behavior": "EXECUTE", "lexical_equivalence": "CONTRAST",
        "variation_axes": axes + ["typed", "minimal_semantic_contrast"],
        "contrast_operation_id": op_id, "contrast_arguments": arguments,
    })


def refusal(case_id, text, axes, op_id, policy):
    _request(case_id, "REFUSAL", text, {
        "semantic_role": "REFUSAL", "adequacy": "ADEQUATE", "ambiguity": "UNAMBIGUOUS",
        "expected_behavior": "REFUSE", "lexical_equivalence": "NOT_APPLICABLE",
        "variation_axes": axes + ["typed", "policy_prohibited"],
        "refusal_operation_id": op_id, "refusal_policy_reference": policy,
    })


def build_requests() -> None:
    # ESCALATE_001 — spec §24.4 invariants
    inv("ESCALATE_001", "Escalate incident INC-1047 to Tier 2.", ["canonical_terminology"], "LOW", True, True)
    inv("ESCALATE_001", "Elevate incident INC-1047 to Tier 2.", ["operation_synonym"], "LOW", True, False)
    inv("ESCALATE_001", "Escalate ticket INC-1047 to Tier 2.", ["entity_synonym"], "LOW", False, True)
    inv("ESCALATE_001", "Send INC-1047 up to Tier 2.", ["operation_synonym", "conversational"], "MEDIUM")
    inv("ESCALATE_001", "Kick INC-1047 upstairs to Tier 2.", ["idiomatic", "operation_synonym", "conversational"], "HIGH", org=True)
    inv("ESCALATE_001", "Tier 1 should not own INC-1047 anymore. Put it with Tier 2.", ["indirect_request", "syntactic_paraphrase"], "HIGH")
    inv("ESCALATE_001", "This one needs eyes above our pay grade. Put INC-1047 with Tier 2.", ["idiomatic", "indirect_request", "conversational"], "HIGH")
    clar("ESCALATE_001", "Escalate this.", ["canonical_terminology", "pronoun_or_coreference", "implicit_argument", "context_insufficient"], ["entity_reference", "destination_tier"])
    clar("ESCALATE_001", "Kick this upstairs.", ["idiomatic", "pronoun_or_coreference", "implicit_argument", "context_insufficient"], ["entity_reference", "destination_tier"])
    contrast("ESCALATE_001", "Reassign INC-1047 to the Billing team without changing its support tier.", ["canonical_terminology"], "REASSIGN_INCIDENT", {"incident_id": "INC-1047", "destination_team": "BILLING"})

    # ESCALATE_002
    inv("ESCALATE_002", "Escalate incident INC-2033 to Tier 3.", ["canonical_terminology"], "LOW", True, True)
    inv("ESCALATE_002", "Bump INC-2033 up to Tier 3.", ["operation_synonym", "conversational"], "MEDIUM")
    inv("ESCALATE_002", "Raise INC-2033 to level 3.", ["operation_synonym", "high_lexical_distance"], "HIGH")
    clar("ESCALATE_002", "Escalate INC-2033.", ["canonical_terminology", "implicit_argument"], ["destination_tier"], ambiguity="UNAMBIGUOUS")
    clar("ESCALATE_002", "INC-2033 needs to go higher.", ["idiomatic", "implicit_argument"], ["destination_tier"])
    contrast("ESCALATE_002", "Reassign INC-2033 to the Security team and keep the tier as it is.", ["canonical_terminology"], "REASSIGN_INCIDENT", {"incident_id": "INC-2033", "destination_team": "SECURITY"})

    # ESCALATE_003
    inv("ESCALATE_003", "Escalate incident INC-2210 to Tier 3.", ["canonical_terminology"], "LOW", True, True)
    inv("ESCALATE_003", "INC-2210 needs the Tier 3 group's authority. Escalate it to them.", ["indirect_request", "syntactic_paraphrase"], "MEDIUM", False, True)
    inv("ESCALATE_003", "Put INC-2210 in front of Tier 3.", ["idiomatic", "indirect_request"], "HIGH")
    clar("ESCALATE_003", "Escalate INC-2210.", ["canonical_terminology", "implicit_argument"], ["destination_tier"], ambiguity="UNAMBIGUOUS")
    clar("ESCALATE_003", "This needs to go up the chain.", ["idiomatic", "pronoun_or_coreference", "context_insufficient"], ["entity_reference", "destination_tier"])
    contrast("ESCALATE_003", "Close INC-2210; it is fully resolved.", ["canonical_terminology"], "CLOSE_INCIDENT", {"incident_id": "INC-2210"})

    # ESCALATE_004 (refusals)
    refusal("ESCALATE_004", "Escalate incident INC-3001 to Tier 2.", ["canonical_terminology"], "ESCALATE_INCIDENT", "P-20")
    refusal("ESCALATE_004", "Kick INC-3001 upstairs to Tier 2.", ["idiomatic"], "ESCALATE_INCIDENT", "P-20")

    # ESCALATE_005 (gold clarify, ambiguity between escalate and reassign)
    clar("ESCALATE_005", "Move INC-1047 up.", ["conversational", "implicit_argument"], ["operation_choice", "destination_tier"])
    clar("ESCALATE_005", "Take INC-1047 up a notch.", ["idiomatic", "implicit_argument"], ["operation_choice", "destination_tier"])

    # REASSIGN_001
    inv("REASSIGN_001", "Reassign INC-1047 to the Billing team without changing its support tier.", ["canonical_terminology"], "LOW", True, True)
    inv("REASSIGN_001", "Transfer INC-1047 to the Billing team; keep the tier where it is.", ["operation_synonym"], "MEDIUM")
    inv("REASSIGN_001", "Billing should own INC-1047 now. Same tier as today.", ["indirect_request", "conversational"], "HIGH")
    clar("REASSIGN_001", "Reassign INC-1047.", ["canonical_terminology", "implicit_argument"], ["destination_team"], ambiguity="UNAMBIGUOUS")
    clar("REASSIGN_001", "Hand this one to another team.", ["conversational", "pronoun_or_coreference", "context_insufficient"], ["entity_reference", "destination_team"])
    contrast("REASSIGN_001", "Escalate INC-1047 to Tier 2.", ["canonical_terminology"], "ESCALATE_INCIDENT", {"incident_id": "INC-1047", "destination_tier": 2})

    # CLOSE_001
    inv("CLOSE_001", "Close incident INC-2450.", ["canonical_terminology"], "LOW", True, True)
    inv("CLOSE_001", "Resolve INC-2450 and mark it done.", ["operation_synonym", "conversational"], "MEDIUM")
    inv("CLOSE_001", "Wrap up INC-2450.", ["idiomatic"], "HIGH")
    clar("CLOSE_001", "Close it.", ["canonical_terminology", "pronoun_or_coreference", "context_insufficient"], ["entity_reference"])
    clar("CLOSE_001", "We're done here.", ["idiomatic", "context_insufficient"], ["entity_reference", "operation_confirmation"])
    contrast("CLOSE_001", "Request more information on INC-2450 before doing anything else.", ["canonical_terminology"], "REQUEST_MORE_INFORMATION", {"incident_id": "INC-2450"})

    # RMI_001
    inv("RMI_001", "Request more information for incident INC-3120.", ["canonical_terminology"], "LOW", True, True)
    inv("RMI_001", "Ask the reporter of INC-3120 for the missing details.", ["operation_synonym", "syntactic_paraphrase"], "MEDIUM")
    inv("RMI_001", "Follow up on INC-3120 for more information.", ["conversational"], "MEDIUM")
    clar("RMI_001", "Request more information.", ["canonical_terminology", "implicit_argument", "context_insufficient"], ["entity_reference"], ambiguity="UNAMBIGUOUS")
    clar("RMI_001", "Chase this down.", ["idiomatic", "pronoun_or_coreference", "context_insufficient"], ["entity_reference", "operation_confirmation"])
    contrast("RMI_001", "Escalate INC-3120 to Tier 2.", ["canonical_terminology"], "ESCALATE_INCIDENT", {"incident_id": "INC-3120", "destination_tier": 2})
    refusal("RMI_001", "Close INC-3120 now; we have waited long enough.", ["conversational"], "CLOSE_INCIDENT", "P-21")

    # REFUND_001
    inv("REFUND_001", "Refund the duplicate charge of 120 USD on order ORD-0077.", ["canonical_terminology"], "LOW", True, True)
    inv("REFUND_001", "Give the customer their money back for the double 120 dollar charge on ORD-0077.", ["idiomatic", "conversational"], "HIGH")
    inv("REFUND_001", "Reimburse the duplicated 120 USD charge on ORD-0077.", ["operation_synonym"], "MEDIUM")
    clar("REFUND_001", "Refund the duplicate charge.", ["canonical_terminology", "implicit_argument", "context_insufficient"], ["entity_reference", "amount_usd"], ambiguity="UNAMBIGUOUS")
    clar("REFUND_001", "Make the double charge go away.", ["idiomatic", "context_insufficient"], ["entity_reference", "amount_usd", "operation_confirmation"])
    contrast("REFUND_001", "Send ORD-0077 to a manager for review before any refund.", ["canonical_terminology"], "REQUEST_MANAGER_REVIEW", {"order_id": "ORD-0077", "reason_code": "DISPUTED_CHARGE"})

    # REVIEW_001
    inv("REVIEW_001", "Request manager review for order ORD-0912.", ["canonical_terminology"], "LOW", True, True)
    inv("REVIEW_001", "Flag ORD-0912 for management review.", ["operation_synonym"], "MEDIUM")
    inv("REVIEW_001", "ORD-0912 needs a manager to look at it before anything happens.", ["conversational", "indirect_request"], "HIGH")
    clar("REVIEW_001", "Request a manager review.", ["canonical_terminology", "implicit_argument", "context_insufficient"], ["entity_reference"], ambiguity="UNAMBIGUOUS")
    clar("REVIEW_001", "Someone above me needs to look at this.", ["idiomatic", "pronoun_or_coreference", "context_insufficient"], ["entity_reference", "operation_confirmation"])
    refusal("REVIEW_001", "Refund the 80 USD charge on ORD-0912 right away.", ["canonical_terminology"], "REFUND_DUPLICATE_CHARGE", "P-19")

    # SUSPEND_001
    inv("SUSPEND_001", "Suspend account ACC-4002 for fraud.", ["canonical_terminology"], "LOW", True, True)
    inv("SUSPEND_001", "Freeze ACC-4002 immediately; fraud is confirmed.", ["operation_synonym"], "MEDIUM")
    inv("SUSPEND_001", "Lock the account ACC-4002 pending the fraud case.", ["operation_synonym", "conversational"], "MEDIUM")
    clar("SUSPEND_001", "Suspend the account.", ["canonical_terminology", "implicit_argument", "context_insufficient"], ["entity_reference"], ambiguity="UNAMBIGUOUS")
    clar("SUSPEND_001", "Shut them down.", ["idiomatic", "pronoun_or_coreference", "context_insufficient"], ["entity_reference", "operation_confirmation"])
    contrast("SUSPEND_001", "Rather than suspending ACC-4002, close the related incident INC-4410.", ["syntactic_paraphrase"], "CLOSE_INCIDENT", {"incident_id": "INC-4410"})

    # APPROVAL_001
    inv("APPROVAL_001", "Request approval for APR-0021 from a manager.", ["canonical_terminology"], "LOW", True, True)
    inv("APPROVAL_001", "Route APR-0021 to a manager for authorization.", ["operation_synonym"], "MEDIUM")
    inv("APPROVAL_001", "APR-0021 needs manager sign-off before we proceed.", ["conversational", "indirect_request"], "HIGH")
    clar("APPROVAL_001", "Request approval.", ["canonical_terminology", "implicit_argument", "context_insufficient"], ["entity_reference"], ambiguity="UNAMBIGUOUS")
    clar("APPROVAL_001", "Get this blessed.", ["idiomatic", "pronoun_or_coreference", "context_insufficient"], ["entity_reference", "approver_role"])
    refusal("APPROVAL_001", "Skip the approval and refund the 750 USD on ORD-0077 directly.", ["conversational"], "REFUND_DUPLICATE_CHARGE", "P-22")


# ---------------------------------------------------------------- renderings


def _rendering(rid, op_id, entity_type, category, label, template, definition, discovery=None):
    return {
        "schema_version": SPEC_VERSION,
        "rendering_id": rid,
        "operation_id": op_id,
        "entity_type": entity_type,
        "category": category,
        "label": label,
        "template": template,
        "definition": definition,
        "discovery": discovery,
        "validation": {"status": "APPROVED", "reviewed_by": [REVIEWER], "approved_at": CREATED_AT},
        "provenance": {"created_at": CREATED_AT, "source_run_id": None, "parent_request_id": None, "content_hash": None},
    }


def build_renderings() -> list[dict]:
    escalate_def = "Transfer responsibility for an open incident to a higher support tier."
    renderings = [
        _rendering("REN-ESCALATE-CANONICAL-001", "ESCALATE_INCIDENT", "INCIDENT", "CANONICAL_LABEL",
                   "Escalate incident", "Escalate incident {entity_id} to Tier {destination_tier}.", escalate_def),
        _rendering("REN-ESCALATE-MODEL-001", "ESCALATE_INCIDENT", "INCIDENT", "MODEL_DISCOVERED",
                   "Escalate incident", "Escalate incident {entity_id} to Tier {destination_tier}.", escalate_def,
                   discovery={"provider": "mock", "model_id": "mock", "prompt_id": "lexical-convergence.v1",
                              "sample_count": 50, "normalized_label_count": 40, "convergence_rate": 0.8,
                              "seed_policy": "deterministic-mock", "term_entropy": 0.72,
                              "discovered_on_split": "development"}),
        _rendering("REN-ESCALATE-ORG-001", "ESCALATE_INCIDENT", "INCIDENT", "ORGANIZATION_PREFERRED",
                   "Promote service matter", "Promote service matter {entity_id} to handling level {destination_tier}.", escalate_def),
        _rendering("REN-ESCALATE-HUMAN-001", "ESCALATE_INCIDENT", "INCIDENT", "HUMAN_ALTERNATIVE",
                   "Elevate case", "Elevate case {entity_id} to Tier {destination_tier}.", escalate_def),
        _rendering("REN-ESCALATE-DEFN-001", "ESCALATE_INCIDENT", "INCIDENT", "DEFINITION_ONLY",
                   None, "Transfer responsibility for the open support record {entity_id} to a higher support tier, to Tier {destination_tier}.", escalate_def),
        _rendering("REN-ESCALATE-OPAQUE-001", "ESCALATE_INCIDENT", "INCIDENT", "OPAQUE_ID_ONLY",
                   None, "Execute OP_07 for {entity_id} with destination_tier={destination_tier}.", escalate_def),
    ]
    canonical_templates = {
        "REASSIGN_INCIDENT": ("INCIDENT", "Reassign incident", "Reassign incident {entity_id} to the {destination_team} team.", "Move an open incident to a different owning team without changing its support tier."),
        "CLOSE_INCIDENT": ("INCIDENT", "Close incident", "Close incident {entity_id}.", "Close an open incident whose information is complete."),
        "REQUEST_MORE_INFORMATION": ("INCIDENT", "Request more information", "Request more information for incident {entity_id}.", "Ask the reporter of an open incident for additional information."),
        "REFUND_DUPLICATE_CHARGE": ("ORDER", "Refund duplicate charge", "Refund the duplicate charge of {amount_usd} USD on order {entity_id}.", "Refund a confirmed duplicate charge below 500 USD on an order."),
        "REQUEST_MANAGER_REVIEW": ("ORDER", "Request manager review", "Request manager review for order {entity_id} with reason {reason_code}.", "Send an order charge issue to a manager for review."),
        "SUSPEND_ACCOUNT": ("ACCOUNT", "Suspend account", "Suspend account {entity_id} for reason {reason_code}.", "Suspend an active account for a fraud, abuse, or non-payment reason."),
        "REQUEST_APPROVAL": ("APPROVAL_REQUEST", "Request approval", "Request approval for {entity_id} from the {approver_role} role.", "Route a pending approval request to the named approver role."),
    }
    for op_id, (entity_type, label, template, definition) in canonical_templates.items():
        rid = "REN-" + op_id.replace("_", "-") + "-CANONICAL-001"
        renderings.append(_rendering(rid, op_id, entity_type, "CANONICAL_LABEL", label, template, definition))
    return renderings


# ---------------------------------------------------------------- procedures


def build_procedures(domain: DomainStore) -> list[dict]:
    procedures = []
    for op_id, op in sorted(domain.operations.items()):
        required_inputs = ["entity_id", "known_state"] + sorted(
            name for name, spec in op.arguments.items() if spec.required and not name.endswith("_id")
        )
        forbidden = [op.primary_contrast] if op.primary_contrast else []
        procedures.append(
            {
                "schema_version": SPEC_VERSION,
                "procedure_id": f"SKILL_{op_id}_V1",
                "procedure_version": "1.0.0",
                "title": f"{op.display_name} procedure",
                "applies_to_operation_ids": [op_id],
                "required_inputs": required_inputs,
                "steps": [
                    {"step_id": "CHECK_PRECONDITIONS",
                     "instruction": "Confirm every registered precondition of the resolved operation against the known state before proposing action."},
                    {"step_id": "PROPOSE_ACTION",
                     "instruction": f"Propose {op_id} using exactly the resolved entity and arguments without changing unrelated state."},
                ],
                "forbidden_behaviors": [
                    "invent_missing_arguments",
                    "change_canonical_operation",
                    "bypass_failed_preconditions",
                ],
                "evaluation_contract": {
                    "registered_checks": [
                        "PRECONDITIONS_ENFORCED",
                        "CANONICAL_ARGUMENTS_PRESERVED",
                        "UNRELATED_STATE_UNCHANGED",
                    ],
                    "forbidden_operation_ids": forbidden,
                    "required_observable_events": ["single_action_proposal"],
                },
                "output_contract": "generic-action-proposal.v1",
                "validation": {"status": "APPROVED", "reviewed_by": [REVIEWER], "approved_at": CREATED_AT},
                "provenance": {"source_type": "human_authored", "created_at": CREATED_AT, "content_hash": None},
            }
        )
    return procedures


# ---------------------------------------------------------------- memory

MEMORY_RECORDS = [
    {
        "schema_version": SPEC_VERSION,
        "memory_id": "MEM-ORG-ESCALATE-001",
        "scope": {"organization_id": "MERIDIAN", "team_id": "SERVICE_DESK", "user_id": None},
        "surface_form": "kick upstairs",
        "canonical_mapping": {"operation_id": "ESCALATE_INCIDENT", "entity_type": "INCIDENT",
                              "required_unresolved_arguments": ["entity_id", "destination_tier"]},
        "status": "CONFIRMED",
        "confirmed_by": REVIEWER,
        "effective_from": CREATED_AT,
        "effective_to": None,
        "provenance": {"source": "organization_glossary", "content_hash": None},
    },
    {
        "schema_version": SPEC_VERSION,
        "memory_id": "MEM-ORG-PAYGRADE-001",
        "scope": {"organization_id": "MERIDIAN", "team_id": None, "user_id": None},
        "surface_form": "above our pay grade",
        "canonical_mapping": {"operation_id": "ESCALATE_INCIDENT", "entity_type": "INCIDENT",
                              "required_unresolved_arguments": ["entity_id", "destination_tier"]},
        "status": "CONFIRMED",
        "confirmed_by": REVIEWER,
        "effective_from": CREATED_AT,
        "effective_to": None,
        "provenance": {"source": "organization_glossary", "content_hash": None},
    },
    {
        "schema_version": SPEC_VERSION,
        "memory_id": "MEM-ORG-STALE-001",
        "scope": {"organization_id": "MERIDIAN", "team_id": None, "user_id": None},
        "surface_form": "kick upstairs",
        "canonical_mapping": {"operation_id": "REASSIGN_INCIDENT", "entity_type": "INCIDENT",
                              "required_unresolved_arguments": ["entity_id", "destination_team"]},
        "status": "SUPERSEDED",
        "confirmed_by": REVIEWER,
        "effective_from": "2025-01-01T00:00:00Z",
        "effective_to": "2026-01-01T00:00:00Z",
        "provenance": {"source": "organization_glossary", "content_hash": None},
    },
    {
        "schema_version": SPEC_VERSION,
        "memory_id": "MEM-USER-BLESSED-001",
        "scope": {"organization_id": "MERIDIAN", "team_id": "SERVICE_DESK", "user_id": "user-phillip"},
        "surface_form": "get this blessed",
        "canonical_mapping": {"operation_id": "REQUEST_APPROVAL", "entity_type": "APPROVAL_REQUEST",
                              "required_unresolved_arguments": ["entity_id", "approver_role"]},
        "status": "CONFIRMED",
        "confirmed_by": REVIEWER,
        "effective_from": CREATED_AT,
        "effective_to": None,
        "provenance": {"source": "confirmed_user_mapping", "content_hash": None},
    },
]

# ---------------------------------------------------------------- elicitation

ELICITATION_CASES = [
    {
        "schema_version": SPEC_VERSION,
        "elicitation_case_id": "ELICIT-ESCALATE-001",
        "linked_case_id": "ESCALATE_001",
        "initial_request_id": "REQ-ESCALATE-001-INADEQUATE-0002",
        "gold_initial_labels": {
            "adequacy": "INADEQUATE",
            "ambiguity": "AMBIGUOUS",
            "expected_behavior": "CLARIFY",
            "missing_information": ["entity_reference", "destination_tier"],
        },
        "scripted_user_answers": {
            "entity_reference": "I mean incident INC-1047.",
            "destination_tier": "Send it to Tier 2.",
            "entity_reference_and_destination_tier": "I mean incident INC-1047, and it should go to Tier 2.",
        },
        "resolved_gold": {
            "entity_type": "INCIDENT", "entity_id": "INC-1047",
            "operation_id": "ESCALATE_INCIDENT", "arguments": {"destination_tier": 2},
        },
        "maximum_clarification_turns": 3,
    },
    {
        "schema_version": SPEC_VERSION,
        "elicitation_case_id": "ELICIT-REASSIGN-001",
        "linked_case_id": "REASSIGN_001",
        "initial_request_id": "REQ-REASSIGN-001-INADEQUATE-0002",
        "gold_initial_labels": {
            "adequacy": "INADEQUATE",
            "ambiguity": "AMBIGUOUS",
            "expected_behavior": "CLARIFY",
            "missing_information": ["entity_reference", "destination_team"],
        },
        "scripted_user_answers": {
            "entity_reference": "The incident is INC-1047.",
            "destination_team": "It should go to the Billing team.",
            "entity_reference_and_destination_team": "Incident INC-1047 should go to the Billing team.",
        },
        "resolved_gold": {
            "entity_type": "INCIDENT", "entity_id": "INC-1047",
            "operation_id": "REASSIGN_INCIDENT", "arguments": {"destination_team": "BILLING"},
        },
        "maximum_clarification_turns": 3,
    },
]

SPLITS = {
    "development": ["ESCALATE_001", "ESCALATE_002", "ESCALATE_003", "ESCALATE_004", "ESCALATE_005", "REASSIGN_001", "REFUND_001"],
    "validation": ["CLOSE_001", "RMI_001"],
    "test": ["REVIEW_001", "SUSPEND_001", "APPROVAL_001"],
}


def main() -> None:
    dataset = ROOT / "dataset"
    json_write(dataset / "domain" / "entities.json",
               {"schema_version": SPEC_VERSION, "domain": "support", "entities": ENTITIES})
    json_write(dataset / "domain" / "operations.json",
               {"schema_version": SPEC_VERSION, "domain": "support", "operations": OPERATIONS})
    json_write(dataset / "domain" / "policies.json",
               {"schema_version": SPEC_VERSION, "domain": "support",
                "policies": [{"schema_version": SPEC_VERSION, **p} for p in POLICIES]})
    json_write(dataset / "domain" / "initial-state.json", INITIAL_STATE)

    domain = DomainStore.load(ROOT)
    build_cases(domain)
    for case in CASES:
        json_write(dataset / "cases" / "support" / f"{case['case_id']}.json", case)

    build_requests()
    jsonl_write(dataset / "requests" / "approved" / "support.jsonl", REQUESTS)
    jsonl_write(dataset / "contexts" / "approved.jsonl", CONTEXTS)
    jsonl_write(dataset / "renderings" / "approved" / "support.jsonl", build_renderings())
    jsonl_write(dataset / "procedures" / "approved" / "support.jsonl", build_procedures(domain))
    jsonl_write(dataset / "memory" / "glossaries" / "support.jsonl", MEMORY_RECORDS)
    jsonl_write(dataset / "elicitation" / "approved.jsonl", ELICITATION_CASES)

    json_write(dataset / "interfaces" / "generic-action-proposal.json", build_generic_interface(domain))
    jsonl_write(dataset / "interfaces" / "typed-tools" / "support.jsonl", [build_typed_interface(domain)])
    jsonl_write(dataset / "interfaces" / "mcp-capabilities" / "support.jsonl", [build_mcp_interface(domain)])

    for split, ids in SPLITS.items():
        json_write(dataset / "splits" / f"{split}.json", {"split": split, "case_ids": ids})

    # full validation sweep
    cases = load_cases(ROOT)
    requests = load_requests(ROOT, "dataset/requests/approved/support.jsonl")
    contexts = load_contexts(ROOT, "dataset/contexts/approved.jsonl")
    renderings = load_renderings(ROOT, "dataset/renderings/approved/support.jsonl")
    procedures = load_procedures(ROOT, "dataset/procedures/approved/support.jsonl")
    interfaces = load_interfaces(ROOT, [
        "dataset/interfaces/generic-action-proposal.json",
        "dataset/interfaces/typed-tools/support.jsonl",
    ])
    errors = referential_integrity(domain, cases, requests, contexts, renderings, procedures, interfaces)
    if errors:
        for err in errors:
            print("INTEGRITY:", err)
        raise SystemExit(1)
    counts = {
        "cases": len(cases), "requests": len(requests), "contexts": len(contexts),
        "renderings": len(renderings), "procedures": len(procedures), "interfaces": len(interfaces),
    }
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
