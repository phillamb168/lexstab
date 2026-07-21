"""Model-facing rendering discovery (spec §15, §27.2, §42.8).

Blind naming: the prompt shows definitions and examples, never candidate
labels. Each sample runs in a fresh context. Discovery must use development
material only (§22.2); the discovered rendering is frozen before any
downstream testing (§49.4).
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from lexstab import models
from lexstab.artifacts import (
    DomainStore,
    json_read,
    json_write,
    jsonl_append,
    jsonl_read,
    jsonl_write,
)
from lexstab.config import ModelsConfig
from lexstab.prompts import PromptLibrary
from lexstab.hashing import hash_json_artifact
from lexstab.providers.base import (
    BaseAdapter,
    extract_json_object,
    provider_failure_category,
)

NORMALIZATION_VERSION = "lexical-label-normalization.v1"
MAX_CONSECUTIVE_INVALID_RESPONSES = 5


class DiscoveryError(RuntimeError):
    """Discovery stopped after preserving every completed provider call."""


def normalize_label(label: str) -> str:
    """Normalization rules reported with term entropy (§38.8): lowercase,
    strip punctuation, collapse whitespace, naive plural trim."""
    text = re.sub(r"[^a-z0-9 ]", "", label.lower()).strip()
    text = re.sub(r"\s+", " ", text)
    words = [word[:-1] if word.endswith("s") and len(word) > 3 else word for word in text.split()]
    return " ".join(words)


def term_entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _default_checkpoint_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}.samples.jsonl")


def _summary_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}.summary.json")


def _checkpoint_audit(path: Path | None) -> dict[str, Any]:
    rows = jsonl_read(path) if path is not None and path.exists() else []
    keys = [(row["operation_id"], int(row["sample_index"])) for row in rows]
    status_counts = Counter(row["status"] for row in rows)
    by_operation = {}
    for operation_id in sorted({row["operation_id"] for row in rows}):
        operation_rows = [row for row in rows if row["operation_id"] == operation_id]
        operation_keys = {
            (row["operation_id"], int(row["sample_index"])) for row in operation_rows
        }
        by_operation[operation_id] = {
            "attempt_rows": len(operation_rows),
            "unique_sample_keys": len(operation_keys),
            "superseded_attempts": len(operation_rows) - len(operation_keys),
            "status_counts": dict(Counter(row["status"] for row in operation_rows)),
        }
    return {
        "attempt_rows": len(rows),
        "unique_sample_keys": len(set(keys)),
        "superseded_attempts": len(rows) - len(set(keys)),
        "status_counts": dict(status_counts),
        "by_operation": by_operation,
    }


def _write_summary(output: Path, summary: dict[str, Any], checkpoint: Path | None) -> None:
    summary["checkpoint_audit"] = _checkpoint_audit(checkpoint)
    json_write(_summary_path(output), summary)


def _response_schema(root: Path) -> dict[str, Any]:
    schema = dict(json_read(root / "schemas" / "lexical-name.schema.json"))
    schema.pop("$schema", None)
    schema.pop("$id", None)
    return schema


def _checkpoint_records(
    path: Path | None,
    *,
    provider: str,
    model_id: str,
    prompt_hash: str,
    response_schema_hash: str,
) -> dict[tuple[str, int], dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    records: dict[tuple[str, int], dict[str, Any]] = {}
    for row in jsonl_read(path):
        expected = {
            "provider": provider,
            "requested_model_id": model_id,
            "prompt_hash": prompt_hash,
            "response_schema_hash": response_schema_hash,
        }
        mismatches = [
            key for key, value in expected.items() if row.get(key) != value
        ]
        if mismatches:
            raise DiscoveryError(
                f"checkpoint {path} is incompatible with this discovery run: "
                f"mismatched {', '.join(mismatches)}; use a new output path"
            )
        records[(row["operation_id"], int(row["sample_index"]))] = row
    return records


def _parse_sample(record: models.InvocationRecord) -> tuple[str, dict | None, str | None]:
    provider_failure = provider_failure_category(record.finish_reason)
    if provider_failure:
        return "PROVIDER_ERROR", None, record.parse_error or provider_failure
    obj, parse_error = extract_json_object(record.normalized_text)
    if obj is None:
        return "INVALID", None, parse_error
    try:
        parsed = models.LexicalNameResponse.model_validate(obj)
    except Exception as exc:
        return "INVALID", None, f"lexical-name schema validation failed: {exc}"
    if not parsed.preferred_term.strip():
        return "INVALID", None, "preferred_term is empty"
    return "VALID", parsed.model_dump(mode="json"), None


def _sample_checkpoint_row(
    *,
    operation_id: str,
    sample_index: int,
    status: str,
    parsed: dict | None,
    error: str | None,
    record: models.InvocationRecord,
    prompt_hash: str,
    response_schema_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": models.SCHEMA_VERSION,
        "operation_id": operation_id,
        "sample_index": sample_index,
        "status": status,
        "parsed_response": parsed,
        "error": error,
        "provider": record.provider,
        "requested_model_id": record.requested_model_id,
        "reported_model_id": record.reported_model_id,
        "prompt_hash": prompt_hash,
        "response_schema_hash": response_schema_hash,
        "finish_reason": record.finish_reason,
        "provider_request_id": record.provider_request_id,
        "usage": record.usage,
        "invocation": record.model_dump(mode="json"),
    }


def _operation_sample_summary(rows: list[dict[str, Any]], requested: int) -> dict[str, Any]:
    return {
        "requested_sample_count": requested,
        "attempted_sample_count": len(rows),
        "valid_response_count": sum(row["status"] == "VALID" for row in rows),
        "invalid_response_count": sum(row["status"] == "INVALID" for row in rows),
        "provider_error_count": sum(row["status"] == "PROVIDER_ERROR" for row in rows),
    }


def discover_renderings(
    root: Path,
    domain: DomainStore,
    models_config: ModelsConfig,
    provider: BaseAdapter,
    *,
    operation_ids: list[str],
    samples: int = 50,
    role: str = "execution_primary",
    output: Path | None = None,
    checkpoint: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    prompts = PromptLibrary(root / "prompts")
    prompt = prompts.get("operation-lexical-convergence.v1")
    role_config = models_config.role(role)
    response_schema = _response_schema(root)
    response_schema_hash = hash_json_artifact(response_schema)
    if output is not None and checkpoint is None:
        checkpoint = _default_checkpoint_path(output)
    checkpoints = _checkpoint_records(
        checkpoint,
        provider=role_config.provider,
        model_id=role_config.model_id or "",
        prompt_hash=prompt.content_hash,
        response_schema_hash=response_schema_hash,
    )
    cards = json_read(root / "dataset" / "renderings" / "discovery-cards" / "support.json")
    approved_rows = jsonl_read(root / "dataset" / "renderings" / "approved" / "support.jsonl")
    canonical_renderings = {
        row["operation_id"]: models.Rendering.model_validate(row)
        for row in approved_rows
        if row.get("category") == "CANONICAL_LABEL"
        and (row.get("validation") or {}).get("status") in ("APPROVED", "FROZEN")
    }
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidate_by_operation = {}
    if output is not None and output.exists():
        for row in jsonl_read(output):
            candidate_by_operation[row["operation_id"]] = row
    summary: dict[str, Any] = {
        "schema_version": models.SCHEMA_VERSION,
        "status": "RUNNING",
        "provider": role_config.provider,
        "requested_model_id": role_config.model_id or "",
        "prompt_id": prompt.prompt_id,
        "prompt_hash": prompt.content_hash,
        "response_schema": "lexical-name.schema.json",
        "response_schema_hash": response_schema_hash,
        "samples_per_operation": samples,
        "requested_operations": operation_ids,
        "candidate_output": str(output) if output else None,
        "sample_checkpoint": str(checkpoint) if checkpoint else None,
        "operations": {},
    }
    renderings = []
    failed_operations: list[str] = []
    for op_id in operation_ids:
        op = domain.operations[op_id]
        if op_id not in cards:
            raise ValueError(f"{op_id}: no blind discovery card")
        reference = canonical_renderings.get(op_id)
        if reference is None or not reference.label:
            raise ValueError(f"{op_id}: no active canonical rendering with a label")
        card = cards[op_id]
        reference_label_span = card.get("reference_template_label_span", reference.label)
        if progress:
            existing_count = sum(key[0] == op_id for key in checkpoints)
            progress(f"{op_id}: starting ({existing_count}/{samples} checkpointed)")
        consecutive_invalid = 0
        for sample_index in range(samples):
            key = (op_id, sample_index)
            existing = checkpoints.get(key)
            if existing is not None and existing["status"] != "PROVIDER_ERROR":
                if existing["status"] == "INVALID":
                    consecutive_invalid += 1
                else:
                    consecutive_invalid = 0
                if consecutive_invalid >= MAX_CONSECUTIVE_INVALID_RESPONSES:
                    break
                continue
            record = provider.invoke(
                role=role,
                model_id=role_config.model_id or "",
                messages=[{
                    "role": "system",
                    "content": prompt.render(
                        definition=card["definition"],
                        positive_examples="\n".join(f"- {item}" for item in card["positive_examples"]),
                        negative_examples="\n".join(f"- {item}" for item in card["negative_examples"]),
                    ),
                }],
                tools=None,
                response_schema=response_schema,
                parameters=role_config.parameters,
                metadata={
                    "run_id": "discovery",
                    "cell_id": f"discovery:{op_id}:{sample_index}",
                    "timestamp": now,
                    "response_kind": "lexical_name",
                    "response_schema_id": "lexical-name.schema.json",
                    "sample_index": sample_index,
                },
            )
            status, parsed, error = _parse_sample(record)
            row = _sample_checkpoint_row(
                operation_id=op_id,
                sample_index=sample_index,
                status=status,
                parsed=parsed,
                error=error,
                record=record,
                prompt_hash=prompt.content_hash,
                response_schema_hash=response_schema_hash,
            )
            checkpoints[key] = row
            if checkpoint is not None:
                jsonl_append(checkpoint, row)
            if progress and ((sample_index + 1) % 10 == 0 or status != "VALID"):
                progress(f"{op_id}: sample {sample_index + 1}/{samples} {status.lower()}")
            if status == "PROVIDER_ERROR":
                operation_rows = [
                    checkpoints[(op_id, index)]
                    for index in range(samples)
                    if (op_id, index) in checkpoints
                ]
                summary["operations"][op_id] = {
                    **_operation_sample_summary(operation_rows, samples),
                    "status": "PROVIDER_ERROR",
                    "last_error": error,
                }
                summary["status"] = "INTERRUPTED"
                if output is not None:
                    _write_summary(output, summary, checkpoint)
                raise DiscoveryError(
                    f"{op_id}: provider failure at sample {sample_index + 1}; "
                    f"completed calls were preserved in {checkpoint}: {error}"
                )
            consecutive_invalid = consecutive_invalid + 1 if status == "INVALID" else 0
            if consecutive_invalid >= MAX_CONSECUTIVE_INVALID_RESPONSES:
                break
        operation_rows = [
            checkpoints[(op_id, index)]
            for index in range(samples)
            if (op_id, index) in checkpoints
        ]
        counts = _operation_sample_summary(operation_rows, samples)
        valid_rows = [row for row in operation_rows if row["status"] == "VALID"]
        raw_terms = [row["parsed_response"]["preferred_term"] for row in valid_rows]
        reported_model_ids = [
            row["reported_model_id"] for row in operation_rows if row.get("reported_model_id")
        ]
        if counts["attempted_sample_count"] < samples:
            failed_operations.append(op_id)
            summary["operations"][op_id] = {
                **counts,
                "status": "INTERRUPTED_AFTER_CONSECUTIVE_INVALID_RESPONSES",
                "last_errors": [
                    row["error"] for row in operation_rows[-5:] if row.get("error")
                ],
            }
            if output is not None:
                _write_summary(output, summary, checkpoint)
            continue
        if not raw_terms:
            failed_operations.append(op_id)
            summary["operations"][op_id] = {
                **counts,
                "status": "NO_VALID_RESPONSES",
                "last_errors": [
                    row["error"] for row in operation_rows[-5:] if row.get("error")
                ],
            }
            if output is not None:
                _write_summary(output, summary, checkpoint)
            continue
        normalized = Counter(normalize_label(term) for term in raw_terms if term != "DEFINITION_ONLY")
        raw_by_normalized: dict[str, Counter] = {}
        for term in raw_terms:
            if term == "DEFINITION_ONLY":
                continue
            raw_by_normalized.setdefault(normalize_label(term), Counter())[term.strip()] += 1
        definition_only = sum(1 for term in raw_terms if term == "DEFINITION_ONLY")
        if normalized:
            modal_term, modal_count = normalized.most_common(1)[0]
            representative = raw_by_normalized[modal_term].most_common(1)[0][0]
            discovery_outcome = "LEXICAL_LABEL"
        else:
            modal_term, modal_count = "DEFINITION_ONLY", definition_only
            representative = reference.label
            discovery_outcome = "DEFINITION_ONLY"
        if not reference.template.casefold().startswith(reference_label_span.casefold()):
            raise ValueError(
                f"{op_id}: canonical template must begin with its reviewed label span"
            )
        template = representative + reference.template[len(reference_label_span):]
        model_slug = re.sub(r"[^A-Z0-9]+", "-", (role_config.model_id or "MODEL").upper()).strip("-")
        renderings.append({
            "schema_version": models.SCHEMA_VERSION,
            "rendering_id": f"REN-{op_id.replace('_', '-')}-DISCOVERED-{model_slug}-001",
            "operation_id": op_id,
            "entity_type": op.entity_type,
            "category": "MODEL_DISCOVERED",
            "label": representative,
            "template": template,
            "definition": card["definition"],
            "discovery": {
                "provider": role_config.provider,
                "model_id": role_config.model_id or "",
                "prompt_id": "operation-lexical-convergence.v1",
                "sample_count": samples,
                "normalized_label_count": modal_count,
                "convergence_rate": round(modal_count / samples, 4),
                "seed_policy": "provider-supported-seeds-or-recorded-null",
                "term_entropy": round(term_entropy(normalized), 4),
                "discovered_on_split": "development",
                "reported_model_id": Counter(reported_model_ids).most_common(1)[0][0] if reported_model_ids else None,
                "prompt_hash": prompt.content_hash,
                "normalization_version": NORMALIZATION_VERSION,
                "term_counts": (
                    dict(normalized.most_common())
                    if normalized else {"DEFINITION_ONLY": definition_only}
                ),
                "definition_only_rate": round(definition_only / samples, 4),
                "reference_rendering_id": reference.rendering_id,
                "reference_rendering_hash": hash_json_artifact(reference.model_dump(mode="json")),
                "reference_template_label_span": reference_label_span,
                "discovery_outcome": discovery_outcome,
                "attempted_sample_count": counts["attempted_sample_count"],
                "valid_response_count": counts["valid_response_count"],
                "invalid_response_count": counts["invalid_response_count"],
                "provider_error_count": counts["provider_error_count"],
            },
            "validation": {"status": "CANDIDATE", "reviewed_by": [], "approved_at": None},
            "provenance": {"created_at": now, "source_run_id": "discovery",
                           "parent_request_id": None, "content_hash": None},
            "_distribution": {
                "modal_term": representative,
                "convergence_rate": round(modal_count / samples, 4),
                "term_entropy": round(term_entropy(normalized), 4),
                "alternatives": dict(normalized.most_common(10)),
                "definition_only_rate": round(definition_only / samples, 4),
            },
        })
        candidate_by_operation[op_id] = renderings[-1]
        summary["operations"][op_id] = {
            **counts,
            "status": "COMPLETE" if counts["attempted_sample_count"] == samples else "PARTIAL",
            "modal_term": representative,
            "convergence_rate": round(modal_count / samples, 4),
            "term_entropy": round(term_entropy(normalized), 4),
            "definition_only_rate": round(definition_only / samples, 4),
        }
        if output is not None:
            jsonl_write(output, [candidate_by_operation[key] for key in sorted(candidate_by_operation)])
            _write_summary(output, summary, checkpoint)
    if output:
        persisted = []
        for rendering in candidate_by_operation.values():
            row = {key: value for key, value in rendering.items() if not key.startswith("_")}
            models.Rendering.model_validate(row)
            persisted.append({**row, "_distribution": rendering["_distribution"]})
        jsonl_write(output, sorted(persisted, key=lambda row: row["operation_id"]))
        summary["status"] = "INCOMPLETE" if failed_operations else "COMPLETE"
        summary["failed_operations"] = failed_operations
        _write_summary(output, summary, checkpoint)
    if failed_operations:
        raise DiscoveryError(
            "no valid structured responses for "
            + ", ".join(failed_operations)
            + f"; diagnostics are in {_summary_path(output) if output else 'the discovery summary'}"
        )
    return renderings


def review_rendering_candidates(
    input_path: Path,
    approved_path: Path,
    rejected_path: Path,
    *,
    reviewer: str,
    decisions: dict[str, str] | None = None,
    default_decision: str | None = None,
) -> dict[str, int]:
    """Apply selective human decisions while preserving deferred candidates."""
    rows = jsonl_read(input_path)
    existing = jsonl_read(approved_path) if approved_path.exists() else []
    existing_ids = {row["rendering_id"] for row in existing}
    rejected_existing = jsonl_read(rejected_path) if rejected_path.exists() else []
    approved, rejected, deferred = [], [], []
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for source_row in rows:
        rendering_id = source_row["rendering_id"]
        decision = ((decisions or {}).get(rendering_id, default_decision) or "DEFER").upper()
        if decision not in {"APPROVE", "REJECT", "DEFER", "NEEDS_SECOND_REVIEW"}:
            raise DiscoveryError(f"{rendering_id}: unsupported review decision {decision!r}")
        if rendering_id in existing_ids:
            continue

        row = {key: value for key, value in source_row.items() if not key.startswith("_")}
        validation = dict(row.get("validation") or {})
        reviewed_by = list(validation.get("reviewed_by") or [])
        if reviewer not in reviewed_by:
            reviewed_by.append(reviewer)
        validation["reviewed_by"] = reviewed_by

        if decision == "APPROVE":
            if row.get("category") == "MODEL_DISCOVERED":
                for prior in existing:
                    if (
                        prior.get("operation_id") == row.get("operation_id")
                        and prior.get("category") == "MODEL_DISCOVERED"
                        and (prior.get("validation") or {}).get("status")
                        in ("APPROVED", "FROZEN")
                    ):
                        prior["validation"]["status"] = "SUPERSEDED"
            validation.update({"status": "APPROVED", "approved_at": now})
            row["validation"] = validation
            models.Rendering.model_validate(row)
            existing.append(row)
            existing_ids.add(rendering_id)
            approved.append(row)
        elif decision == "REJECT":
            validation.update({"status": "REJECTED", "approved_at": None})
            row["validation"] = validation
            models.Rendering.model_validate(row)
            rejected.append(row)
        else:
            deferred_row = dict(source_row)
            deferred_validation = dict(deferred_row.get("validation") or {})
            deferred_validation.update({
                "status": "NEEDS_REVIEW",
                "reviewed_by": reviewed_by,
                "approved_at": None,
            })
            deferred_row["validation"] = deferred_validation
            deferred.append(deferred_row)

    jsonl_write(approved_path, existing)
    if rejected:
        jsonl_write(rejected_path, rejected_existing + rejected)
    if deferred:
        jsonl_write(input_path, deferred)
    else:
        input_path.unlink(missing_ok=True)
    return {
        "approved": len(approved),
        "rejected": len(rejected),
        "deferred": len(deferred),
    }
