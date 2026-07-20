"""Experiment 7: plausible substitution and input modality (spec §30; D-014).

Stores intended concept, typed text, human transcript, and ASR transcript as
separate artifacts and measures where lexical/canonical identity first changes.
Audio collection requires participants and consent (§30.10) and is operator
work; the shipped chains are text-only demonstrations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lexstab.artifacts import jsonl_read, jsonl_write
from lexstab.config import load_models_config
from lexstab.prompts import PromptLibrary
from lexstab.providers.base import extract_json_object
from lexstab.providers.registry import build_provider

ARTIFACT_KINDS = ("typed_text", "human_transcript", "asr_transcript")


def lexical_mutation_stage(chain: dict) -> str | None:
    """First artifact whose surface form differs from the typed expression."""
    typed = (chain.get("typed_text") or "").lower().strip()
    for kind in ("human_transcript", "asr_transcript"):
        value = (chain.get(kind) or "").lower().strip()
        if value and value != typed:
            return kind
    return None


def run_modality_experiment(
    root: Path, dataset_path: Path, models_path: str, output: Path,
) -> dict[str, Any]:
    prompts = PromptLibrary(root / "prompts")
    models_config = load_models_config(root / models_path, strict_env=False)
    role = models_config.role("boundary_canonicalizer")
    adapter = build_provider(role)
    rows = []
    for chain in jsonl_read(dataset_path):
        for kind in ARTIFACT_KINDS:
            text = chain.get(kind)
            if not text:
                continue
            record = adapter.invoke(
                role="boundary_canonicalizer",
                model_id=role.model_id or "mock",
                messages=[{
                    "role": "system",
                    "content": prompts.get("engineering-canonicalizer.v1").render(user_request=text),
                }],
                tools=None, response_schema=None, parameters=role.parameters,
                metadata={"run_id": "modality", "cell_id": f"modality:{chain['chain_id']}:{kind}",
                          "timestamp": "", "response_kind": "engineering_resolution"},
            )
            obj, _err = extract_json_object(record.normalized_text)
            resolution = obj or {}
            gold = chain["intended"]
            expected_clarify = bool(chain.get("gold_clarify"))
            resolved_correct = (
                resolution.get("status") == "RESOLVED"
                and resolution.get("operation_id") == gold["operation_id"]
                and (gold.get("knowledge_source") is None
                     or resolution.get("knowledge_source") == gold["knowledge_source"])
            )
            clarified = resolution.get("status") == "CLARIFY"
            rows.append({
                "chain_id": chain["chain_id"],
                "concept_card_id": chain.get("concept_card_id"),
                "participant_id": chain.get("participant_id"),
                "artifact_kind": kind,
                "parse_ok": obj is not None,
                "resolution": resolution,
                "gold_operation": gold["operation_id"],
                "expected_clarify": expected_clarify,
                "correct": clarified if expected_clarify else resolved_correct,
                "false_action": resolved_correct is False and resolution.get("status") == "RESOLVED"
                and expected_clarify,
                "lexical_mutation_stage": lexical_mutation_stage(chain),
            })
    jsonl_write(output, rows)
    by_kind: dict[str, list[dict]] = {}
    for row in rows:
        by_kind.setdefault(row["artifact_kind"], []).append(row)
    return {
        "chains": len({row["chain_id"] for row in rows}),
        "accuracy_by_artifact": {
            kind: round(sum(1 for row in group if row["correct"]) / len(group), 4)
            for kind, group in sorted(by_kind.items())
        },
        "clarification_rate_on_ambiguous": (
            lambda amb: round(sum(1 for row in amb if row["correct"]) / len(amb), 4) if amb else None
        )([row for row in rows if row["expected_clarify"]]),
        "output": str(output),
    }
