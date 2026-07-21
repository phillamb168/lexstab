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
from lexstab.hashing import hash_file, root_hash
from lexstab.metrics import aggregate
from lexstab.metrics.input_audit import effective_input_audit
from lexstab.metrics.statistics import benjamini_hochberg
from lexstab.run import summarize_run_health


class EvaluationError(Exception):
    pass


def _evaluation_source_hash(root: Path) -> str | None:
    """Content hash the local harness source used for provider-free analysis."""
    source_root = root / "src" / "lexstab"
    if not source_root.exists():
        return None
    inventory = {
        str(path.relative_to(root)): hash_file(path)
        for path in sorted(source_root.rglob("*.py"))
    }
    return root_hash(inventory) if inventory else None


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
    flat_invocations = [
        record
        for records in invocations_by_cell.values()
        for record in records
    ]
    summary_path = run_dir / "run-summary.json"
    stored_summary = json_read(summary_path) if summary_path.exists() else {}
    if "healthy" in stored_summary:
        run_health = {
            key: stored_summary[key]
            for key in (
                "status", "healthy", "configured_baseline_eligible", "baseline_eligible",
                "provider_error_calls", "provider_error_cells", "http_error_calls",
                "transport_error_calls", "length_terminated_calls", "harness_error_cells",
                "aborted_cells",
            )
            if key in stored_summary
        }
    else:
        # Backward-compatible audit for runs created before health summaries
        # became explicit. This correctly disqualifies stored runs containing
        # terminal provider failures even when their manifest said eligible.
        run_health = summarize_run_health(
            results,
            configured_baseline_eligible=bool(manifest.get("baseline_eligible", False)),
            invocations=flat_invocations,
        )

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
    minimum_schema_validity = float(
        evaluation_config.get("minimum_schema_validity_for_interpretation", 0.99)
    )
    minimum_independent_cases = int(
        evaluation_config.get("minimum_independent_cases_for_interpretation", 6)
    )
    minimum_operation_families = int(
        evaluation_config.get("minimum_operation_families_for_generalization", 3)
    )
    if minimum_independent_cases < 1 or minimum_operation_families < 1:
        raise EvaluationError(
            "interpretation and generalization sample thresholds must be positive integers"
        )
    measurement_warnings = aggregate.measurement_warnings(
        scores, minimum_schema_validity=minimum_schema_validity
    )
    primary_comparisons = [
        aggregate.apply_interpretation_gate(
            comparison, measurement_warnings,
            minimum_independent_cases=minimum_independent_cases,
            minimum_operation_families=minimum_operation_families,
        )
        for comparison in aggregate.primary_comparisons(
            scores, equivalence, samples=samples, seed=boot_seed, confidence=confidence
        )
    ]
    formalization_transitions = aggregate.formalization_transitions(
        scores, samples=samples, seed=boot_seed,
        margin=float(equivalence.get("final_state_margin", 0.02)),
        confidence=confidence,
    )
    for transition in formalization_transitions:
        if transition.get("marginal_quality"):
            transition["marginal_quality"] = aggregate.apply_interpretation_gate(
                transition["marginal_quality"], measurement_warnings,
                minimum_independent_cases=minimum_independent_cases,
                minimum_operation_families=minimum_operation_families,
            )
    component_ablations = aggregate.component_ablations(
        scores, samples=samples, seed=boot_seed,
        margin=float(equivalence.get("final_state_margin", 0.02)),
        confidence=confidence,
    )
    for index, comparison in enumerate(component_ablations):
        if comparison.get("pairing_cohorts"):
            component_ablations[index] = aggregate.apply_interpretation_gate(
                comparison, measurement_warnings,
                minimum_independent_cases=minimum_independent_cases,
                minimum_operation_families=minimum_operation_families,
            )
    rendering_contrast = aggregate.rendering_contrast_metrics(
        scores,
        samples=samples,
        seed=boot_seed,
        confidence=confidence,
        margin=float(equivalence.get("success_margin", 0.01)),
    )
    for key in ("all_cases_comparison", "lexically_distinct_comparison"):
        rendering_contrast[key] = aggregate.apply_interpretation_gate(
            rendering_contrast[key], measurement_warnings,
            minimum_independent_cases=minimum_independent_cases,
            minimum_operation_families=minimum_operation_families,
        )

    # Missing-cell reporting (§39.11): matrix cells with no result never vanish.
    matrix_rows = jsonl_read(run_dir / "matrix.jsonl") if (run_dir / "matrix.jsonl").exists() else []
    scored_cells = {score["cell_id"] for score in scores}
    missing_cells = [row["cell_id"] for row in matrix_rows if row["cell_id"] not in scored_cells]
    input_audit = effective_input_audit(scores, invocations_by_cell)

    exploratory_p = {}
    for comparison in primary_comparisons:
        p = (comparison.get("case_level_sign_test") or {}).get("sign_p")
        if p is not None:
            exploratory_p[comparison["comparison"]] = p

    metrics: dict[str, Any] = {
        "run_id": manifest["run_id"],
        "evaluation_harness_source_hash": _evaluation_source_hash(root),
        "benchmark_root_hash": manifest["benchmark_root_hash"],
        "mocked": manifest.get("mocked", False),
        "baseline_eligible": run_health.get("baseline_eligible", False),
        "run_health": run_health,
        "bootstrap_samples": samples,
        "bootstrap_seed": boot_seed,
        "confidence_level": confidence,
        "interpretation_thresholds": {
            "minimum_independent_cases_for_interpretation": minimum_independent_cases,
            "minimum_operation_families_for_generalization": minimum_operation_families,
            "note": (
                "Lexical variants and repetitions do not increase the independent "
                "canonical-case count. These gates are not a power analysis."
            ),
        },
        "headline": aggregate.headline_metrics(
            scores, samples=samples, seed=boot_seed, confidence=confidence,
            minimum_independent_cases=minimum_independent_cases,
            minimum_operation_families=minimum_operation_families,
        ),
        "robustness": aggregate.robustness_metrics(scores),
        "adequacy_matrix": aggregate.adequacy_matrix_metrics(
            [
                s for s in scores
                if s.get("request_id")
                and s.get("metadata", {}).get("intent_mode") != "gold"
            ]
        ),
        "primary_comparisons": primary_comparisons,
        "formalization_transitions": formalization_transitions,
        "component_ablations": component_ablations,
        "persistence": aggregate.persistence_metrics(
            scores,
            minimum_independent_cases=minimum_independent_cases,
            minimum_operation_families=minimum_operation_families,
        ),
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
        "measurement_warnings": measurement_warnings,
        "effective_input_audit": input_audit,
        "rendering_contrast": rendering_contrast,
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
                "effective_input_audit",
            ],
            "exploratory": ["exploratory_fdr"],
        },
    }
    json_write(run_dir / "metrics.json", metrics)
    if (manifest.get("tracing") or {}).get("langsmith"):
        from lexstab.tracing.langsmith import export_run

        json_write(run_dir / "langsmith-export.json", export_run(run_dir))
    return metrics
