"""Unit tests: deterministic simulator (spec §11.5, §46.20)."""

from pathlib import Path

import pytest

from lexstab.artifacts import DomainStore, find_repo_root
from lexstab.simulators.support_domain import SupportSimulator, recompute_gold_state

ROOT = find_repo_root(Path(__file__))


@pytest.fixture(scope="module")
def domain():
    return DomainStore.load(ROOT)


@pytest.fixture(scope="module")
def corrected_domain():
    return DomainStore.load(ROOT, "dataset/domain/v0.2.0")


def _state():
    return {"incidents": {"INC-1047": {
        "status": "OPEN", "severity": "SEV-2", "support_tier": 1,
        "assigned_team": "SERVICE_DESK", "information_complete": True,
        "escalation_count": 0,
    }}}


def test_escalation_transition(domain):
    sim = SupportSimulator(domain, _state(), "T0")
    result = sim.call_tool("escalate_incident", {"incident_id": "INC-1047", "destination_tier": 2})
    assert result.accepted
    incident = sim.snapshot()["incidents"]["INC-1047"]
    assert incident["support_tier"] == 2
    assert incident["escalation_count"] == 1
    assert incident["updated_at"] == "T0"
    assert [event.event_type for event in sim.events] == [
        "attempted", "accepted", "state_transition",
    ]


def test_precondition_rejection_records_events(domain):
    state = _state()
    state["incidents"]["INC-1047"]["status"] = "CLOSED"
    sim = SupportSimulator(domain, state, "T0")
    result = sim.call_tool("escalate_incident", {"incident_id": "INC-1047", "destination_tier": 2})
    assert not result.accepted
    assert result.error_category == "precondition_failed"
    assert sim.snapshot() == state  # no state change on rejection


def test_downward_escalation_rejected(domain):
    state = _state()
    state["incidents"]["INC-1047"]["support_tier"] = 3
    sim = SupportSimulator(domain, state, "T0")
    result = sim.call_tool("escalate_incident", {"incident_id": "INC-1047", "destination_tier": 2})
    assert not result.accepted


def test_unknown_tool_and_entity(domain):
    sim = SupportSimulator(domain, _state(), "T0")
    assert sim.call_tool("nuke_everything", {}).error_category == "unknown_tool"
    result = sim.call_tool("escalate_incident", {"incident_id": "INC-9999", "destination_tier": 2})
    assert result.error_category == "unknown_entity"


def test_argument_validation(domain):
    sim = SupportSimulator(domain, _state(), "T0")
    assert sim.call_tool("escalate_incident", {"incident_id": "INC-1047"}).error_category == "invalid_arguments"
    assert sim.call_tool(
        "escalate_incident", {"incident_id": "INC-1047", "destination_tier": 9}
    ).error_category == "invalid_arguments"
    assert sim.call_tool(
        "escalate_incident", {"incident_id": "INC-1047", "destination_tier": 2, "extra": 1}
    ).error_category == "invalid_arguments"


def test_request_more_information_requires_message_and_preserves_ownership(corrected_domain):
    state = {
        "incidents": {
            "INC-3120": {
                "status": "OPEN",
                "severity": "SEV-2",
                "support_tier": 1,
                "assigned_team": "SERVICE_DESK",
                "information_complete": False,
                "escalation_count": 0,
                "reporter_id": "USR-3120",
                "awaiting_party": "NONE",
                "reporter_notification_sent": False,
            }
        }
    }
    sim = SupportSimulator(corrected_domain, state, "T0")
    missing = sim.call_tool("request_more_information", {"incident_id": "INC-3120"})
    assert not missing.accepted
    assert missing.error_category == "invalid_arguments"

    message = "Please attach the missing application logs."
    accepted = sim.call_tool(
        "request_more_information",
        {"incident_id": "INC-3120", "message": message},
    )
    assert accepted.accepted
    incident = sim.snapshot()["incidents"]["INC-3120"]
    assert incident["assigned_team"] == "SERVICE_DESK"
    assert incident["support_tier"] == 1
    assert incident["status"] == "PENDING_INFO"
    assert incident["awaiting_party"] == "REPORTER"
    assert incident["last_public_comment"] == message
    assert incident["reporter_notification_sent"] is True


def test_reset_restores_exact_initial_state(domain):
    sim = SupportSimulator(domain, _state(), "T0")
    sim.call_tool("escalate_incident", {"incident_id": "INC-1047", "destination_tier": 2})
    sim.reset()
    assert sim.snapshot() == _state()
    assert sim.events == []


def test_determinism(domain):
    runs = []
    for _ in range(2):
        sim = SupportSimulator(domain, _state(), "T0")
        sim.call_tool("escalate_incident", {"incident_id": "INC-1047", "destination_tier": 2})
        runs.append(sim.snapshot())
    assert runs[0] == runs[1]


def test_gold_recompute_matches_case_artifacts(domain):
    from lexstab.artifacts import load_cases
    from lexstab.models import GoldDecision

    for case in load_cases(ROOT).values():
        if case.gold.decision != GoldDecision.ACT:
            continue
        accepted, resulting, detail = recompute_gold_state(
            domain, case.initial_state, case.gold.tool, case.gold.arguments, "<run_clock>"
        )
        assert accepted, f"{case.case_id}: {detail}"
        assert resulting == case.gold.resulting_state, case.case_id


def test_corrected_gold_recompute_matches_versioned_case_artifacts(corrected_domain):
    from lexstab.artifacts import load_cases
    from lexstab.models import GoldDecision

    for case in load_cases(ROOT, "dataset/cases/support-v0.2.0").values():
        if case.gold.decision != GoldDecision.ACT:
            continue
        accepted, resulting, detail = recompute_gold_state(
            corrected_domain,
            case.initial_state,
            case.gold.tool,
            case.gold.arguments,
            "<run_clock>",
        )
        assert accepted, f"{case.case_id}: {detail}"
        assert resulting == case.gold.resulting_state, case.case_id
