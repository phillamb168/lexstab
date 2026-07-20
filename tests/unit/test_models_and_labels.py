"""Unit tests: Pydantic label-consistency rules (spec §13.5, §49.2)."""

import pytest
from pydantic import ValidationError

from lexstab import models


def _request(labels_overrides=None, validation_overrides=None, provenance_overrides=None):
    labels = {
        "semantic_role": "INVARIANT",
        "adequacy": "ADEQUATE",
        "ambiguity": "UNAMBIGUOUS",
        "expected_behavior": "EXECUTE",
        "lexical_equivalence": "INVARIANT",
        "variation_axes": ["idiomatic"],
        **(labels_overrides or {}),
    }
    validation = {
        "status": "CANDIDATE",
        "reviewers": [],
        **(validation_overrides or {}),
    }
    provenance = {"created_at": "2026-07-20T00:00:00Z", **(provenance_overrides or {})}
    return {
        "schema_version": "1.2.0",
        "request_id": "REQ-TEST-0001",
        "case_id": "ESCALATE_001",
        "text": "Escalate incident INC-1047 to Tier 2.",
        "source": {"type": "human", "creator": "tester"},
        "labels": labels,
        "validation": validation,
        "provenance": provenance,
    }


def test_valid_request_passes():
    models.NLRequest.model_validate(_request())


def test_ambiguous_cannot_expect_execute():
    with pytest.raises(ValidationError, match="AMBIGUOUS"):
        models.NLRequest.model_validate(_request({
            "ambiguity": "AMBIGUOUS",
        }))


def test_inadequate_requires_missing_info_and_context():
    with pytest.raises(ValidationError, match="missing_information|contradiction"):
        models.NLRequest.model_validate(_request({
            "semantic_role": "CLARIFICATION", "adequacy": "INADEQUATE",
            "ambiguity": "AMBIGUOUS", "expected_behavior": "CLARIFY",
            "lexical_equivalence": "NOT_APPLICABLE",
        }))
    with pytest.raises(ValidationError, match="context"):
        models.NLRequest.model_validate(_request({
            "semantic_role": "CLARIFICATION", "adequacy": "INADEQUATE",
            "ambiguity": "AMBIGUOUS", "expected_behavior": "CLARIFY",
            "lexical_equivalence": "NOT_APPLICABLE",
            "missing_information": ["entity_reference"],
        }))


def test_refusal_requires_policy_reference():
    with pytest.raises(ValidationError, match="REFUSAL"):
        models.NLRequest.model_validate(_request({
            "semantic_role": "REFUSAL", "expected_behavior": "REFUSE",
            "lexical_equivalence": "NOT_APPLICABLE",
        }))


def test_contrast_requires_gold_contrast_operation():
    with pytest.raises(ValidationError, match="CONTRAST"):
        models.NLRequest.model_validate(_request({
            "semantic_role": "CONTRAST", "lexical_equivalence": "CONTRAST",
        }))


def test_approved_requires_reviewer():
    with pytest.raises(ValidationError, match="reviewer"):
        models.NLRequest.model_validate(_request(validation_overrides={"status": "APPROVED"}))


def test_frozen_requires_content_hash():
    with pytest.raises(ValidationError, match="content hash"):
        models.NLRequest.model_validate(_request(
            validation_overrides={
                "status": "FROZEN",
                "reviewers": [{"reviewer_id": "r1", "decision": "APPROVE"}],
            },
        ))


def test_unknown_variation_axis_rejected():
    with pytest.raises(ValidationError, match="variation axis"):
        models.NLRequest.model_validate(_request({"variation_axes": ["not_an_axis"]}))


def test_primary_h1_predicate():
    request = models.NLRequest.model_validate(_request())
    assert request.is_primary_h1()
    contrast = models.NLRequest.model_validate(_request({
        "semantic_role": "CONTRAST", "lexical_equivalence": "CONTRAST",
        "contrast_operation_id": "REASSIGN_INCIDENT",
    }))
    assert not contrast.is_primary_h1()


def test_gold_act_requires_tool_and_state():
    with pytest.raises(ValidationError):
        models.GoldSpec.model_validate({"decision": "ACT"})


def test_action_proposal_act_requires_operation():
    with pytest.raises(ValidationError):
        models.ActionProposal.model_validate({"decision": "ACT"})
    models.ActionProposal.model_validate(
        {"decision": "ACT", "operation_id": "ESCALATE_INCIDENT",
         "arguments": {"incident_id": "INC-1047", "destination_tier": 2}}
    )


def test_ledger_rejects_unknown_representation():
    with pytest.raises(ValidationError):
        models.RepresentationLedgerRecord.model_validate({
            "run_id": "r", "cell_id": "c", "stage_id": "s", "stage_index": 0,
            "authoritative_representation": "TELEPATHY",
            "canonical_ids_present": False, "procedure_id_present": False,
            "typed_schema_present": False,
            "input_content_hash": "sha256:aa", "output_content_hash": "sha256:bb",
        })
