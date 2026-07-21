"""Canonical-resolution envelope and deterministic grounding policy."""

from pathlib import Path

import pytest

from lexstab import canonical, domaintext, models
from lexstab.artifacts import (
    DomainStore,
    find_repo_root,
    json_read,
    jsonl_read,
    load_elicitation_cases,
)
from lexstab.freeze import (
    FreezeError,
    FrozenBenchmark,
    _validate_real_discovered_renderings,
    active_approved_rows,
)

ROOT = find_repo_root(Path(__file__))
DOMAIN = DomainStore.load(ROOT)
CORRECTED_DOMAIN = DomainStore.load(ROOT, "dataset/domain/v0.2.0")
CORRECTED_BENCH = FrozenBenchmark(
    ROOT, ROOT / "dataset/manifests/benchmark-v0.2.0.json"
)


def _mapped(entity_type, entity_id, operation_id, arguments):
    return models.CanonicalResolution(
        mapping_outcome="MAPPED",
        canonical_intent={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "operation_id": operation_id,
            "arguments": arguments,
        },
    )


def test_strict_parser_rejects_legacy_status_shape_by_default():
    legacy = {
        "status": "RESOLVED",
        "entity_type": "INCIDENT",
        "entity_id": "INC-1047",
        "operation_id": "ESCALATE_INCIDENT",
        "arguments": {"destination_tier": 2},
    }
    parsed, error = canonical.parse_resolution(legacy)
    assert parsed is None and error
    compatible, error = canonical.parse_resolution(legacy, allow_legacy=True)
    assert error is None
    assert compatible.mapping_outcome == models.MappingOutcome.MAPPED


def test_gold_clarification_is_not_converted_to_a_mapped_intent():
    case = CORRECTED_BENCH.cases["ESCALATE_005"]
    payload = domaintext.gold_canonical_resolution(case)
    parsed = models.CanonicalResolution.model_validate(payload)
    assert parsed.mapping_outcome == models.MappingOutcome.NEEDS_CLARIFICATION
    assert parsed.canonical_intent is None
    assert parsed.question
    assert parsed.candidate_mappings[0].missing_or_ambiguous == [
        "operation_choice",
        "destination_tier",
    ]


def test_gold_refusal_keeps_mapped_intent_for_precondition_evaluation():
    case = CORRECTED_BENCH.cases["ESCALATE_004"]
    payload = domaintext.gold_canonical_resolution(case)
    parsed = models.CanonicalResolution.model_validate(payload)
    assert parsed.mapping_outcome == models.MappingOutcome.MAPPED
    assert parsed.canonical_intent.operation_id == "ESCALATE_INCIDENT"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entity_type", "SUPPORT_THING"),
        ("operation_id", "ESCALATE_INCIDENT234234"),
    ],
)
def test_canonical_resolution_rejects_unregistered_identifiers(field, value):
    payload = {
        "mapping_outcome": "NEEDS_CLARIFICATION",
        "canonical_intent": None,
        "candidate_mappings": [{
            "entity_type": "INCIDENT",
            "operation_id": "ESCALATE_INCIDENT",
            "missing_or_ambiguous": ["destination_tier"],
        }],
        "question": "Which destination tier should be used?",
        "preserved_user_terms": [],
        "uncertainties": ["destination_tier"],
        "grounding": {},
    }
    payload["candidate_mappings"][0][field] = value
    parsed, error = canonical.parse_resolution(payload)
    assert parsed is None
    assert error is not None


def test_hidden_singleton_state_cannot_originate_entity():
    proposed = _mapped(
        "ORDER", "ORD-0077", "REFUND_DUPLICATE_CHARGE", {"amount_usd": 120.0}
    )
    grounded = canonical.enforce_grounding(
        proposed,
        domain=DOMAIN,
        user_request="Refund the duplicate charge.",
        shared_context_text="(no shared context)",
        visible_state={},
        known_state={
            "orders": {
                "ORD-0077": {
                    "duplicate_charge_confirmed": True,
                    "duplicate_charge_amount_usd": 120.0,
                }
            }
        },
    )
    assert grounded.mapping_outcome == models.MappingOutcome.NEEDS_CLARIFICATION
    assert "entity_reference" in grounded.candidate_mappings[0].missing_or_ambiguous


def test_anchored_order_allows_registered_state_derived_amount():
    proposed = _mapped(
        "ORDER", "ORD-0077", "REFUND_DUPLICATE_CHARGE", {"amount_usd": 120.0}
    )
    grounded = canonical.enforce_grounding(
        proposed,
        domain=DOMAIN,
        user_request="Return the confirmed duplicate charge on ORD-0077.",
        shared_context_text="(no shared context)",
        visible_state={},
        known_state={
            "orders": {
                "ORD-0077": {
                    "duplicate_charge_confirmed": True,
                    "duplicate_charge_amount_usd": 120.0,
                }
            }
        },
    )
    assert grounded.mapping_outcome == models.MappingOutcome.MAPPED
    assert grounded.grounding["entity_id"] == "request"
    assert grounded.grounding["amount_usd"] == "known_state:state-derivation.v1"


def test_anchored_order_completes_missing_registered_state_derived_amount():
    proposed = _mapped("ORDER", "ORD-0077", "REFUND_DUPLICATE_CHARGE", {})
    grounded = canonical.enforce_grounding(
        proposed,
        domain=DOMAIN,
        user_request="Return the confirmed duplicate charge on ORD-0077.",
        shared_context_text="(no shared context)",
        visible_state={},
        known_state={
            "orders": {
                "ORD-0077": {
                    "duplicate_charge_confirmed": True,
                    "duplicate_charge_amount_usd": 120.0,
                }
            }
        },
    )
    assert grounded.mapping_outcome == models.MappingOutcome.MAPPED
    assert grounded.canonical_intent.arguments["amount_usd"] == 120.0
    assert grounded.grounding["amount_usd"] == "known_state:state-derivation.v1"


def test_context_can_anchor_entity_but_unregistered_arguments_cannot_come_from_state():
    proposed = _mapped(
        "INCIDENT", "INC-1047", "REASSIGN_INCIDENT", {"destination_team": "BILLING"}
    )
    grounded = canonical.enforce_grounding(
        proposed,
        domain=DOMAIN,
        user_request="Move it to the appropriate team.",
        shared_context_text="We are discussing INC-1047.",
        visible_state={"active_incident_id": "INC-1047"},
        known_state={"incidents": {"INC-1047": {"assigned_team": "SERVICE_DESK"}}},
    )
    assert grounded.mapping_outcome == models.MappingOutcome.NEEDS_CLARIFICATION
    assert "destination_team" in grounded.candidate_mappings[0].missing_or_ambiguous


def test_context_anchored_entity_and_explicit_argument_map_successfully():
    proposed = _mapped(
        "INCIDENT", "INC-1047", "ESCALATE_INCIDENT", {"destination_tier": 2}
    )
    grounded = canonical.enforce_grounding(
        proposed,
        domain=DOMAIN,
        user_request="Move it to Tier 2.",
        shared_context_text="We are discussing INC-1047.",
        visible_state={"active_incident_id": "INC-1047"},
        known_state={"incidents": {"INC-1047": {"support_tier": 1}}},
    )
    assert grounded.mapping_outcome == models.MappingOutcome.MAPPED
    assert grounded.grounding == {"entity_id": "shared_context", "destination_tier": "request"}


def test_request_more_information_without_explicit_message_requires_clarification():
    proposed = _mapped("INCIDENT", "INC-3120", "REQUEST_MORE_INFORMATION", {})
    grounded = canonical.enforce_grounding(
        proposed,
        domain=CORRECTED_DOMAIN,
        user_request="Request more information for incident INC-3120.",
        shared_context_text="(no shared context)",
        visible_state={},
        known_state={
            "incidents": {
                "INC-3120": {
                    "reporter_id": "USR-3120",
                    "assigned_team": "SERVICE_DESK",
                }
            }
        },
    )
    assert grounded.mapping_outcome == models.MappingOutcome.NEEDS_CLARIFICATION
    assert grounded.candidate_mappings[0].missing_or_ambiguous == ["message"]
    assert "message" in grounded.question


def test_request_more_information_maps_explicit_message_without_changing_owner():
    message = "Please attach the missing application logs."
    proposed = _mapped(
        "INCIDENT", "INC-3120", "REQUEST_MORE_INFORMATION", {"message": message}
    )
    grounded = canonical.enforce_grounding(
        proposed,
        domain=CORRECTED_DOMAIN,
        user_request=f'Request more information for INC-3120: "{message}"',
        shared_context_text="(no shared context)",
        visible_state={},
        known_state={"incidents": {"INC-3120": {"assigned_team": "SERVICE_DESK"}}},
    )
    assert grounded.mapping_outcome == models.MappingOutcome.MAPPED
    assert grounded.grounding == {"entity_id": "request", "message": "request"}


def test_superseded_ownership_request_is_excluded_and_replacements_follow_review_lifecycle():
    approved = jsonl_read(ROOT / "dataset/requests/approved/support.jsonl")
    by_id = {row["request_id"]: row for row in approved}
    active_ids = {row["request_id"] for row in active_approved_rows(approved)}
    assert "REQ-ESCALATE-001-0006" not in active_ids
    assert "REQ-ESCALATE-001-CLARIFY-OWNERSHIP-0001" not in active_ids
    assert "REQ-ESCALATE-001-0009" in active_ids

    ambiguous = by_id["REQ-ESCALATE-001-CLARIFY-OWNERSHIP-0001"]
    replacement = by_id["REQ-ESCALATE-001-0009"]
    assert ambiguous["labels"]["expected_behavior"] == "CLARIFY"
    assert ambiguous["labels"]["ambiguity"] == "AMBIGUOUS"
    assert ambiguous["validation"]["status"] == "SUPERSEDED"
    assert replacement["labels"]["lexical_equivalence"] == "INVARIANT"
    assert replacement["labels"]["expected_behavior"] == "EXECUTE"
    assert replacement["validation"]["status"] == "APPROVED"
    assert replacement["validation"]["approved_by"] == "phillip"


def test_rmi_contract_corrections_preserve_superseded_rows_after_human_review():
    approved = jsonl_read(ROOT / "dataset/requests/approved/support.jsonl")
    by_id = {row["request_id"]: row for row in approved}
    superseded_ids = {
        "REQ-CLOSE-001-CONTRAST-0001",
        "REQ-RMI-001-0001",
        "REQ-RMI-001-0002",
        "REQ-RMI-001-0003",
        "REQ-RMI-001-INADEQUATE-0001",
        "REQ-RMI-001-INADEQUATE-0002",
        "REQ-CLOSE-001-CONTRAST-0002",
    }
    assert all(by_id[request_id]["validation"]["status"] == "SUPERSEDED"
               for request_id in superseded_ids)

    replacement_ids = {
        "REQ-CLOSE-001-CONTRAST-0003",
        "REQ-RMI-001-0004",
        "REQ-RMI-001-0005",
        "REQ-RMI-001-0006",
        "REQ-RMI-001-INADEQUATE-0003",
        "REQ-RMI-001-INADEQUATE-0004",
        "REQ-RMI-001-INADEQUATE-0005",
    }
    candidates = [by_id[request_id] for request_id in replacement_ids]
    assert all(row["validation"]["status"] == "APPROVED" for row in candidates)
    assert all(row["validation"]["approved_by"] == "phillip" for row in candidates)

    executable = next(row for row in candidates if row["request_id"] == "REQ-RMI-001-0004")
    assert executable["labels"]["missing_information"] == []
    assert "Please attach the missing application logs" in executable["text"]
    clarification = next(
        row for row in candidates
        if row["request_id"] == "REQ-RMI-001-INADEQUATE-0003"
    )
    assert clarification["labels"]["missing_information"] == ["message"]
    assert clarification["labels"]["expected_behavior"] == "CLARIFY"


def test_rmi_elicitation_is_versioned_without_mutating_v010_source():
    historical = load_elicitation_cases(
        ROOT, "dataset/elicitation/approved.jsonl"
    )
    corrected = load_elicitation_cases(
        ROOT, "dataset/elicitation/approved-v0.2.0.jsonl"
    )
    assert "ELICIT-RMI-001" not in historical
    assert corrected["ELICIT-RMI-001"].initial_request_id == (
        "REQ-RMI-001-INADEQUATE-0003"
    )
    assert corrected["ELICIT-RMI-001"].gold_initial_labels["missing_information"] == [
        "message"
    ]


def _real_discovered_fixture():
    approved = jsonl_read(ROOT / "dataset/renderings/approved/support.jsonl")
    canonical = {
        row["operation_id"]: models.Rendering.model_validate(row)
        for row in approved
        if row["category"] == "CANONICAL_LABEL"
    }
    cards = json_read(
        ROOT / "dataset/renderings/discovery-cards/support.json"
    )
    renderings = {item.rendering_id: item for item in canonical.values()}
    for operation_id, reference in canonical.items():
        label_span = cards[operation_id].get(
            "reference_template_label_span", reference.label
        )
        discovered = models.Rendering.model_validate({
            "rendering_id": f"REN-{operation_id.replace('_', '-')}-DISCOVERED-TEST-001",
            "operation_id": operation_id,
            "entity_type": reference.entity_type,
            "category": "MODEL_DISCOVERED",
            "label": label_span,
            "template": reference.template,
            "definition": reference.definition,
            "discovery": {
                "provider": "anthropic",
                "model_id": "claude-opus-4-8",
                "prompt_id": "operation-lexical-convergence.v1",
                "sample_count": 50,
                "normalized_label_count": 50,
                "convergence_rate": 1.0,
                "seed_policy": "fresh-context",
                "term_entropy": 0.0,
                "reference_rendering_id": reference.rendering_id,
                "reference_template_label_span": label_span,
            },
            "validation": {
                "status": "APPROVED",
                "reviewed_by": ["test-reviewer"],
                "approved_at": "2026-07-20T00:00:00Z",
            },
            "provenance": {"created_at": "2026-07-20T00:00:00Z"},
        })
        renderings[discovered.rendering_id] = discovered
    return renderings


def test_v020_freeze_gate_requires_all_operations_and_nonmock_discovery():
    renderings = _real_discovered_fixture()
    _validate_real_discovered_renderings(DOMAIN, renderings)

    missing = dict(renderings)
    missing_id = next(
        key for key, value in missing.items()
        if value.category == models.RenderingCategory.MODEL_DISCOVERED
        and value.operation_id == "SUSPEND_ACCOUNT"
    )
    missing.pop(missing_id)
    with pytest.raises(FreezeError, match="SUSPEND_ACCOUNT.*found 0"):
        _validate_real_discovered_renderings(DOMAIN, missing)

    mocked = dict(renderings)
    mock_id = next(
        key for key, value in mocked.items()
        if value.category == models.RenderingCategory.MODEL_DISCOVERED
    )
    mocked[mock_id] = mocked[mock_id].model_copy(
        update={
            "discovery": mocked[mock_id].discovery.model_copy(
                update={"provider": "mock", "model_id": "mock"}
            )
        }
    )
    with pytest.raises(FreezeError, match="mock-derived"):
        _validate_real_discovered_renderings(DOMAIN, mocked)
