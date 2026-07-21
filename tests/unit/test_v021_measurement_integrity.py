"""Focused v0.2.1 measurement-integrity checks."""

from pathlib import Path
from types import SimpleNamespace

from lexstab.artifacts import DomainStore, find_repo_root, load_cases
from lexstab.evaluators.deterministic import _first_divergences, _score_arguments
from lexstab.promptsize import build_prompt_size_report
from lexstab.simulators.support_domain import SupportSimulator


ROOT = find_repo_root(Path(__file__))


def test_v021_argument_preservation_modes_are_explicit():
    domain = DomainStore.load(ROOT, "dataset/domain/v0.2.1")
    rmi = domain.operations["REQUEST_MORE_INFORMATION"]
    assert rmi.arguments["message"].preservation.value == "VERBATIM"
    assert rmi.arguments["incident_id"].preservation.value == "CANONICAL"
    assert all(
        spec.preservation.value == "CANONICAL"
        for operation_id, operation in domain.operations.items()
        for name, spec in operation.arguments.items()
        if (operation_id, name) != ("REQUEST_MORE_INFORMATION", "message")
    )


def test_verbatim_argument_scoring_does_not_normalize_rewrites():
    domain = DomainStore.load(ROOT, "dataset/domain/v0.2.1")
    operation = domain.operations["REQUEST_MORE_INFORMATION"]
    gold = {
        "incident_id": "INC-3120",
        "message": "Please attach the missing application logs.",
    }
    actual = {
        "incident_id": "inc-3120",
        "message": "Please attach your missing application logs.",
    }
    _raw, _raw_all, normalized, all_correct, preservation = _score_arguments(
        gold, actual, set(gold), operation.arguments
    )
    assert normalized["incident_id"] is True
    assert normalized["message"] is False
    assert all_correct is False
    assert preservation["message"] == {
        "mode": "VERBATIM", "correct": False, "raw_exact": False,
    }


def test_first_verbatim_divergence_is_earliest_changed_handoff():
    domain = DomainStore.load(ROOT, "dataset/domain/v0.2.1")
    cases = load_cases(ROOT, "dataset/cases/support-v0.2.1")
    case = cases["RMI_001"]
    message = case.canonical.arguments["message"]
    bench = SimpleNamespace(domain=domain)
    result = {
        "decision": "ACT",
        "proposal": {
            "operation_id": "REQUEST_MORE_INFORMATION",
            "arguments": case.canonical.arguments,
        },
        "stage_outputs": [
            {"stage": "triage_handoff", "output": f"INC-3120: {message}"},
            {
                "stage": "policy_handoff",
                "output": "INC-3120: Please attach your missing application logs.",
            },
            {
                "stage": "planner",
                "output": {
                    "operation_id": "REQUEST_MORE_INFORMATION",
                    "arguments": case.canonical.arguments,
                },
            },
        ],
    }
    expected = {
        "behavior": "EXECUTE",
        "operation_id": "REQUEST_MORE_INFORMATION",
        "arguments": case.canonical.arguments,
        "tool": "request_more_information",
    }
    divergences = _first_divergences(bench, result, expected, case)
    assert divergences["first_operation_divergence"] is None
    assert divergences["first_argument_divergence"] == "policy_handoff"
    assert divergences["first_verbatim_argument_divergence"] == "policy_handoff"
    assert divergences["first_divergence_stage"] == "policy_handoff"


def test_replacement_close_contrast_is_executable_as_rmi_under_frozen_state():
    domain = DomainStore.load(ROOT, "dataset/domain/v0.2.1")
    case = load_cases(ROOT, "dataset/cases/support-v0.2.1")["CLOSE_001"]
    simulator = SupportSimulator(domain, case.initial_state, "2026-07-20T12:00:00Z")
    result = simulator.call_tool(
        "request_more_information",
        {
            "incident_id": "INC-2450",
            "message": "Which version of the client was installed when the incident occurred?",
        },
    )
    assert result.accepted is True
    incident = simulator.snapshot()["incidents"]["INC-2450"]
    assert incident["status"] == "PENDING_INFO"
    assert incident["last_public_comment"] == (
        "Which version of the client was installed when the incident occurred?"
    )


def test_prompt_size_report_is_provider_free_and_meets_target():
    report = build_prompt_size_report(ROOT)
    assert report["provider_calls"] == 0
    assert report["summary"]["median_target_met"] is True
    assert report["summary"]["median_delta_percent"] < 2.0
    assert report["summary"]["stages_above_warning"] == []
