"""Evaluation orchestration (spec §18.3): score stored runs, no MUT access.

``evaluate_run`` reads only stored artifacts plus the frozen benchmark, writes
``scores.jsonl`` and ``metrics.json``, and never invokes an execution model.
The optional LLM judge route is separate, gated, and blinded.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from lexstab.artifacts import json_read, json_write, jsonl_read, jsonl_write
from lexstab.evaluators.deterministic import score_cell
from lexstab.freeze import FrozenBenchmark
from lexstab.metrics import aggregate
from lexstab.metrics.statistics import benjamini_hochberg


class EvaluationError(Exception):
    pass


def evaluate_run(
    root: Path,
    run_dir: Path,
    *,
    bootstrap_samples: int | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    manifest = json_read(run_dir / "run-manifest.json")
    bench = FrozenBenchmark(root, root / manifest["benchmark_manifest_path"])
    if bench.manifest.artifact_root_hash != manifest["benchmark_root_hash"]:
        raise EvaluationError(
            "benchmark root hash mismatch between run manifest and current artifacts"
        )
    results = jsonl_read(run_dir / "cell-results.jsonl")
    ledger_by_cell: dict[str, list[dict]] = defaultdict(list)
    ledger_path = run_dir / "representation-ledger.jsonl"
    if ledger_path.exists():
        for row in jsonl_read(ledger_path):
            ledger_by_cell[row["cell_id"]].append(row)
    invocations_by_cell: dict[str, list[dict]] = defaultdict(list)
    invocations_path = run_dir / "invocations.jsonl"
    if invocations_path.exists():
        for row in jsonl_read(invocations_path):
            invocations_by_cell[row["cell_id"]].append(row)

    event_files = {
        "simulator_events": "simulator-events.jsonl",
        "procedure_events": "procedure-events.jsonl",
        "interface_events": "interface-events.jsonl",
    }
    events_by_kind: dict[str, dict[str, list[dict]]] = {}
    for result_key, filename in event_files.items():
        grouped: dict[str, list[dict]] = defaultdict(list)
        path = run_dir / filename
        if path.exists():
            for row in jsonl_read(path):
                grouped[row["cell_id"]].append(
                    {key: value for key, value in row.items() if key != "cell_id"}
                )
        events_by_kind[result_key] = grouped

    scores = []
    for result in results:
        enriched_result = dict(result)
        for result_key in event_files:
            enriched_result[result_key] = events_by_kind[result_key].get(
                result["cell_id"], []
            )
        record = score_cell(
            bench,
            enriched_result,
            ledger_by_cell.get(result["cell_id"], []),
            manifest,
            invocations_by_cell.get(result["cell_id"], []),
        )
        scores.append(record.model_dump())
    jsonl_write(run_dir / "scores.jsonl", scores)

    evaluation_config = manifest.get("evaluation") or {}
    samples = bootstrap_samples or int(evaluation_config.get("bootstrap_samples", 2000))
    boot_seed = seed if seed is not None else manifest.get("matrix_seed", 104729)
    confidence = float(evaluation_config.get("confidence_level", 0.95))
    if not 0.0 < confidence < 1.0:
        raise EvaluationError("evaluation.confidence_level must be between 0 and 1")
    equivalence = {
        "success_margin": 0.01,
        "final_state_margin": 0.01,
        "operational_invariance_margin": 0.02,
        "false_action_margin": 0.0,
        **(evaluation_config.get("practical_equivalence") or {}),
    }
    comparison_method = evaluation_config.get(
        "multiple_comparison_method", "benjamini-hochberg"
    )
    if comparison_method != "benjamini-hochberg":
        raise EvaluationError(
            f"unsupported multiple-comparison method: {comparison_method}"
        )

    # Missing-cell reporting (§39.11): matrix cells with no result never vanish.
    matrix_rows = jsonl_read(run_dir / "matrix.jsonl") if (run_dir / "matrix.jsonl").exists() else []
    scored_cells = {score["cell_id"] for score in scores}
    missing_cells = [row["cell_id"] for row in matrix_rows if row["cell_id"] not in scored_cells]

    exploratory_p = {}
    for comparison in aggregate.primary_comparisons(
        scores, equivalence, samples=samples, seed=boot_seed, confidence=confidence
    ):
        p = (comparison.get("secondary_mcnemar") or {}).get("mcnemar_p")
        if p is not None:
            exploratory_p[comparison["comparison"]] = p

    metrics: dict[str, Any] = {
        "run_id": manifest["run_id"],
        "benchmark_root_hash": manifest["benchmark_root_hash"],
        "mocked": manifest.get("mocked", False),
        "baseline_eligible": manifest.get("baseline_eligible", False),
        "bootstrap_samples": samples,
        "bootstrap_seed": boot_seed,
        "confidence_level": confidence,
        "headline": aggregate.headline_metrics(
            scores, samples=samples, seed=boot_seed, confidence=confidence
        ),
        "robustness": aggregate.robustness_metrics(scores),
        "adequacy_matrix": aggregate.adequacy_matrix_metrics(
            [s for s in scores if s.get("request_id")]
        ),
        "primary_comparisons": aggregate.primary_comparisons(
            scores, equivalence, samples=samples, seed=boot_seed, confidence=confidence
        ),
        "formalization_transitions": aggregate.formalization_transitions(
            scores, samples=samples, seed=boot_seed,
            margin=float(equivalence.get("final_state_margin", 0.02)),
            confidence=confidence,
        ),
        "component_ablations": aggregate.component_ablations(
            scores, samples=samples, seed=boot_seed,
            margin=float(equivalence.get("final_state_margin", 0.02)),
            confidence=confidence,
        ),
        "persistence": aggregate.persistence_metrics(scores),
        "elicitation": aggregate.elicitation_metrics(
            scores, samples=samples, seed=boot_seed, confidence=confidence
        ),
        "adequacy_assessment": aggregate.adequacy_assessment_metrics(
            scores, samples=samples, seed=boot_seed, confidence=confidence
        ),
        "procedure_selection": aggregate.procedure_selection_metrics(
            scores, samples=samples, seed=boot_seed, confidence=confidence
        ),
        "typed_interface": aggregate.typed_interface_metrics(
            scores, samples=samples, seed=boot_seed, confidence=confidence
        ),
        "complexity": aggregate.complexity_bill_of_materials(scores),
        "exploratory_fdr": benjamini_hochberg(exploratory_p),
        "missing_cells": missing_cells,
        "completion": {
            "matrix_cells": len(matrix_rows),
            "scored_cells": len(scored_cells),
            "completion_rate": len(scored_cells) / len(matrix_rows) if matrix_rows else None,
        },
        "analysis_labels": {
            "primary": [
                "headline", "primary_comparisons", "formalization_transitions",
                "component_ablations",
            ],
            "secondary": [
                "robustness", "persistence", "elicitation", "adequacy_matrix",
                "adequacy_assessment", "procedure_selection", "typed_interface",
            ],
            "exploratory": ["exploratory_fdr"],
        },
    }
    json_write(run_dir / "metrics.json", metrics)
    if (manifest.get("tracing") or {}).get("langsmith"):
        from lexstab.tracing.langsmith import export_run

        json_write(run_dir / "langsmith-export.json", export_run(run_dir))
    return metrics
