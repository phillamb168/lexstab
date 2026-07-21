"""Deterministic heuristic interpreter behind the mock provider (D-009).

The mock provider exists so every workflow runs offline. It behaves like a
limited, deterministic "model": it reads only the assembled prompt (never gold
labels), interprets requests through a fixed keyword lexicon, and emits the
contract the prompt asks for. Its lexicon intentionally misses some idioms so
smoke runs produce non-degenerate score distributions. All output is labeled
mock; reports never treat mock runs as research evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

ENTITY_ID_RE = re.compile(r"\b(INC|ORD|ACC|APR|CUS)-\d{4}\b")
TIER_RE = re.compile(r"\b(?:tier|level)\s*([1-4])\b", re.IGNORECASE)
AMOUNT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:usd|dollars|\$)|\$\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
TEAM_RE = re.compile(
    r"\b(billing|payments|security|service desk|fraud|tier ?2 team)\b", re.IGNORECASE
)
QUOTED_MESSAGE_RE = re.compile(r'"([^"\n]{3,})"')

# Keyword lexicon: deliberately covers canonical wording and common synonyms,
# but NOT every idiom, so lexically distant variants can fail.
OPERATION_LEXICON: dict[str, list[str]] = {
    "ESCALATE_INCIDENT": [
        r"\bescalat\w*\b",
        r"\belevate\b",
        r"\bsend .{0,24}up\b",
        r"\bmove .{0,24}up\b",
        r"\bbump .{0,16}(?:up|to tier)\b",
        r"\bpromote\b.*\btier\b",
        r"\bkick .{0,20}upstairs\b",
    ],
    "REASSIGN_INCIDENT": [
        r"\breassign\w*\b",
        r"\bassign .{0,30}team\b",
        r"\btransfer .{0,30}team\b",
        r"\broute .{0,30}team\b",
        r"\bhand .{0,20}(?:to|over)\b.*\bteam\b",
    ],
    "CLOSE_INCIDENT": [r"\bclose\b", r"\bresolve\w*\b", r"\bwrap up\b", r"\bmark .{0,16}closed\b"],
    "REQUEST_MORE_INFORMATION": [
        r"\bmore information\b",
        r"\bmore details\b",
        r"\brequest .{0,16}info\w*\b",
        r"\bask .{0,24}for\b",
        r"\bfollow up .{0,16}information\b",
    ],
    "REFUND_DUPLICATE_CHARGE": [
        r"\brefund\w*\b",
        r"\breimburse\w*\b",
        r"\bmoney back\b",
        r"\bcharge\w{0,2}\b.*\bback\b",
    ],
    "REQUEST_MANAGER_REVIEW": [
        r"\bmanager\b.*\breview\b",
        r"\breview\b.*\bmanager\b",
        r"\bmanager sign.?off\b",
        r"\bmanagement\b.*\breview\b",
    ],
    "SUSPEND_ACCOUNT": [r"\bsuspend\w*\b", r"\bfreeze\b", r"\block\b.*\baccount\b"],
    "REQUEST_APPROVAL": [r"\bapproval\b", r"\bapprove\w*\b", r"\bauthoriz\w+\b", r"\bsign.?off\b"],
}

OPERATION_TOOLS = {
    "ESCALATE_INCIDENT": "escalate_incident",
    "REASSIGN_INCIDENT": "reassign_incident",
    "CLOSE_INCIDENT": "close_incident",
    "REQUEST_MORE_INFORMATION": "request_more_information",
    "REFUND_DUPLICATE_CHARGE": "refund_duplicate_charge",
    "REQUEST_MANAGER_REVIEW": "request_manager_review",
    "SUSPEND_ACCOUNT": "suspend_account",
    "REQUEST_APPROVAL": "request_approval",
}

ENTITY_PREFIX_FOR_OP = {
    "ESCALATE_INCIDENT": "INC",
    "REASSIGN_INCIDENT": "INC",
    "CLOSE_INCIDENT": "INC",
    "REQUEST_MORE_INFORMATION": "INC",
    "REFUND_DUPLICATE_CHARGE": "ORD",
    "REQUEST_MANAGER_REVIEW": "ORD",
    "SUSPEND_ACCOUNT": "ACC",
    "REQUEST_APPROVAL": "APR",
}

ID_ARG_FOR_OP = {
    "ESCALATE_INCIDENT": "incident_id",
    "REASSIGN_INCIDENT": "incident_id",
    "CLOSE_INCIDENT": "incident_id",
    "REQUEST_MORE_INFORMATION": "incident_id",
    "REFUND_DUPLICATE_CHARGE": "order_id",
    "REQUEST_MANAGER_REVIEW": "order_id",
    "SUSPEND_ACCOUNT": "account_id",
    "REQUEST_APPROVAL": "approval_id",
}


def stable_int(text: str, modulus: int) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulus


def prompt_text(messages: list[dict]) -> str:
    parts = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        parts.append(str(content))
    return "\n".join(parts)


def extract_section(text: str, header: str) -> str:
    """Extract the block following an ALL-CAPS section header.

    A section ends at the next ALL-CAPS header, at an instruction line
    ("Return ...", "When ...", "Do not ...", ...), or at end of prompt —
    instruction text and its JSON examples must not leak into section content.
    """
    pattern = re.compile(
        rf"^{re.escape(header)}\s*$\n"
        r"(.*?)(?=^\s*[A-Z][A-Z \-']{2,60}\s*$"
        r"|^(?:Return|When exactly|Do not|Apply|Use INADEQUATE|Follow the procedure|"
        r"If the request|If a required|If exactly|Call the one|Identify the|Select exactly|"
        r"Choose exactly|Determine whether|Ask one concise|Write a concise)\b"
        r"|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def extract_json_from_section(section: str) -> dict | None:
    match = re.search(r"\{.*\}", section, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def find_entity_ids(text: str) -> list[str]:
    seen: list[str] = []
    for match in ENTITY_ID_RE.finditer(text):
        if match.group(0) not in seen:
            seen.append(match.group(0))
    return seen


def match_operations(request_text: str) -> list[str]:
    lowered = request_text.lower()
    matched = []
    for op_id, patterns in OPERATION_LEXICON.items():
        if any(re.search(pattern, lowered) for pattern in patterns):
            matched.append(op_id)
    # Escalation phrasing often also matches reassignment when a team is named;
    # prefer the more specific interpretation deterministically.
    if "ESCALATE_INCIDENT" in matched and "REASSIGN_INCIDENT" in matched:
        if re.search(r"\bwithout changing\b.*\btier\b", lowered) or (
            TEAM_RE.search(lowered) and not TIER_RE.search(lowered)
        ):
            matched.remove("ESCALATE_INCIDENT")
        else:
            matched.remove("REASSIGN_INCIDENT")
    if "REFUND_DUPLICATE_CHARGE" in matched and "REQUEST_MANAGER_REVIEW" in matched:
        if re.search(r"\bmanager\b|\breview\b", lowered):
            matched.remove("REFUND_DUPLICATE_CHARGE")
        else:
            matched.remove("REQUEST_MANAGER_REVIEW")
    return matched


def build_arguments(op_id: str, request_text: str, context_text: str) -> tuple[dict, list[str]]:
    """Return (arguments, missing_fields) from surface text only."""
    combined = request_text + "\n" + context_text
    arguments: dict[str, Any] = {}
    missing: list[str] = []

    prefix = ENTITY_PREFIX_FOR_OP[op_id]
    ids = [eid for eid in find_entity_ids(combined) if eid.startswith(prefix)]
    if ids:
        arguments[ID_ARG_FOR_OP[op_id]] = ids[0]
    else:
        missing.append("entity_reference")

    if op_id == "ESCALATE_INCIDENT":
        tier = TIER_RE.search(request_text) or TIER_RE.search(context_text)
        if tier:
            arguments["destination_tier"] = int(tier.group(1))
        else:
            missing.append("destination_tier")
    elif op_id == "REASSIGN_INCIDENT":
        team = TEAM_RE.search(request_text)
        if team:
            arguments["destination_team"] = team.group(1).upper().replace(" ", "_")
        else:
            missing.append("destination_team")
    elif op_id == "REFUND_DUPLICATE_CHARGE":
        amount = AMOUNT_RE.search(request_text) or AMOUNT_RE.search(context_text)
        if amount:
            arguments["amount_usd"] = float(amount.group(1) or amount.group(2))
        else:
            missing.append("amount_usd")
    elif op_id == "REQUEST_MORE_INFORMATION":
        messages = QUOTED_MESSAGE_RE.findall(combined)
        if messages:
            arguments["message"] = messages[-1].strip()
        else:
            missing.append("message")
    elif op_id == "REQUEST_MANAGER_REVIEW":
        arguments["reason_code"] = "DISPUTED_CHARGE"
    elif op_id == "SUSPEND_ACCOUNT":
        arguments["reason_code"] = "FRAUD"
    elif op_id == "REQUEST_APPROVAL":
        arguments["approver_role"] = "MANAGER"
    return arguments, missing


def known_state_shows_closed(known_state: dict | None, entity_id: str | None) -> bool:
    if not known_state or not entity_id:
        return False
    incidents = known_state.get("incidents", {})
    entity = incidents.get(entity_id, {})
    return entity.get("status") == "CLOSED"


SYNONYM_ROTATION = {
    "escalate incident": ["elevate support case", "route issue upward", "transfer ticket"],
    "reassign incident": ["move case ownership", "switch handling team", "redirect ticket"],
    "close incident": ["finalize case", "complete ticket", "conclude issue"],
}


def rotate_label(current: str, forbidden: list[str]) -> str:
    pool = SYNONYM_ROTATION.get(
        current.lower(), [f"{current} (alt {index})" for index in range(1, 4)]
    )
    for candidate in pool:
        if candidate.lower() != current.lower() and candidate not in forbidden:
            return candidate
    return pool[stable_int(current, len(pool))]
