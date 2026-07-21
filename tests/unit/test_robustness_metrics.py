"""Regression checks for lexical robustness aggregation."""

from lexstab.metrics.aggregate import (
    apply_interpretation_gate,
    headline_metrics,
    paired_comparison,
    robustness_metrics,
)


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


def test_consistency_handles_failed_and_successful_repetitions_together():
    successful = _score("canonical", True, canonical=True)
    failed = {
        **successful,
        "decision": None,
        "actual_operation_id": None,
        "actual_tool": None,
        "actual_arguments": {},
        "full_call_correct": False,
        "final_state_correct": False,
        "repetition": 1,
    }
    metrics = robustness_metrics([successful, failed])["A1_DIRECT_CLARIFY"]
    assert metrics["mean_variant_accuracy"] == 0.5
    assert metrics["within_case_consistency"] == 1.0


def test_headline_never_combines_gold_and_runtime_cohorts():
    base = {
        "track": "progressive_formalization",
        "architecture": "P2_CANONICAL_PROPOSAL",
        "case_id": "CASE_1",
        "request_id": "REQ_1",
        "repetition": 0,
        "schema_valid": True,
        "decision_correct": True,
        "full_call_correct": True,
        "final_state_correct": True,
        "contrast_correct": None,
        "refusal_correct": None,
        "false_action": False,
        "clarification_outcome": "TN",
        "usage": {},
    }
    rows = []
    for mode in ("gold", "runtime"):
        rows.append({
            **base,
            "cell_id": mode,
            "metadata": {
                "intent_mode": mode,
                "procedure_selection": "none",
                "procedure_packaging": "none",
                "expected_behavior": "EXECUTE",
                "primary_h1": True,
            },
        })
    headline = headline_metrics(rows, samples=20)
    assert len(headline) == 2
    assert {row["intent_mode"] for row in headline} == {"gold", "runtime"}
    assert all(row["n_cells"] == 1 for row in headline)


def test_paired_comparison_uses_exact_intent_selection_and_packaging_cohorts():
    base = {
        "track": "progressive_formalization",
        "case_id": "CASE_1",
        "request_id": "REQ_1",
        "repetition": 0,
        "final_state_correct": True,
    }
    rows = [
        {
            **base,
            "architecture": "P2_CANONICAL_PROPOSAL",
            "metadata": {
                "intent_mode": "runtime", "procedure_selection": "none",
                "procedure_packaging": "none", "primary_h1": True,
            },
        },
        {
            **base,
            "architecture": "P3_CANONICAL_PROCEDURE_PROPOSAL",
            "metadata": {
                "intent_mode": "runtime", "procedure_selection": "gold",
                "procedure_packaging": "inline", "primary_h1": True,
            },
        },
        {
            **base,
            "architecture": "P3_CANONICAL_PROCEDURE_PROPOSAL",
            "final_state_correct": False,
            "metadata": {
                "intent_mode": "gold", "procedure_selection": "runtime",
                "procedure_packaging": "packaged", "primary_h1": True,
            },
        },
    ]
    comparison = paired_comparison(
        rows,
        "P2_CANONICAL_PROPOSAL",
        "P3_CANONICAL_PROCEDURE_PROPOSAL",
        "final_state_correct",
        0.01,
        samples=20,
        intent_mode="runtime",
    )
    assert comparison["n_pairs"] == 1
    assert comparison["pairing_cohorts"][1] == {
        "architecture": "P3_CANONICAL_PROCEDURE_PROPOSAL",
        "intent_mode": "runtime",
        "procedure_selection": "gold",
        "procedure_packaging": "inline",
    }


def test_interpretation_gate_preserves_estimate_but_withholds_claim():
    comparison = {
        "n_pairs": 3,
        "delta": {"estimate": 0.2},
        "pairing_cohorts": [{
            "architecture": "P3_CANONICAL_PROCEDURE_PROPOSAL",
            "intent_mode": "runtime",
            "procedure_selection": "gold",
            "procedure_packaging": "inline",
        }],
    }
    warnings = [{
        "architecture": "P3_CANONICAL_PROCEDURE_PROPOSAL",
        "intent_mode": "runtime",
        "procedure_selection": "gold",
        "procedure_packaging": "inline",
    }]
    gated = apply_interpretation_gate(comparison, warnings)
    assert gated["delta"]["estimate"] == 0.2
    assert gated["interpretation_allowed"] is False


def test_interpretation_gate_requires_cases_then_families_for_generalization():
    comparison = {
        "n_pairs": 6,
        "n_independent_cases": 5,
        "n_operation_families": 3,
        "delta": {"estimate": 0.2},
        "pairing_cohorts": [],
    }
    too_few_cases = apply_interpretation_gate(
        comparison, [], minimum_independent_cases=6,
        minimum_operation_families=3,
    )
    assert too_few_cases["interpretation_allowed"] is False
    assert too_few_cases["interpretation_scope"] == "exploratory"
    assert too_few_cases["delta"]["estimate"] == 0.2

    enough_cases = apply_interpretation_gate(
        {**comparison, "n_independent_cases": 6, "n_operation_families": 2},
        [], minimum_independent_cases=6, minimum_operation_families=3,
    )
    assert enough_cases["interpretation_allowed"] is True
    assert enough_cases["generalization_allowed"] is False
    assert enough_cases["interpretation_scope"] == "tested_operation_families_only"

    enough_families = apply_interpretation_gate(
        {**comparison, "n_independent_cases": 6}, [],
        minimum_independent_cases=6, minimum_operation_families=3,
    )
    assert enough_families["interpretation_allowed"] is True
    assert enough_families["generalization_allowed"] is True
    assert enough_families["interpretation_scope"] == "generalizable"
