"""Regression checks for lexical robustness aggregation."""

from lexstab.metrics.aggregate import robustness_metrics


def _score(request_id: str, accuracy: bool, *, canonical: bool, decision: str = "ACT") -> dict:
    return {
        "architecture": "A1_DIRECT_CLARIFY",
        "case_id": "CASE_1",
        "request_id": request_id,
        "repetition": 0,
        "decision": decision,
        "actual_operation_id": "ESCALATE_INCIDENT" if accuracy else "REASSIGN_INCIDENT",
        "actual_tool": "escalate_incident" if accuracy else "reassign_incident",
        "actual_arguments": {"incident_id": "INC-1"},
        "full_call_correct": accuracy,
        "final_state_correct": accuracy,
        "metadata": {
            "primary_h1": True,
            "is_designated_canonical": canonical,
        },
    }


def test_base_accuracy_uses_designated_canonical_request():
    rows = [
        _score("canonical", True, canonical=True),
        _score("other-low-distance", False, canonical=False),
    ]
    metrics = robustness_metrics(rows)["A1_DIRECT_CLARIFY"]
    assert metrics["base_accuracy"] == 1.0
    assert metrics["mean_variant_accuracy"] == 0.5
    assert metrics["robustness_gap"] == 0.5


def test_consistency_uses_observed_operation_not_only_decision():
    rows = [
        _score("canonical", True, canonical=True),
        _score("variant", False, canonical=False),
    ]
    metrics = robustness_metrics(rows)["A1_DIRECT_CLARIFY"]
    assert metrics["within_case_consistency"] == 0.5
    assert metrics["pairwise_variant_disagreement"] == 1.0
