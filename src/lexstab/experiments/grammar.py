"""Experiment 4: grammatical terminology (spec §27; D-014).

Conditions vary only the terminology used to name a fixed editorial phenomenon;
the labeled text corpus stays constant. Scoring is deterministic span-level
precision/recall/F1 plus unrelated-edit rate (§27.6). The shipped corpus is a
minimal demonstration; a research corpus is operator work.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lexstab.artifacts import jsonl_read, jsonl_write
from lexstab.config import load_models_config
from lexstab.prompts import PromptLibrary
from lexstab.providers.base import extract_json_object
from lexstab.providers.registry import build_provider

CONDITION_PROMPTS = {
    "author_term": ("grammar-author-term.v1", {"author_term": "novel definite reference"}),
    "model_term": ("grammar-model-term.v1", {"model_discovered_term": "unintroduced definite reference"}),
    "definition_only": ("grammar-definition-only.v1", {}),
    "model_term_definition": (
        "grammar-model-term-definition.v1",
        {"model_discovered_term": "unintroduced definite reference"},
    ),
}


def span_scores(gold: list[dict], predicted: list[dict]) -> dict[str, Any]:
    gold_spans = {(span["start_character"], span["end_character"]) for span in gold}
    predicted_spans = {
        (span.get("start_character"), span.get("end_character")) for span in predicted
    }
    tp = len(gold_spans & predicted_spans)
    precision = tp / len(predicted_spans) if predicted_spans else (1.0 if not gold_spans else 0.0)
    recall = tp / len(gold_spans) if gold_spans else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "precision": precision, "recall": recall, "f1": f1,
            "n_gold": len(gold_spans), "n_predicted": len(predicted_spans)}


def unrelated_edit_rate(original: str, corrected: str | None, gold: list[dict]) -> float | None:
    """Character-level check: edits outside gold spans count as unrelated."""
    if corrected is None:
        return None
    protected = [False] * len(original)
    for span in gold:
        for index in range(span["start_character"], min(span["end_character"], len(original))):
            protected[index] = True
    # crude alignment: compare outside-span prefix/suffix survival
    unprotected_original = "".join(
        char for index, char in enumerate(original) if not protected[index]
    )
    survived = 0
    corrected_iter = iter(corrected)
    for char in unprotected_original:
        for candidate in corrected_iter:
            if candidate == char:
                survived += 1
                break
    if not unprotected_original:
        return 0.0
    return round(1.0 - survived / len(unprotected_original), 4)


def run_grammar_experiment(
    root: Path, dataset_path: Path, models_path: str, condition: str, output: Path,
) -> dict[str, Any]:
    if condition not in CONDITION_PROMPTS:
        raise ValueError(f"unknown condition {condition}; options: {sorted(CONDITION_PROMPTS)}")
    prompt_id, term_vars = CONDITION_PROMPTS[condition]
    prompts = PromptLibrary(root / "prompts")
    models_config = load_models_config(root / models_path, strict_env=False)
    role = models_config.role("execution_primary")
    adapter = build_provider(role)
    rows = []
    for item in jsonl_read(dataset_path):
        record = adapter.invoke(
            role="execution_primary",
            model_id=role.model_id or "mock",
            messages=[{
                "role": "system",
                "content": prompts.get(prompt_id).render(text=item["text"], **term_vars),
            }],
            tools=None, response_schema=None, parameters=role.parameters,
            metadata={"run_id": "grammar", "cell_id": f"grammar:{condition}:{item['item_id']}",
                      "timestamp": "", "response_kind": "grammar_correction"},
        )
        obj, err = extract_json_object(record.normalized_text)
        predicted = (obj or {}).get("instances", [])
        classification = (obj or {}).get("phenomenon_present")
        rows.append({
            "item_id": item["item_id"],
            "condition": condition,
            "parse_ok": obj is not None,
            "spans": span_scores(item.get("instances", []), predicted),
            "classification_correct": classification == item["phenomenon_present"],
            "unrelated_edit_rate": unrelated_edit_rate(
                item["text"], (obj or {}).get("corrected_text"), item.get("instances", [])
            ),
            "raw": obj,
        })
    jsonl_write(output, rows)
    n = len(rows)
    return {
        "condition": condition,
        "items": n,
        "mean_f1": round(sum(row["spans"]["f1"] for row in rows) / n, 4) if n else None,
        "classification_accuracy": (
            round(sum(1 for row in rows if row["classification_correct"]) / n, 4) if n else None
        ),
        "parse_rate": round(sum(1 for row in rows if row["parse_ok"]) / n, 4) if n else None,
        "output": str(output),
    }
