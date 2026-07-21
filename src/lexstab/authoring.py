"""Dataset-authoring workflow — Graph A (spec §14, §18.1, §34).

Node functions produce candidate request artifacts. Models propose; humans
approve. The generator can never approve its own candidates (§7.9, §49.3);
critic disagreement routes to human review. This workflow is invoked only by
``lexstab author`` — never by ``lexstab run`` (§G7).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lexstab import models
from lexstab.artifacts import DomainStore, jsonl_read, jsonl_write, load_cases
from lexstab.config import ModelsConfig
from lexstab.domaintext import domain_summary
from lexstab.prompts import PromptLibrary
from lexstab.providers.base import BaseAdapter, extract_json_object


@dataclass
class AuthoringContext:
    root: Path
    domain: DomainStore
    cases: dict[str, models.CanonicalCase]
    prompts: PromptLibrary
    models_config: ModelsConfig
    providers: dict[str, BaseAdapter]
    authoring_run_id: str
    regeneration_limit: int = 1  # dataset-construction-only retry budget (§18.1)

    def invoke(self, role: str, prompt_id: str, variables: dict[str, str],
               response_kind: str, mock_key: str | None = None) -> dict | None:
        role_config = self.models_config.role(role)
        adapter = self.providers[role]
        prompt = self.prompts.get(prompt_id)
        record = adapter.invoke(
            role=role,
            model_id=role_config.model_id or "",
            messages=[{"role": "system", "content": prompt.render(**variables)}],
            tools=None,
            response_schema=None,
            parameters=role_config.parameters,
            metadata={
                "run_id": self.authoring_run_id,
                "cell_id": mock_key or prompt_id,
                "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "response_kind": response_kind,
            },
        )
        obj, _err = extract_json_object(record.normalized_text)
        return obj


def measure_axis_coverage(
    existing: list[dict], case_id: str, required_axes: list[str]
) -> dict[str, int]:
    counts = {axis: 0 for axis in required_axes}
    for row in existing:
        if row.get("case_id") != case_id:
            continue
        for axis in row.get("labels", {}).get("variation_axes", []):
            if axis in counts:
                counts[axis] += 1
    return counts


def plan_generation(ctx: AuthoringContext, case: models.CanonicalCase,
                    existing: list[dict], required_axes: list[str],
                    target_per_axis: int) -> dict | None:
    coverage = measure_axis_coverage(existing, case.case_id, required_axes)
    summaries = "\n".join(
        f"- [{', '.join(row['labels']['variation_axes'])}] {row['text']}"
        for row in existing if row.get("case_id") == case.case_id
    ) or "(none)"
    return ctx.invoke(
        "authoring_generator", "coverage-planner.v1",
        {
            "canonical_case": case.model_dump_json(indent=2),
            "existing_request_summaries": summaries,
            "required_axes": "\n".join(f"- {axis}" for axis in required_axes),
            "target_counts": json.dumps({axis: target_per_axis for axis in required_axes}),
        },
        "coverage_plan",
        mock_key=f"plan:{case.case_id}",
    )


def generate_candidates(ctx: AuthoringContext, case: models.CanonicalCase,
                        axes: list[str], count: int, existing: list[dict],
                        forbidden_terms: list[str] | None = None) -> list[dict]:
    obj = ctx.invoke(
        "authoring_generator", "request-generator.v1",
        {
            "canonical_case": case.model_dump_json(indent=2),
            "requested_axes": ", ".join(axes),
            "count": str(count),
            "forbidden_terms": ", ".join(forbidden_terms or []) or "(none)",
            "existing_requests": "\n".join(
                row["text"] for row in existing if row.get("case_id") == case.case_id
            ) or "(none)",
        },
        "generated_requests",
        mock_key=f"generate:{case.case_id}",
    )
    return (obj or {}).get("candidates", [])


def validate_equivalence(ctx: AuthoringContext, case: models.CanonicalCase, text: str) -> dict | None:
    return ctx.invoke(
        "authoring_equivalence_critic", "equivalence-critic.v1",
        {
            "canonical_case": case.model_dump_json(indent=2),
            "domain_rules": domain_summary(ctx.domain),
            "candidate_request": text,
        },
        "equivalence_judgment",
        mock_key=f"equiv:{case.case_id}:{text[:40]}",
    )


def challenge_equivalence(ctx: AuthoringContext, case: models.CanonicalCase, text: str,
                          prior: dict | None) -> dict | None:
    return ctx.invoke(
        "authoring_adversarial_critic", "adversarial-critic.v1",
        {
            "canonical_case": case.model_dump_json(indent=2),
            "domain_rules": domain_summary(ctx.domain),
            "candidate_request": text,
            "prior_judgment": json.dumps(prior or {}, sort_keys=True),
        },
        "adversarial_judgment",
        mock_key=f"adv:{case.case_id}:{text[:40]}",
    )


def classify_adequacy(ctx: AuthoringContext, case: models.CanonicalCase, text: str,
                      frozen_context: str) -> dict | None:
    return ctx.invoke(
        "authoring_equivalence_critic", "adequacy-critic.v1",
        {
            "canonical_case": case.model_dump_json(indent=2),
            "candidate_request": text,
            "frozen_context": frozen_context,
            "domain_requirements": domain_summary(ctx.domain),
        },
        "adequacy_judgment",
        mock_key=f"adeq:{case.case_id}:{text[:40]}",
    )


def classify_ambiguity(ctx: AuthoringContext, case: models.CanonicalCase, text: str,
                       frozen_context: str) -> dict | None:
    return ctx.invoke(
        "authoring_adversarial_critic", "ambiguity-classifier.v1",
        {
            "canonical_case": case.model_dump_json(indent=2),
            "candidate_request": text,
            "frozen_context": frozen_context,
            "domain_rules": domain_summary(ctx.domain),
        },
        "ambiguity_judgment",
        mock_key=f"ambig:{case.case_id}:{text[:40]}",
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _token_jaccard(a: str, b: str) -> float:
    ta, tb = set(_normalize_text(a).split()), set(_normalize_text(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def deduplicate(candidates: list[dict], existing_texts: list[str],
                similarity_threshold: float = 0.85) -> tuple[list[dict], list[list[str]]]:
    """Exact + normalized + token-similarity dedup (§14.6). Similarity only
    flags for review; it never decides equivalence by itself."""
    kept: list[dict] = []
    duplicate_groups: list[list[str]] = []
    seen_normalized = {_normalize_text(text) for text in existing_texts}
    for candidate in candidates:
        normalized = _normalize_text(candidate["text"])
        if normalized in seen_normalized:
            duplicate_groups.append([candidate["text"], "(exact duplicate)"])
            continue
        similar = [
            other["text"] for other in kept
            if _token_jaccard(candidate["text"], other["text"]) >= similarity_threshold
        ]
        if similar:
            candidate = {**candidate, "_similarity_flag": similar}
        seen_normalized.add(normalized)
        kept.append(candidate)
    return kept, duplicate_groups


def _next_request_id(case_id: str, existing_ids: set[str], kind: str = "STD") -> str:
    base = "REQ-" + case_id.replace("_", "-")
    if kind != "STD":
        base = f"{base}-{kind}"
    index = 1
    while f"{base}-{index:04d}" in existing_ids:
        index += 1
    return f"{base}-{index:04d}"


def build_candidate_record(
    ctx: AuthoringContext,
    case: models.CanonicalCase,
    candidate: dict,
    judgments: dict[str, dict | None],
    existing_ids: set[str],
    generator_model: str,
) -> dict:
    equivalence = judgments.get("equivalence") or {}
    adversarial = judgments.get("adversarial") or {}
    adequacy = judgments.get("adequacy") or {}
    ambiguity = judgments.get("ambiguity") or {}

    agree = (
        equivalence.get("equivalent") is True
        and equivalence.get("confidence_band") == "HIGH"
        and adversarial.get("recommended_disposition") == "ACCEPT"
        and adequacy.get("recommended_disposition") == "ACCEPT"
        and ambiguity.get("recommended_disposition", "ACCEPT") == "ACCEPT"
    )
    status = "CANDIDATE" if agree else "NEEDS_REVIEW"
    proposed_adequacy = adequacy.get("adequacy", "ADEQUATE")
    proposed_ambiguity = adequacy.get("ambiguity", ambiguity.get("ambiguity", "UNAMBIGUOUS"))
    proposed_behavior = adequacy.get("expected_behavior", "EXECUTE")
    axes = candidate.get("intended_axes") or ["syntactic_paraphrase"]
    axes = [axis for axis in axes if axis in models.VARIATION_AXES] or ["syntactic_paraphrase"]
    context_dependent = proposed_adequacy == "INADEQUATE"
    labels = {
        "semantic_role": "INVARIANT" if proposed_behavior == "EXECUTE" else "CLARIFICATION",
        "adequacy": proposed_adequacy,
        "ambiguity": proposed_ambiguity,
        "expected_behavior": proposed_behavior,
        "lexical_equivalence": "INVARIANT" if proposed_behavior == "EXECUTE" else "NOT_APPLICABLE",
        "missing_information": adequacy.get("missing_information", []),
        "context_id": "CTX-EMPTY-001" if context_dependent else None,
        "variation_axes": axes + (["typed"] if "typed" not in axes else []),
        "contains_canonical_entity_term": False,
        "contains_canonical_operation_term": False,
        "contains_model_discovered_term": False,
        "contains_organization_term": False,
        "lexical_distance_band": "MEDIUM",
    }
    return {
        "schema_version": models.SCHEMA_VERSION,
        "request_id": _next_request_id(case.case_id, existing_ids),
        "case_id": case.case_id,
        "text": candidate["text"],
        "language": "en-US",
        "source": {
            "type": "synthetic",
            "creator": None,
            "model_provider": ctx.models_config.role("authoring_generator").provider,
            "model_id": generator_model,
            "prompt_id": "request-generator.v1",
            "seed": None,
        },
        "labels": labels,
        "validation": {
            "status": status,
            "semantic_equivalence": equivalence.get("equivalent"),
            "adequacy_verified": None,
            "ambiguity_verified": None,
            "reviewers": [],
            "approved_by": None,
            "approved_at": None,
            "critic_judgments": [
                {"critic": "equivalence", "judgment": equivalence},
                {"critic": "adversarial", "judgment": adversarial},
                {"critic": "adequacy", "judgment": adequacy},
                {"critic": "ambiguity", "judgment": ambiguity},
            ],
        },
        "provenance": {
            "created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_run_id": ctx.authoring_run_id,
            "parent_request_id": None,
            "content_hash": None,
        },
        "audio_uri": None,
        "transcript_kind": "typed",
    }


def author_requests(
    ctx: AuthoringContext,
    *,
    case_ids: list[str] | None = None,
    axes: list[str] | None = None,
    count_per_axis: int = 4,
    existing: list[dict] | None = None,
) -> dict[str, Any]:
    """Full authoring pipeline for the selected cases (§18.1 node order)."""
    existing = existing or []
    generator_model = ctx.models_config.role("authoring_generator").model_id or ""
    axes = axes or ["entity_synonym", "operation_synonym", "idiomatic", "indirect_request"]
    state: dict[str, Any] = {
        "authoring_run_id": ctx.authoring_run_id,
        "accepted_candidates": [],
        "rejected_candidates": [],
        "human_review_required": [],
        "duplicate_groups": [],
        "errors": [],
        "coverage": {},
    }
    existing_ids = {row["request_id"] for row in existing}
    for case_id in case_ids or sorted(ctx.cases):
        case = ctx.cases[case_id]
        plan = plan_generation(ctx, case, existing, axes, count_per_axis)
        state["coverage"][case_id] = plan
        attempts = 0
        accepted_for_case: list[dict] = []
        candidates = generate_candidates(ctx, case, axes, count_per_axis, existing)
        while True:
            candidates, dup_groups = deduplicate(
                candidates,
                [row["text"] for row in existing] + [c["text"] for c in accepted_for_case],
            )
            state["duplicate_groups"].extend(dup_groups)
            regenerate = []
            for candidate in candidates:
                equivalence = validate_equivalence(ctx, case, candidate["text"])
                adversarial = challenge_equivalence(ctx, case, candidate["text"], equivalence)
                adequacy = classify_adequacy(ctx, case, candidate["text"], "(no shared context)")
                ambiguity = classify_ambiguity(ctx, case, candidate["text"], "(no shared context)")
                if equivalence and equivalence.get("equivalent") is False and (
                    equivalence.get("component_checks", {}).get("operation") == "DIFFERENT"
                ):
                    state["rejected_candidates"].append(
                        {"case_id": case_id, "text": candidate["text"],
                         "reason": "equivalence critic rejected", "judgment": equivalence}
                    )
                    regenerate.append(candidate)
                    continue
                record = build_candidate_record(
                    ctx, case, candidate,
                    {"equivalence": equivalence, "adversarial": adversarial,
                     "adequacy": adequacy, "ambiguity": ambiguity},
                    existing_ids, generator_model,
                )
                existing_ids.add(record["request_id"])
                accepted_for_case.append(record)
                if record["validation"]["status"] == "NEEDS_REVIEW":
                    state["human_review_required"].append(record["request_id"])
            if not regenerate or attempts >= ctx.regeneration_limit:
                break
            attempts += 1
            candidates = generate_candidates(
                ctx, case, axes, len(regenerate), existing + accepted_for_case
            )
        state["accepted_candidates"].extend(accepted_for_case)
    return state


def write_candidates(state: dict[str, Any], output: Path) -> int:
    rows = state["accepted_candidates"]
    for row in rows:
        models.NLRequest.model_validate(row)
    jsonl_write(output, rows)
    return len(rows)


# ---------------------------------------------------------------- manual add (§14.4)


def add_human_request(
    root: Path,
    *,
    case_id: str,
    text: str,
    semantic_role: str,
    adequacy: str,
    ambiguity: str,
    expected_behavior: str,
    lexical_equivalence: str,
    axes: list[str],
    creator: str,
    context_id: str | None = None,
    missing_information: list[str] | None = None,
    contrast_operation_id: str | None = None,
    contrast_arguments: dict | None = None,
    refusal_operation_id: str | None = None,
    refusal_policy_reference: str | None = None,
    output: Path | None = None,
) -> dict:
    cases = load_cases(root)
    if case_id not in cases:
        raise ValueError(f"unknown case {case_id}")
    output = output or (root / "dataset" / "requests" / "candidate" / "manual.jsonl")
    existing = jsonl_read(output) if output.exists() else []
    existing_ids = {row["request_id"] for row in existing}
    for directory in ("candidate", "approved", "frozen"):
        base = root / "dataset" / "requests" / directory
        if base.exists():
            for file in base.glob("*.jsonl"):
                existing_ids.update(row["request_id"] for row in jsonl_read(file))
    record = {
        "schema_version": models.SCHEMA_VERSION,
        "request_id": _next_request_id(case_id, existing_ids),
        "case_id": case_id,
        "text": text,
        "language": "en-US",
        "source": {"type": "human", "creator": creator, "model_provider": None,
                   "model_id": None, "prompt_id": None, "seed": None},
        "labels": {
            "semantic_role": semantic_role,
            "adequacy": adequacy,
            "ambiguity": ambiguity,
            "expected_behavior": expected_behavior,
            "lexical_equivalence": lexical_equivalence,
            "missing_information": missing_information or [],
            "context_id": context_id,
            "variation_axes": axes,
            "contains_canonical_entity_term": False,
            "contains_canonical_operation_term": False,
            "contains_model_discovered_term": False,
            "contains_organization_term": False,
            "lexical_distance_band": "MEDIUM",
            "contrast_operation_id": contrast_operation_id,
            "contrast_arguments": contrast_arguments,
            "refusal_operation_id": refusal_operation_id,
            "refusal_policy_reference": refusal_policy_reference,
        },
        "validation": {"status": "CANDIDATE", "semantic_equivalence": None,
                       "adequacy_verified": None, "ambiguity_verified": None,
                       "reviewers": [], "approved_by": None, "approved_at": None,
                       "critic_judgments": []},
        "provenance": {"created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "source_run_id": None, "parent_request_id": None, "content_hash": None},
        "audio_uri": None,
        "transcript_kind": "typed",
    }
    models.NLRequest.model_validate(record)
    existing.append(record)
    jsonl_write(output, existing)
    return record


# ---------------------------------------------------------------- review (§42.7)


def review_candidates(
    input_path: Path,
    *,
    reviewer_id: str,
    decisions: dict[str, str] | None = None,
    default_decision: str | None = None,
    notes: str = "",
    approved_output: Path | None = None,
    rejected_output: Path | None = None,
) -> dict[str, int]:
    """Batch review: apply decisions (request_id -> APPROVE/REJECT/NEEDS_SECOND_REVIEW).

    The interactive CLI wraps this. Approved rows append to the approved
    corpus; rejected rows move to the rejected directory. Frozen rows are
    immutable and never touched here."""
    rows = jsonl_read(input_path)
    approved, rejected, deferred = [], [], []
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for row in rows:
        decision = (decisions or {}).get(row["request_id"], default_decision)
        if decision is None:
            deferred.append(row)
            continue
        row = dict(row)
        validation = dict(row["validation"])
        validation["reviewers"] = list(validation.get("reviewers", [])) + [{
            "reviewer_id": reviewer_id, "decision": decision, "notes": notes, "reviewed_at": now,
        }]
        if decision in ("APPROVE", "EDIT_AND_APPROVE"):
            validation["status"] = "APPROVED"
            validation["approved_by"] = reviewer_id
            validation["approved_at"] = now
            validation["adequacy_verified"] = True
            validation["ambiguity_verified"] = True
            row["validation"] = validation
            models.NLRequest.model_validate(row)
            approved.append(row)
        elif decision == "REJECT":
            validation["status"] = "REJECTED"
            row["validation"] = validation
            rejected.append(row)
        else:
            validation["status"] = "NEEDS_REVIEW"
            row["validation"] = validation
            deferred.append(row)
    if approved and approved_output:
        existing = jsonl_read(approved_output) if approved_output.exists() else []
        existing_by_id = {row["request_id"]: row for row in existing}
        superseded_ids = {
            request_id
            for row in approved
            for request_id in (row.get("provenance") or {}).get(
                "supersedes_request_ids", []
            )
        }
        missing_superseded = sorted(superseded_ids - set(existing_by_id))
        if missing_superseded:
            raise ValueError(
                "approved candidates reference unknown superseded requests: "
                + ", ".join(missing_superseded)
            )
        updated_existing = []
        for row in existing:
            if row["request_id"] not in superseded_ids:
                updated_existing.append(row)
                continue
            replacement = dict(row)
            replacement_validation = dict(replacement["validation"])
            replacement_validation["status"] = "SUPERSEDED"
            replacement_validation["reviewers"] = list(
                replacement_validation.get("reviewers", [])
            ) + [{
                "reviewer_id": reviewer_id,
                "decision": "SUPERSEDE",
                "notes": (
                    "Superseded by an approved corrective request: "
                    + ", ".join(
                        candidate["request_id"]
                        for candidate in approved
                        if row["request_id"] in (
                            candidate.get("provenance") or {}
                        ).get("supersedes_request_ids", [])
                    )
                ),
                "reviewed_at": now,
            }]
            replacement["validation"] = replacement_validation
            models.NLRequest.model_validate(replacement)
            updated_existing.append(replacement)
        jsonl_write(approved_output, updated_existing + approved)
    if rejected and rejected_output:
        existing = jsonl_read(rejected_output) if rejected_output.exists() else []
        jsonl_write(rejected_output, existing + rejected)
    if deferred:
        jsonl_write(input_path, deferred)
    else:
        input_path.unlink(missing_ok=True)
    return {"approved": len(approved), "rejected": len(rejected), "deferred": len(deferred)}


def reviewer_agreement_export(paths: list[Path]) -> list[dict]:
    """Export reviewer decisions for inter-annotator agreement analysis (§14.5)."""
    rows = []
    for path in paths:
        if not path.exists():
            continue
        for row in jsonl_read(path):
            for review in row.get("validation", {}).get("reviewers", []):
                rows.append({
                    "request_id": row["request_id"],
                    "case_id": row.get("case_id"),
                    "reviewer_id": review.get("reviewer_id"),
                    "decision": review.get("decision"),
                    "labels": row.get("labels", {}),
                    "status": row.get("validation", {}).get("status"),
                })
    return rows
