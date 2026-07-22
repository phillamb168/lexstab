"""Provider-free composition of a broad run with a whole-track repair run.

Source runs remain immutable. The composite contains one result source for
every matrix cell and records enough provenance to audit the substitution.
"""

from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
from typing import Any

from lexstab.artifacts import (
    json_read,
    json_write,
    jsonl_read,
    jsonl_write,
    make_read_only,
)
from lexstab.hashing import hash_file
from lexstab.run import summarize_run_health


class CompositionError(Exception):
    pass


CELL_ARTIFACTS = (
    "cell-results.jsonl",
    "invocations.jsonl",
    "representation-ledger.jsonl",
    "simulator-events.jsonl",
    "procedure-events.jsonl",
    "interface-events.jsonl",
)


def _rows(path: Path) -> list[dict[str, Any]]:
    return jsonl_read(path) if path.exists() else []


def _validate_role_compatibility(
    base_roles: dict[str, Any], replacement_roles: dict[str, Any]
) -> dict[str, Any]:
    if set(base_roles) != set(replacement_roles):
        raise CompositionError("source runs resolve different model-role sets")
    differences: dict[str, Any] = {}
    for role_name in sorted(base_roles):
        base = base_roles[role_name]
        replacement = replacement_roles[role_name]
        for field in ("provider", "model_id", "enabled", "baseline_eligible"):
            if base.get(field) != replacement.get(field):
                raise CompositionError(
                    f"role {role_name} differs in {field}: "
                    f"{base.get(field)!r} != {replacement.get(field)!r}"
                )
        base_parameters = base.get("parameters") or {}
        replacement_parameters = replacement.get("parameters") or {}
        changed = {
            key: {
                "base": base_parameters.get(key),
                "replacement": replacement_parameters.get(key),
            }
            for key in sorted(set(base_parameters) | set(replacement_parameters))
            if base_parameters.get(key) != replacement_parameters.get(key)
        }
        unsupported = set(changed) - {"max_tokens"}
        if unsupported:
            raise CompositionError(
                f"role {role_name} changes unsupported parameters: "
                f"{sorted(unsupported)}"
            )
        if "max_tokens" in changed:
            old = changed["max_tokens"]["base"]
            new = changed["max_tokens"]["replacement"]
            if old is None or new is None or int(new) < int(old):
                raise CompositionError(
                    f"role {role_name} repair must only increase max_tokens"
                )
            differences[role_name] = changed
    return differences


def _validate_manifests(
    base: dict[str, Any], replacement: dict[str, Any]
) -> dict[str, Any]:
    exact_fields = (
        "benchmark_manifest_path",
        "benchmark_root_hash",
        "code_revision",
        "lockfile_hash",
        "prompt_hashes",
        "procedure_hashes",
        "interface_hashes",
        "run_clock",
        "matrix_seed",
    )
    for field in exact_fields:
        if base.get(field) != replacement.get(field):
            raise CompositionError(f"source run manifests differ in {field}")
    return _validate_role_compatibility(
        base.get("resolved_roles") or {}, replacement.get("resolved_roles") or {}
    )


def compose_track_repair(
    base_run_dir: Path,
    replacement_run_dir: Path,
    output_run_dir: Path,
    *,
    tracks: set[str],
) -> Path:
    """Create a new run by replacing complete tracks from a healthy repair run."""
    if not tracks:
        raise CompositionError("at least one replacement track is required")
    if output_run_dir.exists():
        raise CompositionError(f"output run already exists: {output_run_dir}")

    base_manifest = json_read(base_run_dir / "run-manifest.json")
    replacement_manifest = json_read(replacement_run_dir / "run-manifest.json")
    parameter_differences = _validate_manifests(base_manifest, replacement_manifest)

    replacement_summary = json_read(replacement_run_dir / "run-summary.json")
    if not replacement_summary.get("healthy"):
        raise CompositionError("replacement run is not healthy")

    base_matrix = _rows(base_run_dir / "matrix.jsonl")
    replacement_matrix = _rows(replacement_run_dir / "matrix.jsonl")
    base_by_cell = {row["cell_id"]: row for row in base_matrix}
    expected_replacement = {
        cell_id: row
        for cell_id, row in base_by_cell.items()
        if row.get("track") in tracks
    }
    actual_replacement = {row["cell_id"]: row for row in replacement_matrix}
    if not actual_replacement:
        raise CompositionError("replacement run contains no matrix cells")
    foreign_tracks = {
        row.get("track") for row in replacement_matrix if row.get("track") not in tracks
    }
    if foreign_tracks:
        raise CompositionError(
            f"replacement run contains unrequested tracks: {sorted(foreign_tracks)}"
        )
    if actual_replacement != expected_replacement:
        missing = sorted(set(expected_replacement) - set(actual_replacement))
        extra = sorted(set(actual_replacement) - set(expected_replacement))
        changed = sorted(
            cell_id
            for cell_id in set(actual_replacement) & set(expected_replacement)
            if actual_replacement[cell_id] != expected_replacement[cell_id]
        )
        raise CompositionError(
            "replacement matrix is not the exact whole-track subset of the base matrix; "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    replacement_cell_ids = set(actual_replacement)

    output_run_dir.mkdir(parents=True, exist_ok=False)
    jsonl_write(output_run_dir / "matrix.jsonl", base_matrix)
    skipped_path = base_run_dir / "matrix-skipped.jsonl"
    if skipped_path.exists():
        jsonl_write(output_run_dir / "matrix-skipped.jsonl", jsonl_read(skipped_path))

    artifact_counts: dict[str, dict[str, int]] = {}
    for filename in CELL_ARTIFACTS:
        base_rows = _rows(base_run_dir / filename)
        replacement_rows = _rows(replacement_run_dir / filename)
        kept = [row for row in base_rows if row.get("cell_id") not in replacement_cell_ids]
        inserted = [
            row for row in replacement_rows if row.get("cell_id") in replacement_cell_ids
        ]
        if filename == "cell-results.jsonl":
            inserted_cells = {row.get("cell_id") for row in inserted}
            if inserted_cells != replacement_cell_ids:
                raise CompositionError(
                    "replacement run does not contain exactly one result source for every "
                    "replacement matrix cell"
                )
            final_cells = [row.get("cell_id") for row in [*kept, *inserted]]
            if len(final_cells) != len(base_matrix) or len(set(final_cells)) != len(base_matrix):
                raise CompositionError("composite cell results are incomplete or duplicated")
        if kept or inserted or (base_run_dir / filename).exists():
            jsonl_write(output_run_dir / filename, [*kept, *inserted])
        artifact_counts[filename] = {
            "reused_rows": len(kept),
            "replacement_rows": len(inserted),
            "total_rows": len(kept) + len(inserted),
        }

    composed_results = _rows(output_run_dir / "cell-results.jsonl")
    composed_invocations = _rows(output_run_dir / "invocations.jsonl")
    configured_eligible = bool(
        base_manifest.get("baseline_eligible")
        and replacement_summary.get("configured_baseline_eligible", True)
    )
    health = summarize_run_health(
        composed_results,
        configured_baseline_eligible=configured_eligible,
        invocations=composed_invocations,
    )
    if not health["healthy"]:
        raise CompositionError(
            f"composed run is not healthy after substitution: {health['status']}"
        )

    created_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hashed_source_artifacts = (
        "run-manifest.json",
        "run-summary.json",
        "matrix.jsonl",
        "matrix-skipped.jsonl",
        *CELL_ARTIFACTS,
    )
    source_hashes = {
        source_name: {
            filename: hash_file(source_dir / filename)
            for filename in hashed_source_artifacts
            if (source_dir / filename).exists()
        }
        for source_name, source_dir in (
            ("base", base_run_dir), ("replacement", replacement_run_dir)
        )
    }
    provenance = {
        "schema_version": "track-repair.v1",
        "created_at": created_at,
        "output_run_id": output_run_dir.name,
        "base_run_id": base_manifest["run_id"],
        "replacement_run_id": replacement_manifest["run_id"],
        "replaced_tracks": sorted(tracks),
        "reused_matrix_cells": len(base_matrix) - len(replacement_cell_ids),
        "replacement_matrix_cells": len(replacement_cell_ids),
        "replacement_cell_ids": sorted(replacement_cell_ids),
        "parameter_differences": parameter_differences,
        "artifact_counts": artifact_counts,
        "source_artifact_hashes": source_hashes,
        "interpretation": (
            "The complete named track comes from the healthy replacement run. All other "
            "cells come from the base run. No failed source invocation is retained in the "
            "composite, and neither source run is modified."
        ),
    }
    json_write(output_run_dir / "composition-provenance.json", provenance)

    composite_manifest = copy.deepcopy(base_manifest)
    composite_manifest["run_id"] = output_run_dir.name
    composite_manifest["run_name"] = f"{base_manifest.get('run_name', 'run')}-track-repair"
    composite_manifest["created_at"] = created_at
    composite_manifest["baseline_eligible"] = health["baseline_eligible"]
    overrides = dict(composite_manifest.get("research_overrides") or {})
    overrides["composition"] = {
        "schema_version": provenance["schema_version"],
        "base_run_id": provenance["base_run_id"],
        "replacement_run_id": provenance["replacement_run_id"],
        "replaced_tracks": provenance["replaced_tracks"],
        "parameter_differences": parameter_differences,
        "provenance_path": "composition-provenance.json",
        "provenance_hash": hash_file(output_run_dir / "composition-provenance.json"),
    }
    composite_manifest["research_overrides"] = overrides
    json_write(output_run_dir / "run-manifest.json", composite_manifest)
    make_read_only(output_run_dir / "run-manifest.json")
    json_write(output_run_dir / "run-summary.json", {
        "run_id": output_run_dir.name,
        "cells_executed": len(base_matrix),
        "mocked": bool(base_manifest.get("mocked") or replacement_manifest.get("mocked")),
        "composite": True,
        "source_runs": [base_manifest["run_id"], replacement_manifest["run_id"]],
        **health,
    })
    return output_run_dir
