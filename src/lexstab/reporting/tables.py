"""Flat report tables from metrics.json and scores (spec §44.2, §44.3, §44.5).

Every rate row carries its case-clustered interval and denominator where the
metrics provide one. CSV files land under ``runs/<id>/tables/``; the per-score
``analysis-table.parquet`` supports external hierarchical modeling (D-010).
"""

from __future__ import annotations

import csv
import json
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any


def format_ci(interval: dict[str, Any] | None, digits: int = 2) -> str:
    """Render an Interval dict as ``0.68 [0.55, 0.79]``."""
    if not interval or interval.get("estimate") is None:
        return "n/a"
    estimate = interval["estimate"]
    low = interval.get("ci_low")
    high = interval.get("ci_high")
    if low is None or high is None:
        return f"{estimate:.{digits}f}"
    return f"{estimate:.{digits}f} [{low:.{digits}f}, {high:.{digits}f}]"


def _rate(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _family(score: dict) -> str:
    family = score.get("metadata", {}).get("family_id")
    if family:
        return family
    return score["case_id"].split("_", 1)[0]


# ---------------------------------------------------------------- §44.2 headline


def headline_table(metrics: dict[str, Any]) -> list[dict]:
    rows = []
    for entry in metrics.get("headline", []):
        full = entry.get("full_call_accuracy") or {}
        final = entry.get("final_state_accuracy") or {}
        contrast = entry.get("contrast_accuracy") or {}
        invariance = entry.get("operational_invariance") or {}
        clar = entry.get("clarification") or {}
        rows.append({
            "track": entry["track"],
            "architecture": entry["architecture"],
            "intent_mode": entry.get("intent_mode", "none"),
            "procedure_selection": entry.get("procedure_selection", "none"),
            "procedure_packaging": entry.get("procedure_packaging", "none"),
            "n_cells": entry.get("n_cells"),
            "n_independent_cases": entry.get("n_independent_cases"),
            "n_operation_families": entry.get("n_operation_families"),
            "interpretation_scope": entry.get("interpretation_scope"),
            "full_call": format_ci(full),
            "full_call_estimate": full.get("estimate"),
            "full_call_ci_low": full.get("ci_low"),
            "full_call_ci_high": full.get("ci_high"),
            "full_call_n": full.get("n_observations"),
            "full_call_n_cases": full.get("n_cases"),
            "final_state": format_ci(final),
            "final_state_estimate": final.get("estimate"),
            "final_state_ci_low": final.get("ci_low"),
            "final_state_ci_high": final.get("ci_high"),
            "final_state_n": final.get("n_observations"),
            "invariance": (
                f"{_rate(invariance.get('estimate'))} (n={invariance.get('n_cases', 0)} cases)"
                if invariance.get("estimate") is not None else "n/a"
            ),
            "invariance_estimate": invariance.get("estimate"),
            "invariance_n_cases": invariance.get("n_cases"),
            "contrast": format_ci(contrast),
            "contrast_estimate": contrast.get("estimate"),
            "contrast_ci_low": contrast.get("ci_low"),
            "contrast_ci_high": contrast.get("ci_high"),
            "contrast_n": contrast.get("n_observations"),
            "false_action_rate": entry.get("false_action_rate"),
            "false_action": (
                f"{_rate(entry.get('false_action_rate'))} (n={entry.get('n_cells')})"
                if entry.get("false_action_rate") is not None else "n/a"
            ),
            "clarification_precision": clar.get("precision"),
            "clarification_recall": clar.get("recall"),
            "unnecessary_clarification_rate": clar.get("unnecessary_clarification_rate"),
        })
    return rows


# ---------------------------------------------------------------- §44.3 comparisons


def comparison_table(metrics: dict[str, Any]) -> list[dict]:
    rows = []
    for comparison in metrics.get("primary_comparisons", []):
        delta = comparison.get("delta") or {}
        rows.append({
            "comparison": comparison["comparison"],
            "field": comparison.get("field"),
            "delta": format_ci(delta, digits=3),
            "delta_estimate": delta.get("estimate"),
            "ci_low": delta.get("ci_low"),
            "ci_high": delta.get("ci_high"),
            "margin": comparison.get("margin"),
            "verdict": (
                comparison.get("verdict")
                if comparison.get("interpretation_allowed", True)
                else "withheld: measurement validity gate"
            ),
            "practically_equivalent": comparison.get("practically_equivalent"),
            "n_pairs": comparison.get("n_pairs"),
            "n_cases": comparison.get("n_independent_cases", delta.get("n_cases")),
            "n_operation_families": comparison.get("n_operation_families"),
            "interpretation_scope": comparison.get("interpretation_scope"),
            "mcnemar_p": (comparison.get("secondary_mcnemar") or {}).get("mcnemar_p"),
            "case_b_better": (
                comparison.get("case_level_sign_test") or {}
            ).get("b_better_cases"),
            "case_a_better": (
                comparison.get("case_level_sign_test") or {}
            ).get("a_better_cases"),
            "case_ties": (
                comparison.get("case_level_sign_test") or {}
            ).get("tied_cases"),
            "case_sign_p": (
                comparison.get("case_level_sign_test") or {}
            ).get("sign_p"),
        })
    return rows


def transition_table(metrics: dict[str, Any]) -> list[dict]:
    rows = []
    for transition in metrics.get("formalization_transitions", []):
        quality = transition.get("marginal_quality") or {}
        delta = quality.get("delta") or {}
        safety = transition.get("marginal_safety") or {}
        cost = transition.get("marginal_cost") or {}
        rows.append({
            "transition": transition["transition"],
            "quality_delta": format_ci(delta, digits=3),
            "quality_delta_estimate": delta.get("estimate"),
            "quality_ci_low": delta.get("ci_low"),
            "quality_ci_high": delta.get("ci_high"),
            "verdict": (
                quality.get("verdict")
                if quality.get("interpretation_allowed", True)
                else "withheld: measurement validity gate"
            ),
            "n_pairs": quality.get("n_pairs"),
            "false_action_delta": safety.get("delta"),
            "calls_delta": cost.get("calls_delta"),
            "tokens_delta": cost.get("tokens_delta"),
            "latency_ms_delta": cost.get("latency_ms_delta"),
        })
    return rows


# ---------------------------------------------------------------- §44.5 failure views


def failure_views(metrics: dict[str, Any], scores: list[dict]) -> dict[str, list[dict]]:
    views: dict[str, list[dict]] = {}

    worst = []
    for arch, entry in sorted((metrics.get("robustness") or {}).items()):
        for case_id, info in sorted((entry.get("worst_variants_by_case") or {}).items()):
            worst.append({
                "architecture": arch,
                "case_id": case_id,
                "worst_request_id": info.get("worst_request_id"),
                "worst_variant_accuracy": info.get("worst_variant_accuracy"),
            })
    views["worst_variants_by_case"] = sorted(
        worst, key=lambda row: (row["worst_variant_accuracy"] or 0.0, row["architecture"], row["case_id"])
    )

    adequacy = []
    for cell, entry in sorted((metrics.get("adequacy_matrix") or {}).items()):
        if cell.startswith("_"):
            continue
        adequacy.append({
            "adequacy_cell": cell,
            "n": entry.get("n"),
            "error_rate": entry.get("error_rate"),
            "false_action_rate": entry.get("false_action_rate"),
        })
    views["errors_by_adequacy_cell"] = adequacy

    axis_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for score in scores:
        for axis in score.get("metadata", {}).get("variation_axes") or []:
            axis_totals[axis][1] += 1
            if not score.get("full_call_correct"):
                axis_totals[axis][0] += 1
    views["variation_axis_error_rates"] = sorted(
        (
            {"variation_axis": axis, "n": n, "errors": errors, "error_rate": errors / n}
            for axis, (errors, n) in axis_totals.items() if n
        ),
        key=lambda row: (-row["error_rate"], row["variation_axis"]),
    )

    divergence: dict[tuple[str, str], int] = defaultdict(int)
    for score in scores:
        stage = (
            score.get("metadata", {}).get("first_divergence_stage")
            or (score.get("persistence") or {}).get("first_divergence_stage")
        )
        if stage:
            divergence[(score["architecture"], stage)] += 1
    views["first_divergence_stages"] = [
        {"architecture": arch, "stage": stage, "n": count}
        for (arch, stage), count in sorted(divergence.items())
    ]

    views["clarify_requests_with_action"] = [
        {
            "architecture": score["architecture"],
            "case_id": score["case_id"],
            "request_id": score.get("request_id"),
            "repetition": score.get("repetition"),
            "decision": score.get("decision"),
        }
        for score in sorted(scores, key=lambda s: s["cell_id"])
        if score.get("metadata", {}).get("expected_behavior") == "CLARIFY"
        and score.get("false_action")
    ]

    views["unnecessary_clarifications"] = [
        {
            "architecture": score["architecture"],
            "case_id": score["case_id"],
            "request_id": score.get("request_id"),
            "repetition": score.get("repetition"),
        }
        for score in sorted(scores, key=lambda s: s["cell_id"])
        if score.get("metadata", {}).get("expected_behavior") == "EXECUTE"
        and score.get("clarification_outcome") == "FP"
    ]

    views["interface_and_proposal_errors"] = [
        {
            "architecture": score["architecture"],
            "case_id": score["case_id"],
            "request_id": score.get("request_id"),
            "error_category": score.get("error_category"),
            "interface_errors": "; ".join(score.get("interface_errors") or []),
        }
        for score in sorted(scores, key=lambda s: s["cell_id"])
        if score.get("error_category") or score.get("interface_errors")
    ]

    failures: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for score in scores:
        key = (score["architecture"], score["case_id"])
        failures[key][1] += 1
        if not score.get("full_call_correct"):
            failures[key][0] += 1
    views["failures_by_architecture_case"] = sorted(
        (
            {"architecture": arch, "case_id": case_id, "n": n,
             "failures": errors, "failure_rate": errors / n}
            for (arch, case_id), (errors, n) in failures.items() if errors
        ),
        key=lambda row: (-row["failure_rate"], row["architecture"], row["case_id"]),
    )

    return views


# ---------------------------------------------------------------- writers


def _write_csv(path: Path, rows: list[dict]) -> Path | None:
    if not rows:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _analysis_rows(scores: list[dict]) -> list[dict]:
    rows = []
    for score in scores:
        row = {key: value for key, value in score.items() if _scalar(value)}
        for key, value in (score.get("metadata") or {}).items():
            if isinstance(value, list):
                value = ",".join(str(item) for item in value)
            if _scalar(value):
                row[f"metadata_{key}"] = value
        for key, value in (score.get("usage") or {}).items():
            if _scalar(value):
                row[f"usage_{key}"] = value
        rows.append(row)
    return rows


def _jsonl_to_parquet(rows: list[dict], destination: Path) -> Path | None:
    if not rows:
        return None
    import duckdb

    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    normalized = [{key: row.get(key) for key in keys} for row in rows]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as handle:
        for row in normalized:
            handle.write(json.dumps(row) + "\n")
        temp_path = handle.name
    try:
        source = temp_path.replace("'", "''")
        target = str(destination).replace("'", "''")
        duckdb.sql(
            f"COPY (SELECT * FROM read_json_auto('{source}', sample_size=-1)) "
            f"TO '{target}' (FORMAT PARQUET)"
        )
    finally:
        Path(temp_path).unlink(missing_ok=True)
    return destination


def write_tables(run_dir: Path, metrics: dict[str, Any], scores: list[dict],
                 *, csv_output: bool = True, parquet_output: bool = True) -> list[Path]:
    tables_dir = Path(run_dir) / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    named = {
        "headline": headline_table(metrics),
        "primary-comparisons": comparison_table(metrics),
        "formalization-transitions": transition_table(metrics),
    }
    for view_name, rows in failure_views(metrics, scores).items():
        named[f"failure-{view_name.replace('_', '-')}"] = rows

    if csv_output:
        for name, rows in named.items():
            path = _write_csv(tables_dir / f"{name}.csv", rows)
            if path:
                written.append(path)

    if parquet_output:
        headline_parquet = _jsonl_to_parquet(named["headline"], tables_dir / "headline.parquet")
        if headline_parquet:
            written.append(headline_parquet)
        analysis_parquet = _jsonl_to_parquet(
            _analysis_rows(scores), tables_dir / "analysis-table.parquet"
        )
        if analysis_parquet:
            written.append(analysis_parquet)
        scores_jsonl = Path(run_dir) / "scores.jsonl"
        if scores_jsonl.exists():
            import duckdb

            source = str(scores_jsonl).replace("'", "''")
            target = str(tables_dir / "scores.parquet").replace("'", "''")
            duckdb.sql(
                f"COPY (SELECT * FROM read_json_auto('{source}', sample_size=-1)) "
                f"TO '{target}' (FORMAT PARQUET)"
            )
            written.append(tables_dir / "scores.parquet")
    return written
