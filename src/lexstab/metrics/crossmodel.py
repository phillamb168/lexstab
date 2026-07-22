"""Cross-model and cross-version comparison (spec section 29, Experiment 6).

The frozen benchmark never changes across models. This module compares stored,
evaluated runs without invoking a provider. It retains the original rendering
rank analysis and adds the focused persistence comparison used by the v0.3.0
REQUEST_MORE_INFORMATION replication.

The cross-model persistence estimand is a difference in differences:

    (comparison model structured benefit) - (baseline model structured benefit)

where structured benefit is the paired LP1 minus LP0B or LP0BV outcome. A
positive value means the comparison model benefits more from canonical-state
persistence than the baseline model on the frozen cells.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from lexstab.artifacts import json_read, jsonl_read
from lexstab.metrics.statistics import (
    case_level_sign_test,
    cluster_bootstrap_delta,
    cluster_bootstrap_rate,
    paired_discordance,
)


LP0B = "LP0B_GOLD_START_LANGUAGE_BALANCED"
LP0BV = "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM"
LP1 = "LP1_CANONICAL_ONCE"
PERSISTENCE_ARCHITECTURES = (LP0B, LP0BV, LP1)
PERSISTENCE_OUTCOMES = ("final_state_correct", "verbatim_arguments_correct")
PERSISTENCE_BENEFITS = (
    ("canonical_once_minus_prose", LP0B, LP1),
    ("canonical_once_minus_reminded_prose", LP0BV, LP1),
    ("reminder_minus_prose", LP0B, LP0BV),
)

_EXACT_MANIFEST_FIELDS = (
    "benchmark_root_hash",
    "matrix_hash",
    "matrix_seed",
    "run_clock",
    "analysis_plan_hash",
    "lockfile_hash",
    "provider_adapter_versions",
    "repetitions",
    "concurrency",
    "persistence_conditions",
    "prompt_hashes",
    "procedure_hashes",
    "interface_hashes",
)


def _rendering_accuracy(scores: list[dict]) -> dict[str, float]:
    by_rendering: dict[str, list[bool]] = defaultdict(list)
    for score in scores:
        if score.get("rendering_id") and score.get("metadata", {}).get("intent_mode") == "gold":
            by_rendering[score["rendering_id"]].append(bool(score["full_call_correct"]))
    return {
        rendering: sum(values) / len(values)
        for rendering, values in by_rendering.items()
        if values
    }


def _spearman(rank_a: list[str], rank_b: list[str]) -> float | None:
    common_set = set(rank_a) & set(rank_b)
    common = [item for item in rank_a if item in common_set]
    if len(common) < 2:
        return None
    n = len(common)
    positions_b = {
        item: index
        for index, item in enumerate(item for item in rank_b if item in common_set)
    }
    d_squared = sum((index - positions_b[item]) ** 2 for index, item in enumerate(common))
    return 1 - (6 * d_squared) / (n * (n**2 - 1))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _execution_usage(invocations: list[dict]) -> dict[str, Any]:
    rows = [row for row in invocations if row.get("role") == "execution_primary"]
    prompt_tokens = [int((row.get("usage") or {}).get("prompt_tokens") or 0) for row in rows]
    completion_tokens = [
        int((row.get("usage") or {}).get("completion_tokens") or 0) for row in rows
    ]
    latencies = [float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]
    finish_reasons = Counter(str(row.get("finish_reason") or "unknown") for row in rows)
    return {
        "calls": len(rows),
        "prompt_tokens": sum(prompt_tokens),
        "completion_tokens": sum(completion_tokens),
        "total_tokens": sum(prompt_tokens) + sum(completion_tokens),
        "completion_tokens_per_call_mean": (
            sum(completion_tokens) / len(completion_tokens) if completion_tokens else None
        ),
        "completion_tokens_per_call_max": max(completion_tokens) if completion_tokens else None,
        "completion_tokens_per_call_p95": _percentile(completion_tokens, 0.95),
        "latency_ms_mean": sum(latencies) / len(latencies) if latencies else None,
        "latency_ms_p95": _percentile(latencies, 0.95),
        "finish_reasons": dict(sorted(finish_reasons.items())),
    }


def _score_key(score: dict) -> tuple[str, str, int]:
    return (
        str(score["case_id"]),
        str(score["request_id"]),
        int(score.get("repetition") or 0),
    )


def _condition_map(scores: list[dict], architecture: str, outcome: str) -> dict[tuple, float]:
    selected = [
        score
        for score in scores
        if score.get("architecture") == architecture
        and score.get("metadata", {}).get("intent_mode") == "gold"
        and (score.get("metadata", {}).get("procedure_selection") or "none") == "none"
        and (score.get("metadata", {}).get("procedure_packaging") or "none") == "none"
        and score.get(outcome) is not None
    ]
    out: dict[tuple, float] = {}
    for score in selected:
        key = _score_key(score)
        if key in out:
            raise ValueError(
                f"duplicate persistence score for {architecture}, {outcome}, and key {key}"
            )
        out[key] = float(bool(score[outcome]))
    return out


def _require_same_keys(named_maps: dict[str, dict[tuple, float]], context: str) -> set[tuple]:
    if not named_maps:
        return set()
    names = list(named_maps)
    expected = set(named_maps[names[0]])
    for name in names[1:]:
        observed = set(named_maps[name])
        if observed != expected:
            missing = sorted(expected - observed)[:5]
            extra = sorted(observed - expected)[:5]
            raise ValueError(
                f"{context}: unpaired score keys for {name}; "
                f"missing={missing}, extra={extra}"
            )
    return expected


def _condition_summary(
    scores: list[dict], architecture: str, *, samples: int, seed: int
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "architecture": architecture,
        "cohort": {
            "intent_mode": "gold",
            "procedure_selection": "none",
            "procedure_packaging": "none",
        },
    }
    for outcome in PERSISTENCE_OUTCOMES:
        values = _condition_map(scores, architecture, outcome)
        observations = [(key[0], value) for key, value in sorted(values.items())]
        summary[outcome] = cluster_bootstrap_rate(
            observations, samples=samples, seed=seed
        ).to_dict()
    return summary


def _paired_delta(
    map_a: dict[tuple, float],
    map_b: dict[tuple, float],
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    keys = _require_same_keys({"a": map_a, "b": map_b}, "paired comparison")
    paired = [(key[0], map_a[key], map_b[key]) for key in sorted(keys)]
    return {
        "delta_b_minus_a": cluster_bootstrap_delta(
            paired, samples=samples, seed=seed
        ).to_dict(),
        "case_level_sign_test": case_level_sign_test(paired),
        "paired_cell_discordance": paired_discordance(paired),
    }


def _benefit_map(
    scores: list[dict], architecture_a: str, architecture_b: str, outcome: str
) -> dict[tuple, float]:
    map_a = _condition_map(scores, architecture_a, outcome)
    map_b = _condition_map(scores, architecture_b, outcome)
    keys = _require_same_keys(
        {architecture_a: map_a, architecture_b: map_b},
        f"within-model benefit {architecture_b} minus {architecture_a}",
    )
    return {key: map_b[key] - map_a[key] for key in keys}


def _within_model_persistence(
    scores: list[dict], *, samples: int, seed: int
) -> dict[str, Any] | None:
    available = {score.get("architecture") for score in scores}
    if not set(PERSISTENCE_ARCHITECTURES).issubset(available):
        return None
    conditions = {
        architecture: _condition_summary(scores, architecture, samples=samples, seed=seed)
        for architecture in PERSISTENCE_ARCHITECTURES
    }
    comparisons: dict[str, Any] = {}
    for label, architecture_a, architecture_b in PERSISTENCE_BENEFITS:
        comparisons[label] = {}
        for outcome in PERSISTENCE_OUTCOMES:
            comparison = _paired_delta(
                _condition_map(scores, architecture_a, outcome),
                _condition_map(scores, architecture_b, outcome),
                samples=samples,
                seed=seed,
            )
            comparison["condition_a"] = architecture_a
            comparison["condition_b"] = architecture_b
            comparison["outcome"] = outcome
            comparisons[label][outcome] = comparison
    return {
        "available": True,
        "conditions": conditions,
        "within_model_benefits": comparisons,
        "interpretation_scope": (
            "The persistence replication contains eight independent cases from one "
            "operation family. Intervals cluster by canonical case. Conclusions apply "
            "to the tested REQUEST_MORE_INFORMATION family, not all operations."
        ),
    }


def _load_run(run_dir: Path) -> dict[str, Any]:
    required = (
        "run-manifest.json",
        "run-summary.json",
        "metrics.json",
        "scores.jsonl",
        "matrix.jsonl",
        "invocations.jsonl",
    )
    missing = [name for name in required if not (run_dir / name).exists()]
    if missing:
        raise ValueError(f"{run_dir}: missing required evaluated run artifacts {missing}")
    manifest = json_read(run_dir / "run-manifest.json")
    summary = json_read(run_dir / "run-summary.json")
    metrics = json_read(run_dir / "metrics.json")
    if summary.get("status") != "complete" or not summary.get("healthy"):
        raise ValueError(f"{run_dir}: run must be complete and healthy before comparison")
    completion = metrics.get("completion") or {}
    if completion.get("completion_rate") != 1.0:
        raise ValueError(f"{run_dir}: evaluation is incomplete")
    role = (manifest.get("resolved_roles") or {}).get("execution_primary") or {}
    model_id = str(role.get("model_id") or "")
    if not model_id:
        raise ValueError(f"{run_dir}: execution_primary model_id is missing")
    return {
        "path": run_dir,
        "manifest": manifest,
        "summary": summary,
        "metrics": metrics,
        "scores": jsonl_read(run_dir / "scores.jsonl"),
        "matrix": jsonl_read(run_dir / "matrix.jsonl"),
        "invocations": jsonl_read(run_dir / "invocations.jsonl"),
        "model_id": model_id,
        "execution_role": role,
    }


def _non_execution_roles(manifest: dict) -> dict:
    return {
        key: value
        for key, value in (manifest.get("resolved_roles") or {}).items()
        if key != "execution_primary"
    }


def _check_compatibility(runs: list[dict[str, Any]]) -> dict[str, Any]:
    reference = runs[0]
    mismatches: list[str] = []
    warnings: list[str] = []
    for run in runs[1:]:
        for field in _EXACT_MANIFEST_FIELDS:
            if run["manifest"].get(field) != reference["manifest"].get(field):
                mismatches.append(
                    f"{run['model_id']}: manifest field {field} differs from "
                    f"{reference['model_id']}"
                )
        if run["matrix"] != reference["matrix"]:
            mismatches.append(
                f"{run['model_id']}: matrix rows differ from {reference['model_id']}"
            )
        if _non_execution_roles(run["manifest"]) != _non_execution_roles(reference["manifest"]):
            mismatches.append(
                f"{run['model_id']}: non-execution model roles differ from "
                f"{reference['model_id']}"
            )
        source_hash = run["metrics"].get("evaluation_harness_source_hash")
        reference_hash = reference["metrics"].get("evaluation_harness_source_hash")
        if not source_hash or not reference_hash:
            mismatches.append("evaluation_harness_source_hash is missing from one or more runs")
        elif source_hash != reference_hash:
            mismatches.append(
                f"{run['model_id']}: evaluation harness source hash differs from "
                f"{reference['model_id']}; re-evaluate both stored runs with the same code"
            )
        if run["manifest"].get("code_revision") != reference["manifest"].get("code_revision"):
            warnings.append(
                f"{run['model_id']}: execution code revision differs from "
                f"{reference['model_id']}. Frozen prompts, procedures, interfaces, and "
                "matrix match, but a same-revision replication is preferable before publication."
            )
    if mismatches:
        raise ValueError("incompatible runs:\n- " + "\n- ".join(mismatches))
    return {
        "compatible": True,
        "exact_match_fields": list(_EXACT_MANIFEST_FIELDS),
        "evaluation_harness_source_hash": reference["metrics"].get(
            "evaluation_harness_source_hash"
        ),
        "warnings": warnings,
        "execution_model_is_only_intended_model_variable": True,
    }


def _cross_model_condition_deltas(
    baseline: dict[str, Any], comparison: dict[str, Any], *, samples: int, seed: int
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for architecture in PERSISTENCE_ARCHITECTURES:
        out[architecture] = {}
        for outcome in PERSISTENCE_OUTCOMES:
            result = _paired_delta(
                _condition_map(baseline["scores"], architecture, outcome),
                _condition_map(comparison["scores"], architecture, outcome),
                samples=samples,
                seed=seed,
            )
            result.update(
                {
                    "baseline_model": baseline["model_id"],
                    "comparison_model": comparison["model_id"],
                    "outcome": outcome,
                    "orientation": "comparison_model_minus_baseline_model",
                }
            )
            out[architecture][outcome] = result
    return out


def _difference_in_differences(
    baseline: dict[str, Any], comparison: dict[str, Any], *, samples: int, seed: int
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, architecture_a, architecture_b in PERSISTENCE_BENEFITS:
        out[label] = {}
        for outcome in PERSISTENCE_OUTCOMES:
            baseline_benefit = _benefit_map(
                baseline["scores"], architecture_a, architecture_b, outcome
            )
            comparison_benefit = _benefit_map(
                comparison["scores"], architecture_a, architecture_b, outcome
            )
            keys = _require_same_keys(
                {
                    baseline["model_id"]: baseline_benefit,
                    comparison["model_id"]: comparison_benefit,
                },
                f"cross-model difference in differences for {label}/{outcome}",
            )
            paired = [
                (key[0], baseline_benefit[key], comparison_benefit[key])
                for key in sorted(keys)
            ]
            out[label][outcome] = {
                "condition_a": architecture_a,
                "condition_b": architecture_b,
                "outcome": outcome,
                "baseline_model": baseline["model_id"],
                "comparison_model": comparison["model_id"],
                "estimand": (
                    f"({comparison['model_id']} {architecture_b}-{architecture_a}) - "
                    f"({baseline['model_id']} {architecture_b}-{architecture_a})"
                ),
                "difference_in_differences": cluster_bootstrap_delta(
                    paired, samples=samples, seed=seed
                ).to_dict(),
                "case_level_sign_test": case_level_sign_test(paired),
                "interpretation": (
                    "Positive means the comparison model receives a larger benefit from "
                    f"{architecture_b} relative to {architecture_a}; negative means the "
                    "baseline model receives the larger benefit."
                ),
            }
    return out


def compare_runs(
    run_dirs: list[Path],
    *,
    baseline_model: str | None = None,
    samples: int = 2000,
    seed: int = 104729,
) -> dict[str, Any]:
    """Compare completed, evaluated runs of the same frozen benchmark.

    No provider is called. The primary cross-model persistence result is the
    difference in differences, not a comparison of raw model accuracies alone.
    """
    if len(run_dirs) < 2:
        raise ValueError("cross-model comparison requires at least two run directories")
    if samples < 1:
        raise ValueError("bootstrap samples must be at least 1")
    runs = [_load_run(Path(run_dir)) for run_dir in run_dirs]
    model_ids = [run["model_id"] for run in runs]
    duplicates = sorted(model for model, count in Counter(model_ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"execution model IDs must be unique; duplicates={duplicates}")
    if baseline_model is None:
        baseline_model = runs[0]["model_id"]
    by_model = {run["model_id"]: run for run in runs}
    if baseline_model not in by_model:
        raise ValueError(
            f"baseline model {baseline_model!r} not found; available={sorted(by_model)}"
        )
    compatibility = _check_compatibility(runs)

    per_model: dict[str, dict[str, Any]] = {}
    for run in runs:
        accuracy = _rendering_accuracy(run["scores"])
        h1 = [score for score in run["scores"] if score.get("metadata", {}).get("primary_h1")]
        per_model[run["model_id"]] = {
            "run_id": run["manifest"]["run_id"],
            "run_date": run["manifest"]["created_at"],
            "run_path": str(run["path"]),
            "provider": run["execution_role"].get("provider"),
            "parameters": run["execution_role"].get("parameters") or {},
            "mocked": run["manifest"].get("mocked", False),
            "baseline_eligible": run["summary"].get("baseline_eligible", False),
            "rendering_accuracy": accuracy,
            "rendering_rank": sorted(accuracy, key=lambda key: (-accuracy[key], key)),
            "h1_full_call_accuracy": (
                sum(1 for score in h1 if score["full_call_correct"]) / len(h1)
                if h1
                else None
            ),
            "execution_usage": _execution_usage(run["invocations"]),
            "persistence": _within_model_persistence(
                run["scores"], samples=samples, seed=seed
            ),
        }

    model_names = sorted(per_model)
    correlations = {}
    for index, model_a in enumerate(model_names):
        for model_b in model_names[index + 1 :]:
            correlations[f"{model_a} vs {model_b}"] = _spearman(
                per_model[model_a]["rendering_rank"],
                per_model[model_b]["rendering_rank"],
            )

    pairwise_persistence: dict[str, Any] = {}
    baseline = by_model[baseline_model]
    if per_model[baseline_model]["persistence"] is not None:
        for comparison_model, comparison in by_model.items():
            if comparison_model == baseline_model:
                continue
            if per_model[comparison_model]["persistence"] is None:
                continue
            label = f"{baseline_model} -> {comparison_model}"
            pairwise_persistence[label] = {
                "baseline_model": baseline_model,
                "comparison_model": comparison_model,
                "condition_level_model_deltas": _cross_model_condition_deltas(
                    baseline, comparison, samples=samples, seed=seed
                ),
                "difference_in_differences": _difference_in_differences(
                    baseline, comparison, samples=samples, seed=seed
                ),
            }

    return {
        "benchmark_root_hash": runs[0]["manifest"]["benchmark_root_hash"],
        "matrix_hash": runs[0]["manifest"]["matrix_hash"],
        "baseline_model": baseline_model,
        "bootstrap_samples": samples,
        "bootstrap_seed": seed,
        "compatibility": compatibility,
        "models": per_model,
        "rendering_rank_spearman": correlations,
        "pairwise_persistence": pairwise_persistence,
        "interpretation_notes": [
            "The primary persistence estimand is the cross-model difference in "
            "differences, not the raw accuracy difference between models.",
            "A positive canonical_once difference in differences means canonical-state "
            "persistence helps the comparison model more than it helps the baseline model.",
            "The v0.3.0 persistence replication covers one operation family. It can "
            "replicate a mechanism within that family but cannot establish all-operation "
            "or all-model generality.",
            "Rendering ranks are retained for Experiment 6 compatibility. Same rankings "
            "may reflect shared training distributions; unstable rankings may reflect "
            "model-specific or prompt-local variation.",
        ],
    }
