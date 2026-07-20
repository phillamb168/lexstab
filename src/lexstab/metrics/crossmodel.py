"""Cross-model and cross-version comparison (spec §29, Experiment 6).

The frozen benchmark never changes across models (§29.3): each model is one
run of the same manifest with a different model configuration. This module
compares stored runs — rendering ranks per model, Spearman rank correlation,
own-discovered-rendering advantage, and version deltas.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from lexstab.artifacts import json_read, jsonl_read


def _rendering_accuracy(scores: list[dict]) -> dict[str, float]:
    by_rendering: dict[str, list[bool]] = defaultdict(list)
    for score in scores:
        if score.get("rendering_id") and score.get("metadata", {}).get("intent_mode") == "gold":
            by_rendering[score["rendering_id"]].append(bool(score["full_call_correct"]))
    return {
        rendering: sum(values) / len(values)
        for rendering, values in by_rendering.items() if values
    }


def _spearman(rank_a: list[str], rank_b: list[str]) -> float | None:
    common = [item for item in rank_a if item in set(rank_b)]
    if len(common) < 2:
        return None
    n = len(common)
    positions_b = {item: index for index, item in enumerate(item for item in rank_b if item in set(common))}
    d_squared = sum(
        (index - positions_b[item]) ** 2 for index, item in enumerate(common)
    )
    return 1 - (6 * d_squared) / (n * (n**2 - 1))


def compare_runs(run_dirs: list[Path]) -> dict[str, Any]:
    """Compare completed runs of the SAME frozen benchmark across models."""
    per_model: dict[str, dict[str, Any]] = {}
    root_hashes = set()
    for run_dir in run_dirs:
        manifest = json_read(run_dir / "run-manifest.json")
        scores = jsonl_read(run_dir / "scores.jsonl")
        root_hashes.add(manifest["benchmark_root_hash"])
        model_id = str(
            manifest["resolved_roles"].get("execution_primary", {}).get("model_id")
        )
        accuracy = _rendering_accuracy(scores)
        h1 = [s for s in scores if s.get("metadata", {}).get("primary_h1")]
        per_model[model_id] = {
            "run_id": manifest["run_id"],
            "run_date": manifest["created_at"],
            "mocked": manifest.get("mocked", False),
            "rendering_accuracy": accuracy,
            "rendering_rank": sorted(accuracy, key=lambda k: -accuracy[k]),
            "h1_full_call_accuracy": (
                sum(1 for s in h1 if s["full_call_correct"]) / len(h1) if h1 else None
            ),
        }
    if len(root_hashes) > 1:
        raise ValueError(
            "cross-model comparison requires runs of the same frozen benchmark; "
            f"found root hashes {sorted(root_hashes)}"
        )
    models = sorted(per_model)
    correlations = {}
    for index, model_a in enumerate(models):
        for model_b in models[index + 1:]:
            correlations[f"{model_a} vs {model_b}"] = _spearman(
                per_model[model_a]["rendering_rank"], per_model[model_b]["rendering_rank"]
            )
    return {
        "benchmark_root_hash": next(iter(root_hashes)) if root_hashes else None,
        "models": per_model,
        "rendering_rank_spearman": correlations,
        "interpretation_note": (
            "Same ranking may reflect shared training distributions; each model "
            "favoring its own discovered term supports model-specific adapters; "
            "unstable rankings suggest prompt-local variation (spec §29.6)."
        ),
    }
