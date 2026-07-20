"""Regression suite promotion (spec §17.3, §45.5).

Human-approved red-team failures are promoted into a versioned regression
suite with provenance links to the discovering run. Promotion always creates a
new suite version; the full frozen benchmark is never replaced.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from lexstab import models
from lexstab.artifacts import ArtifactError, json_read, json_write, jsonl_read, make_read_only
from lexstab.hashing import hash_json_artifact


class RegressionError(Exception):
    pass


def promote_to_regression(
    root: Path,
    *,
    version: str,
    request_ids: list[str],
    candidate_corpus: Path,
    discovering_run_id: str,
    reason: str,
    approved_by: str,
    base_benchmark_manifest: str,
) -> Path:
    suite_path = root / "dataset" / "manifests" / f"regression-v{version}.json"
    if suite_path.exists():
        raise RegressionError(
            f"regression suite version {version} already exists; promotion creates a "
            "new version (§45.5)"
        )
    corpus = {row["request_id"]: row for row in jsonl_read(candidate_corpus)}
    promoted = []
    for request_id in request_ids:
        row = corpus.get(request_id)
        if row is None:
            raise RegressionError(f"request {request_id} not found in {candidate_corpus}")
        status = row.get("validation", {}).get("status")
        approving = [
            review for review in row.get("validation", {}).get("reviewers", [])
            if review.get("decision") in ("APPROVE", "EDIT_AND_APPROVE")
        ]
        if status not in ("APPROVED", "FROZEN") or not approving:
            raise RegressionError(
                f"request {request_id} is not human-approved (status={status}); "
                "only validated failures may be promoted (§45.5)"
            )
        models.NLRequest.model_validate(row)
        promoted.append(row)
    suite = {
        "schema_version": models.SCHEMA_VERSION,
        "suite_id": "lexstab-support-regression",
        "suite_version": version,
        "created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_benchmark_manifest": base_benchmark_manifest,
        "promotion": {
            "discovering_run_id": discovering_run_id,
            "reason": reason,
            "approved_by": approved_by,
            "source_corpus": str(candidate_corpus),
        },
        "request_ids": request_ids,
        "requests": promoted,
        "request_hashes": {row["request_id"]: hash_json_artifact(row) for row in promoted},
        "recommended_repetitions": 3,
    }
    json_write(suite_path, suite)
    make_read_only(suite_path)
    return suite_path


def load_regression_suite(root: Path, version: str) -> dict[str, Any]:
    path = root / "dataset" / "manifests" / f"regression-v{version}.json"
    suite = json_read(path)
    for row in suite["requests"]:
        actual = hash_json_artifact(row)
        expected = suite["request_hashes"][row["request_id"]]
        if actual != expected:
            raise ArtifactError(f"regression request {row['request_id']} hash mismatch")
    return suite


def check_run_thresholds(run_dir: Path, thresholds: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a completed run against configured blocking gates.

    Only gates represented by the selected tracks are applied. Every skipped
    gate is reported explicitly so a narrow scheduled run cannot appear to
    have exercised procedure, elicitation, or interface checks that were not
    in its matrix.
    """
    metrics = json_read(run_dir / "metrics.json")
    manifest = json_read(run_dir / "run-manifest.json")
    failures: list[str] = []
    skipped: list[str] = []
    checks: list[dict[str, Any]] = []
    require_intervals = thresholds.get("blocking", {}).get(
        "require_case_clustered_interval", True
    )

    if manifest.get("mocked") or not manifest.get("baseline_eligible"):
        failures.append("run is mocked or baseline-ineligible")
    completion = metrics.get("completion") or {}
    if thresholds.get("blocking", {}).get("block_on_missing_cells", True):
        if metrics.get("missing_cells") or completion.get("completion_rate") != 1.0:
            failures.append("run contains missing or unscored matrix cells")

    headline = metrics.get("headline") or []
    baseline_arch = thresholds.get("baseline_architecture", "A1_DIRECT_CLARIFY")
    baselines = {
        row.get("track"): row
        for row in headline
        if row.get("architecture") == baseline_arch
    }

    def estimate(row: dict, key: str) -> float | None:
        value = row.get(key)
        if isinstance(value, dict):
            return value.get("estimate")
        return value if isinstance(value, (int, float)) else None

    gates = thresholds.get("gates") or {}
    schema_min = (gates.get("schema_validity") or {}).get("minimum")
    false_action_max = (gates.get("false_action_rate") or {}).get("maximum")
    unnecessary_max = (
        gates.get("unnecessary_clarification_rate") or {}
    ).get("maximum")
    drop_fields = {
        "full_call_accuracy": "full_call_accuracy",
        "final_state_accuracy": "final_state_accuracy",
        "operational_invariance": "operational_invariance",
        "contrast_accuracy": "contrast_accuracy",
    }

    for row in headline:
        label = f"{row.get('track')}:{row.get('architecture')}"
        if schema_min is not None:
            interval = row.get("schema_validity") or {}
            actual = estimate(row, "schema_validity")
            conservative = interval.get("ci_low") if require_intervals else actual
            passed = conservative is not None and conservative >= float(schema_min)
            checks.append({"gate": "schema_validity", "condition": label,
                           "actual": actual, "conservative_value": conservative,
                           "required": schema_min, "passed": passed})
            if not passed:
                failures.append(
                    f"{label} schema-validity lower bound {conservative} is below {schema_min}"
                )
        if false_action_max is not None and row.get("false_action_rate") is not None:
            actual = float(row["false_action_rate"])
            interval = row.get("false_action_interval") or {}
            conservative = interval.get("ci_high") if require_intervals else actual
            passed = conservative is not None and conservative <= float(false_action_max)
            checks.append({"gate": "false_action_rate", "condition": label,
                           "actual": actual, "conservative_value": conservative,
                           "required": false_action_max, "passed": passed})
            if not passed:
                failures.append(
                    f"{label} false-action upper bound {conservative} exceeds {false_action_max}"
                )
        clarification = row.get("clarification") or {}
        if unnecessary_max is not None and clarification.get("unnecessary_clarification_rate") is not None:
            actual = float(clarification["unnecessary_clarification_rate"])
            interval = row.get("unnecessary_clarification_interval") or {}
            conservative = interval.get("ci_high") if require_intervals else actual
            passed = conservative is not None and conservative <= float(unnecessary_max)
            checks.append({"gate": "unnecessary_clarification_rate", "condition": label,
                           "actual": actual, "conservative_value": conservative,
                           "required": unnecessary_max, "passed": passed})
            if not passed:
                failures.append(
                    f"{label} unnecessary-clarification upper bound {conservative} "
                    f"exceeds {unnecessary_max}"
                )
        baseline = baselines.get(row.get("track"))
        if baseline is None or row.get("architecture") == baseline_arch:
            continue
        for gate_name, field in drop_fields.items():
            maximum_drop = (gates.get(gate_name) or {}).get("maximum_drop_from_baseline")
            if maximum_drop is None:
                continue
            baseline_value = estimate(baseline, field)
            actual = estimate(row, field)
            if baseline_value is None or actual is None:
                skipped.append(f"{label} {gate_name}: metric not defined for selected stratum")
                continue
            interval = row.get(field) or {}
            conservative_actual = (
                interval.get("ci_low") if require_intervals else actual
            )
            if conservative_actual is None:
                failures.append(f"{label} {gate_name}: required interval is missing")
                continue
            drop = baseline_value - actual
            conservative_drop = baseline_value - conservative_actual
            passed = conservative_drop <= float(maximum_drop)
            checks.append({"gate": gate_name, "condition": label, "actual": actual,
                           "baseline": baseline_value, "drop": drop,
                           "conservative_drop": conservative_drop,
                           "required": maximum_drop, "passed": passed})
            if not passed:
                failures.append(
                    f"{label} {gate_name} conservative drop {conservative_drop:.6f} "
                    f"exceeds {maximum_drop}"
                )

    specialized_intervals: dict[str, list[tuple[str, dict[str, Any]]]] = {
        "adequacy_accuracy": list((metrics.get("adequacy_assessment") or {}).items()),
        "unresolved_without_action_rate": [
            (architecture, values["unresolved_without_action_interval"])
            for architecture, values in (metrics.get("elicitation") or {}).items()
            if values.get("unresolved_without_action_interval", {}).get("estimate") is not None
        ],
        "procedure_selection_accuracy": list(
            (metrics.get("procedure_selection") or {}).items()
        ),
        "typed_interface_validation_rate": list(
            (metrics.get("typed_interface") or {}).items()
        ),
    }
    for gate_name, values in specialized_intervals.items():
        gate = gates.get(gate_name)
        if not gate:
            continue
        if not values:
            skipped.append(f"{gate_name}: selected tracks do not produce this metric")
            continue
        minimum = gate.get("minimum")
        if minimum is None:
            continue
        for condition, interval in values:
            actual = interval.get("estimate")
            conservative = interval.get("ci_low") if require_intervals else actual
            passed = conservative is not None and conservative >= float(minimum)
            checks.append({"gate": gate_name, "condition": condition,
                           "actual": actual, "conservative_value": conservative,
                           "required": minimum, "passed": passed})
            if not passed:
                failures.append(
                    f"{condition} {gate_name} lower bound {conservative} is below {minimum}"
                )

    report = {
        "run_id": metrics.get("run_id"),
        "passed": not failures,
        "failures": failures,
        "checks": checks,
        "skipped": skipped,
    }
    json_write(run_dir / "threshold-check.json", report)
    return report
