"""Guarded construction of the focused RMI persistence replication corpus.

This module creates versioned source artifacts and human-review candidates. It
never creates or modifies benchmark manifests and never invokes a provider.
Interactive prompting lives in ``lexstab.cli`` so builders remain testable.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from lexstab import models
from lexstab.artifacts import (
    DomainStore,
    json_read,
    json_write,
    jsonl_read,
    jsonl_write,
    load_cases,
)
from lexstab.hashing import hash_json_artifact
from lexstab.simulators.support_domain import recompute_gold_state

RUN_CLOCK_PLACEHOLDER = "<run_clock>"
VARIANT_CATEGORIES = ("canonical", "natural", "high_lexical_distance")
VariantCategory = Literal["canonical", "natural", "high_lexical_distance"]


class ReplicationError(Exception):
    """Raised before any guarded replication artifact is committed."""


class RMISeedCard(models.StrictModel):
    case_id: str = Field(pattern=r"^RMI_REP_[0-9]{3}$")
    incident_id: str = Field(pattern=r"^INC-[0-9]{4}$")
    reporter_id: str = Field(pattern=r"^USR-[0-9]{4}$")
    title: str = Field(min_length=1)
    public_message: str = Field(min_length=12)
    assigned_team: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    support_tier: int = Field(ge=1, le=4)
    severity: Literal["SEV-1", "SEV-2", "SEV-3"]
    escalation_count: int = Field(ge=0)
    difficulty: Literal["basic", "intermediate", "advanced"]


class RMIReplicationSeed(models.StrictModel):
    schema_version: str = models.SCHEMA_VERSION
    replication_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]+$")
    benchmark_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    base_benchmark_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    created_at: str
    cases: list[RMISeedCard] = Field(min_length=6)

    @model_validator(mode="after")
    def _unique_cards(self) -> "RMIReplicationSeed":
        for field_name in ("case_id", "incident_id", "reporter_id", "public_message"):
            values = [getattr(card, field_name) for card in self.cases]
            if len(values) != len(set(values)):
                raise ValueError(f"replication seed has duplicate {field_name}")
        if self.benchmark_version == self.base_benchmark_version:
            raise ValueError("replication version must differ from base version")
        return self


def load_rmi_replication_seed(path: Path) -> RMIReplicationSeed:
    return RMIReplicationSeed.model_validate(json_read(path))


def _version_paths(root: Path, version: str) -> dict[str, Path]:
    return {
        "domain": root / "dataset" / "domain" / f"v{version}",
        "cases": root / "dataset" / "cases" / f"support-v{version}",
        "interfaces": root / "dataset" / "interfaces" / f"v{version}",
        "splits": root / "dataset" / "splits" / f"v{version}",
        "elicitation": root / "dataset" / "elicitation" / f"approved-v{version}.jsonl",
        "changelog": root / "dataset" / "manifests" / f"changelog-v{version}.json",
        "manifest": root / "dataset" / "manifests" / f"benchmark-v{version}.json",
        "receipt": root / "dataset" / "replication" / f"rmi-v{version}.json",
        "frozen_requests": root / "dataset" / "requests" / "frozen" / f"support-v{version}.jsonl",
        "frozen_renderings": root / "dataset" / "renderings" / "frozen" / f"support-v{version}.jsonl",
        "frozen_procedures": root / "dataset" / "procedures" / "frozen" / f"support-v{version}.jsonl",
    }


def _base_paths(root: Path, version: str) -> dict[str, Path]:
    elicitation = root / "dataset" / "elicitation" / f"approved-v{version}.jsonl"
    if not elicitation.exists():
        elicitation = root / "dataset" / "elicitation" / "approved.jsonl"
    return {
        "domain": root / "dataset" / "domain" / f"v{version}",
        "cases": root / "dataset" / "cases" / f"support-v{version}",
        "interfaces": root / "dataset" / "interfaces" / f"v{version}",
        "splits": root / "dataset" / "splits",
        "elicitation": elicitation,
    }


def _ensure_new_version(root: Path, version: str, targets: dict[str, Path]) -> None:
    conflicts = [path for path in targets.values() if path.exists()]
    if conflicts:
        rendered = "\n".join(f"  - {path.relative_to(root)}" for path in conflicts)
        raise ReplicationError(
            f"refusing to overwrite existing v{version} artifacts:\n{rendered}"
        )


def _build_rmi_case(
    card: RMISeedCard,
    *,
    public_message: str,
    domain: DomainStore,
    created_by: str,
    created_at: str,
) -> dict[str, Any]:
    incident = {
        "assigned_team": card.assigned_team,
        "awaiting_party": "NONE",
        "escalation_count": card.escalation_count,
        "information_complete": False,
        "reporter_id": card.reporter_id,
        "reporter_notification_sent": False,
        "severity": card.severity,
        "status": "OPEN",
        "support_tier": card.support_tier,
    }
    initial_state = {"incidents": {card.incident_id: incident}}
    arguments = {"incident_id": card.incident_id, "message": public_message}
    accepted, resulting_state, detail = recompute_gold_state(
        domain,
        initial_state,
        "request_more_information",
        arguments,
        RUN_CLOCK_PLACEHOLDER,
    )
    if not accepted:
        raise ReplicationError(f"{card.case_id}: simulator rejected seed case: {detail}")
    record = {
        "schema_version": models.SCHEMA_VERSION,
        "case_id": card.case_id,
        "domain": "support",
        "title": card.title,
        "family_id": "RMI_REPLICATION",
        "canonical": {
            "entity_type": "INCIDENT",
            "entity_id": card.incident_id,
            "operation_id": "REQUEST_MORE_INFORMATION",
            "arguments": {"message": public_message},
        },
        "initial_state": initial_state,
        "gold": {
            "decision": "ACT",
            "tool": "request_more_information",
            "arguments": arguments,
            "resulting_state": resulting_state,
        },
        "tags": [
            "single_turn",
            "tool_selection",
            "rmi_replication",
            "protected_argument",
        ],
        "difficulty": card.difficulty,
        "created_by": created_by,
        "created_at": created_at,
    }
    return models.CanonicalCase.model_validate(record).model_dump(mode="json")


def scaffold_rmi_replication(
    root: Path,
    seed: RMIReplicationSeed,
    *,
    reviewed_messages: dict[str, str],
    creator: str,
) -> dict[str, Any]:
    """Create a new versioned case corpus without touching any manifest."""
    if set(reviewed_messages) != {card.case_id for card in seed.cases}:
        raise ReplicationError("reviewed messages must contain every seed case exactly once")
    if len(set(reviewed_messages.values())) != len(reviewed_messages):
        raise ReplicationError("every canonical case must use a distinct public message")

    targets = _version_paths(root, seed.benchmark_version)
    _ensure_new_version(root, seed.benchmark_version, targets)
    bases = _base_paths(root, seed.base_benchmark_version)
    missing = [path for path in bases.values() if not path.exists()]
    if missing:
        raise ReplicationError(
            "missing base artifacts:\n" + "\n".join(f"  - {path}" for path in missing)
        )

    domain = DomainStore.load(root, bases["domain"])
    base_cases = load_cases(root, bases["cases"])
    case_rows = []
    for card in seed.cases:
        if card.case_id in base_cases:
            raise ReplicationError(f"duplicate case ID {card.case_id}")
        case_rows.append(
            _build_rmi_case(
                card,
                public_message=reviewed_messages[card.case_id].strip(),
                domain=domain,
                created_by=creator,
                created_at=seed.created_at,
            )
        )

    split_docs: dict[str, dict[str, Any]] = {}
    for split_name in ("development", "validation", "test"):
        document = json_read(bases["splits"] / f"{split_name}.json")
        if split_name == "validation":
            document = {
                **document,
                "case_ids": document["case_ids"] + [row["case_id"] for row in case_rows],
            }
        split_docs[split_name] = document

    receipt = {
        "schema_version": models.SCHEMA_VERSION,
        "replication_id": seed.replication_id,
        "benchmark_version": seed.benchmark_version,
        "base_benchmark_version": seed.base_benchmark_version,
        "created_at": seed.created_at,
        "created_by": creator,
        "status": "CASES_SCAFFOLDED",
        "case_ids": [row["case_id"] for row in case_rows],
        "seed_hash": hash_json_artifact(seed.model_dump(mode="json")),
        "public_message_hashes": {
            row["case_id"]: hash_json_artifact(row["canonical"]["arguments"]["message"])
            for row in case_rows
        },
    }
    changelog = [
        {
            "version": seed.benchmark_version,
            "change": (
                "Added eight independent REQUEST_MORE_INFORMATION persistence-replication "
                "cases and a versioned validation split. Existing benchmark versions are unchanged."
            ),
            "approved_by": creator,
        },
        {
            "version": seed.benchmark_version,
            "change": (
                "The replication holds each case's exact public message constant across canonical, "
                "natural, and high-lexical-distance user requests."
            ),
            "approved_by": creator,
        },
    ]

    dataset_root = root / "dataset"
    dataset_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".rmi-replication-", dir=dataset_root))
    moved: list[Path] = []
    try:
        stage_domain = stage / "domain"
        stage_cases = stage / "cases"
        stage_interfaces = stage / "interfaces"
        stage_splits = stage / "splits"
        shutil.copytree(bases["domain"], stage_domain)
        shutil.copytree(bases["cases"], stage_cases)
        shutil.copytree(bases["interfaces"], stage_interfaces)
        stage_splits.mkdir()
        for row in case_rows:
            json_write(stage_cases / f"{row['case_id']}.json", row)
        for split_name, document in split_docs.items():
            json_write(stage_splits / f"{split_name}.json", document)
        shutil.copy2(bases["elicitation"], stage / "elicitation.jsonl")
        json_write(stage / "changelog.json", changelog)
        json_write(stage / "receipt.json", receipt)

        DomainStore.load(root, stage_domain)
        staged_cases = load_cases(root, stage_cases)
        if len(staged_cases) != len(base_cases) + len(case_rows):
            raise ReplicationError("staged case corpus has an unexpected case count")

        commits = [
            (stage_domain, targets["domain"]),
            (stage_cases, targets["cases"]),
            (stage_interfaces, targets["interfaces"]),
            (stage_splits, targets["splits"]),
            (stage / "elicitation.jsonl", targets["elicitation"]),
            (stage / "changelog.json", targets["changelog"]),
            (stage / "receipt.json", targets["receipt"]),
        ]
        _ensure_new_version(root, seed.benchmark_version, targets)
        for source, destination in commits:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            moved.append(destination)
    except Exception:
        for destination in reversed(moved):
            if destination.is_dir():
                shutil.rmtree(destination)
            elif destination.exists():
                destination.unlink()
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    return {
        "version": seed.benchmark_version,
        "case_count": len(case_rows),
        "case_ids": [row["case_id"] for row in case_rows],
        "paths": {
            key: str(path.relative_to(root))
            for key, path in targets.items()
            if key in {
                "domain", "cases", "interfaces", "splits",
                "elicitation", "changelog", "receipt",
            }
        },
    }


def suggested_variant_texts(case: models.CanonicalCase) -> dict[VariantCategory, str]:
    message = str(case.canonical.arguments["message"])
    incident_id = case.canonical.entity_id
    incident = case.initial_state["incidents"][incident_id]
    team = str(incident["assigned_team"]).replace("_", " ").title()
    return {
        "canonical": (
            f'Request more information for incident {incident_id} with this exact public message: '
            f'"{message}"'
        ),
        "natural": (
            f'On incident {incident_id}, ask the reporter: "{message}" '
            f'Keep {team} assigned while we wait for the response.'
        ),
        "high_lexical_distance": (
            f'Do not close {incident_id} yet. Put the work on hold for reporter feedback and add '
            f'exactly this public comment: "{message}" {team} still owns it.'
        ),
    }


def _instruction_text(text: str, protected_message: str) -> str:
    return text.replace(protected_message, "", 1)


def validate_variant_text(
    case: models.CanonicalCase,
    category: VariantCategory,
    text: str,
) -> list[str]:
    errors: list[str] = []
    message = str(case.canonical.arguments["message"])
    incident_id = case.canonical.entity_id
    if text.count(message) != 1:
        errors.append("wording must contain the exact public message exactly once")
    if incident_id not in text:
        errors.append(f"wording must contain anchored entity ID {incident_id}")
    instruction = _instruction_text(text, message).casefold()
    has_operation = "request more information" in instruction
    has_entity_term = bool(re.search(r"\bincident\b", instruction))
    if category == "canonical" and not (has_operation and has_entity_term):
        errors.append(
            "canonical wording must use both 'request more information' and 'incident'"
        )
    if category == "natural" and has_operation:
        errors.append("natural wording must not use the canonical operation phrase")
    if category == "high_lexical_distance":
        if has_operation:
            errors.append("high-distance wording must not use the canonical operation phrase")
        if has_entity_term:
            errors.append(
                "high-distance wording must avoid the canonical entity term outside the message"
            )
    if category != "canonical" and not any(
        cue in instruction for cue in ("reporter", "feedback", "response", "public comment")
    ):
        errors.append("wording needs a clear reporter-feedback or response cue")
    return errors


def _variant_labels(
    category: VariantCategory,
    text: str,
    protected_message: str,
) -> dict[str, Any]:
    instruction = _instruction_text(text, protected_message).casefold()
    category_fields = {
        "canonical": {
            "variation_axes": ["canonical_terminology", "typed"],
            "lexical_distance_band": "LOW",
        },
        "natural": {
            "variation_axes": [
                "operation_synonym", "syntactic_paraphrase", "conversational", "typed",
            ],
            "lexical_distance_band": "MEDIUM",
        },
        "high_lexical_distance": {
            "variation_axes": [
                "idiomatic", "indirect_request", "conversational",
                "high_lexical_distance", "typed",
            ],
            "lexical_distance_band": "HIGH",
        },
    }[category]
    return {
        "semantic_role": "INVARIANT",
        "adequacy": "ADEQUATE",
        "ambiguity": "UNAMBIGUOUS",
        "expected_behavior": "EXECUTE",
        "lexical_equivalence": "INVARIANT",
        "missing_information": [],
        "context_id": None,
        **category_fields,
        "contains_canonical_entity_term": bool(re.search(r"\bincident\b", instruction)),
        "contains_canonical_operation_term": "request more information" in instruction,
        "contains_model_discovered_term": False,
        "contains_organization_term": False,
        "contrast_operation_id": None,
        "contrast_arguments": None,
        "refusal_operation_id": None,
        "refusal_policy_reference": None,
    }


def _request_id(case_id: str, category_index: int) -> str:
    return f"REQ-{case_id.replace('_', '-')}-{category_index:04d}"


def _all_request_ids(root: Path) -> set[str]:
    request_ids: set[str] = set()
    for lifecycle in ("candidate", "approved", "frozen", "rejected"):
        directory = root / "dataset" / "requests" / lifecycle
        if not directory.exists():
            continue
        for path in directory.glob("*.jsonl"):
            request_ids.update(row["request_id"] for row in jsonl_read(path))
    return request_ids


def _focused_run_config(
    *, version: str, case_ids: list[str], request_ids: list[str], include_lp3: bool,
) -> dict[str, Any]:
    persistence = [
        "LP0B_GOLD_START_LANGUAGE_BALANCED",
        "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM",
        "LP1_CANONICAL_ONCE",
    ]
    if include_lp3:
        persistence.append("LP3_CANONICAL_PROCEDURE_TOOL")
    return {
        "schema_version": models.SCHEMA_VERSION,
        "run_name": f"v{version}-rmi-persistence-replication-1x",
        "benchmark_manifest": f"dataset/manifests/benchmark-v{version}.json",
        "model_config": "config/models.local.yaml",
        "tracks": {
            "boundary": {"enabled": False, "architectures": []},
            "intent_elicitation": {"enabled": False, "architectures": []},
            "memory_ablation": {"enabled": False, "architectures": []},
            "progressive_formalization": {
                "enabled": True,
                "conditions": [],
                "persistence_conditions": persistence,
                "persistence_intent_modes": {condition: ["gold"] for condition in persistence},
                "procedure_registry": f"dataset/procedures/frozen/support-v{version}.jsonl",
                "generic_action_interface": (
                    f"dataset/interfaces/v{version}/generic-action-proposal.json"
                ),
                "typed_action_interfaces": (
                    f"dataset/interfaces/v{version}/typed-tools/support.jsonl"
                ),
                "run_cumulative_ladder": False,
                "run_component_ablations": False,
                "run_language_persistence_ablation": True,
            },
            "post_canonical": {"enabled": False, "architectures": []},
            "agent_loop": {
                "enabled": False, "intent_modes": ["gold"],
                "conditions": [], "case_ids": [],
            },
        },
        "selection": {
            "split": "validation",
            "case_ids": case_ids,
            "request_ids": request_ids,
            "variation_axes": [],
            "adequacy": ["ADEQUATE"],
            "ambiguity": ["UNAMBIGUOUS"],
            "expected_behavior": ["EXECUTE"],
        },
        "execution": {
            "repetitions": 1,
            "concurrency": 4,
            "randomize_matrix_order": True,
            "random_seed": 104729,
            "transport_retries": 3,
            "semantic_retries": 0,
            "cache_responses": False,
            "run_clock": "2026-07-20T12:00:00Z",
        },
        "evaluation": {
            "minimum_schema_validity_for_interpretation": 1.0,
            "minimum_independent_cases_for_interpretation": 6,
            "minimum_operation_families_for_generalization": 3,
            "deterministic_first": True,
            "optional_llm_judge": False,
            "human_review_on_judge_disagreement": True,
            "blind_condition_labels": True,
            "bootstrap_samples": 2000,
            "confidence_level": 0.95,
            "multiple_comparison_method": "benjamini-hochberg",
            "practical_equivalence": {
                "baseline_architecture": "LP0B_GOLD_START_LANGUAGE_BALANCED",
                "success_margin": 0.01,
                "false_action_margin": 0.0,
                "operational_invariance_margin": 0.02,
            },
            "complexity_accounting": {
                "enabled": True,
                "include_model_calls": True,
                "include_external_services": True,
                "include_persisted_state": True,
                "include_operator_runbook_steps": True,
            },
            "formalization_accounting": {
                "record_representation_ledger": True,
                "record_procedure_adherence": True,
                "record_action_boundary_errors": True,
                "require_information_parity_check": True,
            },
        },
        "tracing": {
            "local_jsonl": True,
            "langsmith": False,
            "redact_secrets": True,
            "include_prompts": True,
            "include_raw_responses": True,
        },
    }


def author_rmi_variants(
    root: Path,
    *,
    version: str,
    variant_texts: dict[str, dict[VariantCategory, str]],
    creator: str,
    include_lp3: bool = False,
    output: Path | None = None,
    run_config_output: Path | None = None,
) -> dict[str, Any]:
    """Write exactly three validated human candidates per replication case."""
    receipt_path = root / "dataset" / "replication" / f"rmi-v{version}.json"
    if not receipt_path.exists():
        raise ReplicationError(
            f"missing scaffold receipt {receipt_path.relative_to(root)}; run scaffold-rmi first"
        )
    receipt = json_read(receipt_path)
    cases_root = root / "dataset" / "cases" / f"support-v{version}"
    cases = load_cases(root, cases_root)
    case_ids = list(receipt["case_ids"])
    replication_cases = {case_id: cases[case_id] for case_id in case_ids}
    if set(variant_texts) != set(case_ids):
        raise ReplicationError("variant input must contain every scaffolded case exactly once")

    output = output or (
        root / "dataset" / "requests" / "candidate" / f"rmi-replication-v{version}.jsonl"
    )
    run_config_output = run_config_output or (
        root / "config" / f"run.v{version}-rmi-replication-1x.yaml"
    )
    for path in (output, run_config_output):
        if path.exists():
            raise ReplicationError(
                f"refusing to overwrite existing artifact {path.relative_to(root)}"
            )

    existing_ids = _all_request_ids(root)
    rows: list[dict[str, Any]] = []
    normalized_texts: set[str] = set()
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for case_id in case_ids:
        case = replication_cases[case_id]
        supplied = variant_texts[case_id]
        if set(supplied) != set(VARIANT_CATEGORIES):
            raise ReplicationError(
                f"{case_id}: exactly three named variant categories are required"
            )
        message = str(case.canonical.arguments["message"])
        for index, category in enumerate(VARIANT_CATEGORIES, 1):
            text = supplied[category].strip()
            errors = validate_variant_text(case, category, text)
            if errors:
                raise ReplicationError(f"{case_id} {category}: " + "; ".join(errors))
            normalized = " ".join(text.casefold().split())
            if normalized in normalized_texts:
                raise ReplicationError(f"{case_id} {category}: duplicate normalized wording")
            normalized_texts.add(normalized)
            request_id = _request_id(case_id, index)
            if request_id in existing_ids:
                raise ReplicationError(f"request ID already exists: {request_id}")
            record = {
                "schema_version": models.SCHEMA_VERSION,
                "request_id": request_id,
                "case_id": case_id,
                "text": text,
                "language": "en-US",
                "source": {
                    "type": "human", "creator": creator, "model_provider": None,
                    "model_id": None, "prompt_id": None, "seed": None,
                },
                "labels": _variant_labels(category, text, message),
                "validation": {
                    "status": "CANDIDATE",
                    "semantic_equivalence": None,
                    "adequacy_verified": None,
                    "ambiguity_verified": None,
                    "reviewers": [],
                    "approved_by": None,
                    "approved_at": None,
                    "critic_judgments": [],
                },
                "provenance": {
                    "created_at": now,
                    "source_run_id": f"rmi-replication-v{version}",
                    "parent_request_id": None,
                    "supersedes_request_ids": [],
                    "content_hash": None,
                },
                "audio_uri": None,
                "transcript_kind": "typed",
            }
            rows.append(models.NLRequest.model_validate(record).model_dump(mode="json"))
            existing_ids.add(request_id)

    config = _focused_run_config(
        version=version,
        case_ids=case_ids,
        request_ids=[row["request_id"] for row in rows],
        include_lp3=include_lp3,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    run_config_output.parent.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix=".rmi-variants-", dir=output.parent))
    try:
        staged_jsonl = stage_dir / output.name
        staged_config = stage_dir / run_config_output.name
        jsonl_write(staged_jsonl, rows)
        staged_config.write_text(
            yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        if output.exists() or run_config_output.exists():
            raise ReplicationError("output appeared during authoring; refusing to overwrite")
        os.replace(staged_jsonl, output)
        try:
            os.replace(staged_config, run_config_output)
        except Exception:
            output.unlink(missing_ok=True)
            raise
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)

    return {
        "version": version,
        "case_count": len(case_ids),
        "request_count": len(rows),
        "conditions": config["tracks"]["progressive_formalization"][
            "persistence_conditions"
        ],
        "candidate_path": str(output.relative_to(root)),
        "run_config_path": str(run_config_output.relative_to(root)),
    }
