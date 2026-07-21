"""Provider-free tests for the effective model-input identity audit."""

from lexstab.metrics.input_audit import effective_input_audit


def _score(cell_id: str, request_id: str, band: str) -> dict:
    return {
        "cell_id": cell_id,
        "case_id": "CASE_1",
        "request_id": request_id,
        "repetition": 0,
        "track": "progressive_formalization",
        "architecture": "LP1_CANONICAL_ONCE",
        "metadata": {
            "intent_mode": "gold",
            "procedure_selection": "none",
            "procedure_packaging": "none",
            "lexical_distance_band": band,
            "variation_axes": [band.lower()],
        },
    }


def _invocation(text: str) -> dict:
    return {
        "messages": [{"role": "user", "content": text}],
        "tools": None,
        "response_schema_id": "triage_result.v1",
        "tool_call_mode": "native",
        "role": "execution_primary",
        "provider": "test",
        "requested_model_id": "model-a",
        "accepted_parameters": {"max_tokens": 100},
    }


def test_audit_detects_source_variants_collapsed_before_model_call():
    scores = [
        _score("cell-1", "REQ-1", "LOW"),
        _score("cell-2", "REQ-2", "MEDIUM"),
        _score("cell-3", "REQ-3", "HIGH"),
    ]
    invocations = {
        score["cell_id"]: [_invocation("identical canonical state")]
        for score in scores
    }

    audit = effective_input_audit(scores, invocations)

    assert audit["n_collapsed_source_variant_groups"] == 1
    assert audit["n_cells_in_collapsed_source_variant_groups"] == 3
    group = audit["groups"][0]
    assert group["n_source_requests"] == 3
    assert group["n_unique_first_model_inputs"] == 1
    assert group["claim_scope"] == "does_not_test_source_lexical_variation"


def test_audit_recognizes_distinct_effective_inputs():
    scores = [
        _score("cell-1", "REQ-1", "LOW"),
        _score("cell-2", "REQ-2", "HIGH"),
    ]
    invocations = {
        "cell-1": [_invocation("canonical wording")],
        "cell-2": [_invocation("high-distance wording")],
    }

    group = effective_input_audit(scores, invocations)["groups"][0]

    assert group["classification"] == "DISTINCT_MODEL_INPUTS"
    assert group["n_unique_first_model_inputs"] == 2
    assert group["claim_scope"] == "source_lexical_variation_may_be_tested"
