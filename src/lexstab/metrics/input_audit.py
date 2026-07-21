"""Audit whether nominal request variants produced distinct model inputs.

The frozen request label describes the source stimulus. It does not prove that
the request text reached a model call. Gold-injected and other preformalized
conditions may collapse several request rows to one identical effective input.
This module makes that distinction explicit without changing any score.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from lexstab.hashing import hash_json_artifact


def _first_model_input_hash(invocations: list[dict[str, Any]]) -> str | None:
    if not invocations:
        return None
    first = invocations[0]
    model_visible_input = {
        "messages": first.get("messages"),
        "tools": first.get("tools"),
        "response_schema_id": first.get("response_schema_id"),
        "tool_call_mode": first.get("tool_call_mode"),
        "role": first.get("role"),
        "provider": first.get("provider"),
        "requested_model_id": first.get("requested_model_id"),
        "accepted_parameters": first.get("accepted_parameters"),
    }
    return hash_json_artifact(model_visible_input)


def effective_input_audit(
    scores: list[dict[str, Any]],
    invocations_by_cell: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Compare frozen source variants with the first effective model input.

    Grouping is by canonical case and exact execution cohort. This prevents a
    difference caused by architecture or intent mode from masquerading as a
    difference caused by the source request.
    """
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    missing_invocation_cells: list[str] = []
    for score in scores:
        meta = score.get("metadata") or {}
        prompt_hash = _first_model_input_hash(
            invocations_by_cell.get(score["cell_id"], [])
        )
        if prompt_hash is None:
            missing_invocation_cells.append(score["cell_id"])
        key = (
            score.get("track") or "none",
            score.get("architecture") or "none",
            meta.get("intent_mode") or "none",
            meta.get("procedure_selection") or "none",
            meta.get("procedure_packaging") or "none",
            score.get("case_id") or "none",
        )
        grouped[key].append({
            "cell_id": score["cell_id"],
            "request_id": score.get("request_id"),
            "repetition": score.get("repetition"),
            "lexical_distance_band": meta.get("lexical_distance_band"),
            "variation_axes": meta.get("variation_axes") or [],
            "first_model_input_hash": prompt_hash,
        })

    groups: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        request_ids = sorted({row["request_id"] for row in rows if row["request_id"]})
        hashes = sorted({
            row["first_model_input_hash"]
            for row in rows
            if row["first_model_input_hash"] is not None
        })
        bands = sorted({
            row["lexical_distance_band"]
            for row in rows
            if row["lexical_distance_band"] is not None
        })
        axes = sorted({axis for row in rows for axis in row["variation_axes"]})
        source_variation = len(request_ids) > 1
        if source_variation and len(hashes) == 1:
            classification = "SOURCE_VARIANTS_COLLAPSED_TO_IDENTICAL_MODEL_INPUT"
            claim_scope = "does_not_test_source_lexical_variation"
        elif source_variation and len(hashes) > 1:
            classification = "DISTINCT_MODEL_INPUTS"
            claim_scope = "source_lexical_variation_may_be_tested"
        elif len(hashes) == 1:
            classification = "SINGLE_MODEL_INPUT"
            claim_scope = "single_stimulus_or_repetition_only"
        else:
            classification = "MISSING_OR_MULTIPLE_UNATTRIBUTED_INPUTS"
            claim_scope = "requires_manual_audit"
        groups.append({
            "track": key[0],
            "architecture": key[1],
            "intent_mode": key[2],
            "procedure_selection": key[3],
            "procedure_packaging": key[4],
            "case_id": key[5],
            "n_cells": len(rows),
            "n_source_requests": len(request_ids),
            "n_repetitions": len({row["repetition"] for row in rows}),
            "n_unique_first_model_inputs": len(hashes),
            "source_request_ids": request_ids,
            "source_lexical_distance_bands": bands,
            "source_variation_axes": axes,
            "first_model_input_hashes": hashes,
            "classification": classification,
            "claim_scope": claim_scope,
        })

    counts: dict[str, int] = {}
    for group in groups:
        classification = group["classification"]
        counts[classification] = counts.get(classification, 0) + 1
    collapsed = [
        group for group in groups
        if group["classification"]
        == "SOURCE_VARIANTS_COLLAPSED_TO_IDENTICAL_MODEL_INPUT"
    ]
    return {
        "fingerprint_scope": (
            "first provider invocation: messages, tools, response schema, tool mode, "
            "role, provider, model, and accepted parameters"
        ),
        "grouping_unit": (
            "track + architecture + intent mode + procedure selection + "
            "procedure packaging + canonical case"
        ),
        "n_groups": len(groups),
        "classification_counts": counts,
        "n_collapsed_source_variant_groups": len(collapsed),
        "n_cells_in_collapsed_source_variant_groups": sum(
            group["n_cells"] for group in collapsed
        ),
        "missing_invocation_cells": sorted(missing_invocation_cells),
        "groups": groups,
    }
