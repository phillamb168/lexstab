"""Contract tests: JSON Schemas match runtime models; artifacts validate under
both layers; frozen artifacts cannot be silently mutated (spec §49.2)."""

import json
from pathlib import Path

import jsonschema
import pytest

from lexstab import models
from lexstab.artifacts import (
    DomainStore,
    find_repo_root,
    json_read,
    jsonl_read,
    load_cases,
    load_contexts,
    load_interfaces,
    load_procedures,
    load_renderings,
    load_requests,
    referential_integrity,
    validate_artifact,
)
from lexstab.schemagen import SCHEMA_MAP, check_all

ROOT = find_repo_root(Path(__file__))


def test_committed_schemas_match_models():
    assert check_all(ROOT / "schemas") == []


def test_all_schemas_are_valid_draft_2020_12():
    for filename in SCHEMA_MAP:
        schema = json_read(ROOT / "schemas" / filename)
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_dataset_validates_under_both_layers():
    domain = DomainStore.load(ROOT)
    cases = load_cases(ROOT)
    requests = load_requests(ROOT, "dataset/requests/frozen/support-v0.1.0.jsonl")
    contexts = load_contexts(ROOT, "dataset/contexts/frozen/support-v0.1.0.jsonl")
    renderings = load_renderings(ROOT, "dataset/renderings/frozen/support-v0.1.0.jsonl")
    procedures = load_procedures(ROOT, "dataset/procedures/frozen/support-v0.1.0.jsonl")
    interfaces = load_interfaces(ROOT, [
        "dataset/interfaces/generic-action-proposal.json",
        "dataset/interfaces/typed-tools/support.jsonl",
    ])
    assert len(cases) >= 12
    assert len(requests) >= 60
    errors = referential_integrity(
        domain, cases, requests, contexts, renderings, procedures, interfaces
    )
    assert errors == []


def test_schema_rejects_unknown_operation_argument():
    obj = json_read(ROOT / "dataset" / "cases" / "support" / "ESCALATE_001.json")
    obj["canonical"]["arguments"]["nonexistent"] = 1
    from lexstab.artifacts import ArtifactError, validate_case_against_domain

    case = models.CanonicalCase.model_validate(obj)
    with pytest.raises(ArtifactError, match="not defined"):
        validate_case_against_domain(case, DomainStore.load(ROOT))


def test_schema_layer_rejects_extra_fields():
    obj = json_read(ROOT / "dataset" / "cases" / "support" / "ESCALATE_001.json")
    obj["surprise"] = True
    from lexstab.artifacts import ArtifactError

    with pytest.raises(ArtifactError, match="surprise"):
        validate_artifact(obj, models.CanonicalCase, "case.schema.json", ROOT, "test")


def test_frozen_rows_carry_verifiable_hashes():
    from lexstab.hashing import verify_content_hash

    rows = jsonl_read(ROOT / "dataset/requests/frozen/support-v0.1.0.jsonl")
    assert rows
    for row in rows:
        assert row["validation"]["status"] == "FROZEN"
        assert verify_content_hash(row)


def test_frozen_files_are_read_only():
    import os

    for relative in [
        "dataset/requests/frozen/support-v0.1.0.jsonl",
        "dataset/manifests/benchmark-v0.1.0.json",
    ]:
        assert not os.access(ROOT / relative, os.W_OK), f"{relative} should be read-only"


def test_original_text_preserved_exactly():
    rows = jsonl_read(ROOT / "dataset/requests/frozen/support-v0.1.0.jsonl")
    by_id = {row["request_id"]: row for row in rows}
    kick = next(row for row in rows if "upstairs to Tier 2" in row["text"])
    assert kick["text"] == "Kick INC-1047 upstairs to Tier 2."


def test_primary_h1_selection_rule():
    requests = load_requests(ROOT, "dataset/requests/frozen/support-v0.1.0.jsonl")
    h1 = [request for request in requests.values() if request.is_primary_h1()]
    assert h1
    for request in h1:
        labels = request.labels
        assert labels.adequacy.value == "ADEQUATE"
        assert labels.ambiguity.value == "UNAMBIGUOUS"
        assert labels.expected_behavior.value == "EXECUTE"
        assert labels.lexical_equivalence.value == "INVARIANT"
