"""Run orchestration: manifest, execution, local JSONL traces (§21.2, §23.1).

The primary benchmark command only consumes frozen artifacts; it never invokes
authoring (§G7). Response caching is not implemented: every invocation is a
fresh provider call, so repetitions trivially bypass caches (§20.3, §49.6).
"""

from __future__ import annotations

import concurrent.futures
import datetime as _dt
import os
import platform
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from lexstab import models
from lexstab.artifacts import ArtifactError, json_read, json_write, jsonl_append, jsonl_write, make_read_only
from lexstab.config import (
    ModelsConfig,
    RunConfig,
    load_models_config,
    load_run_config,
    validate_role_separation,
)
from lexstab.freeze import FrozenBenchmark
from lexstab.hashing import hash_file, sha256_text
from lexstab.matrix import Matrix, MatrixCell, expand_matrix
from lexstab.prompts import PromptLibrary
from lexstab.providers.registry import adapter_versions, build_provider
from lexstab.runner import CellResult, RunContext, run_cell

INVOCATIONS_PER_ARCH = {
    "A0_DIRECT": 1, "A1_DIRECT_CLARIFY": 1, "B_RUNTIME": 2, "C_RUNTIME": 2,
    "B_GOLD": 1, "C_GOLD": 1, "D_DEFINITION_ONLY": 1, "E_ORGANIZATION_TERM": 1,
    "B_EXTERNAL_GATE": 6, "B_EXTERNAL_GATE_GOLD": 5, "HUMAN_ORACLE": 2,
    "M0_NO_MEMORY": 1, "M1_STATIC_GLOSSARY": 1, "M2_RETRIEVED_MEMORY": 1,
    "M3_CANONICAL_RESOLVER": 2, "M4_PERSONALIZED_MEMORY": 1,
    "P0_RAW_PROPOSAL": 1, "P1_CLARIFY_PROPOSAL": 1, "P2_CANONICAL_PROPOSAL": 2,
    "P3_CANONICAL_PROCEDURE_PROPOSAL": 2, "P4_CANONICAL_PROCEDURE_TOOL": 2,
    "LP0_LANGUAGE_THROUGHOUT": 7, "LP0G_GOLD_START_LANGUAGE": 7,
    "LP1_CANONICAL_ONCE": 5, "LP2_CANONICAL_PROCEDURE": 5, "LP3_CANONICAL_PROCEDURE_TOOL": 5,
    "AL_RAW": 4, "AL_CANONICAL": 4, "AL_RENDERED": 4, "AL_DRIFT": 6,
}

DEFAULT_COST_PER_CALL_USD = 0.01  # dry-run planning placeholder; real costs come from providers


class RunError(Exception):
    pass


def _git_revision(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def build_run_context(
    root: Path,
    run_config: RunConfig,
    *,
    run_id: str | None = None,
    mock_script: dict[str, Any] | None = None,
) -> tuple[RunContext, Matrix, ModelsConfig]:
    bench = FrozenBenchmark(root, root / run_config.benchmark_manifest)
    models_config = load_models_config(root / run_config.model_config_path, strict_env=False)
    violations = validate_role_separation(models_config)
    if violations and not models_config.separation_policy.allow_role_overlap:
        raise RunError("role separation policy violated:\n" + "\n".join(violations))

    prompts = PromptLibrary(root / "prompts")
    prompt_errors = prompts.validate_all()
    if prompt_errors:
        raise RunError("prompt validation failed:\n" + "\n".join(prompt_errors))
    # Verify the prompts pinned by the manifest have not changed (§16, §40).
    for _role_name, prompt_id in bench.manifest.prompt_versions.items():
        recorded = bench.manifest.prompt_hashes.get(prompt_id)
        if recorded and prompts.get(prompt_id).content_hash != recorded:
            raise RunError(
                f"prompt {prompt_id} hash differs from the frozen benchmark manifest; "
                "freeze a new benchmark version"
            )

    providers = {}
    needed_roles = {"execution_primary", "boundary_canonicalizer", "adequacy_assessor", "procedure_router"}
    for role_name in needed_roles:
        role = models_config.roles.get(role_name)
        if role and role.enabled:
            providers[role_name] = build_provider(role, mock_script=mock_script)

    matrix = expand_matrix(bench, run_config)
    ctx = RunContext(
        root=root,
        bench=bench,
        prompts=prompts,
        models_config=models_config,
        providers=providers,
        run_id=run_id or f"run-{uuid.uuid4().hex[:12]}",
        run_clock=run_config.run_clock,
        mocked=all(
            models_config.roles[name].provider == "mock"
            for name in providers
            if name in models_config.roles
        ),
    )
    return ctx, matrix, models_config


def write_run_manifest(
    root: Path,
    ctx: RunContext,
    matrix: Matrix,
    run_config: RunConfig,
    models_config: ModelsConfig,
    run_dir: Path,
) -> models.RunManifest:
    execution_role = models_config.roles.get("execution_primary")
    resolved_roles = {
        name: {
            "provider": role.provider,
            "model_id": role.model_id,
            "parameters": role.parameters,
            "enabled": role.enabled,
            "baseline_eligible": role.baseline_eligible,
        }
        for name, role in models_config.roles.items()
    }
    lockfile = root / "uv.lock"
    plan_path = root / "docs" / "ANALYSIS_PLAN.md"
    analysis_plan_hash = hash_file(plan_path) if plan_path.exists() else None
    formal = run_config.tracks.get("progressive_formalization", {})
    manifest = models.RunManifest(
        run_id=ctx.run_id,
        run_name=run_config.run_name,
        created_at=_dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        benchmark_manifest_path=run_config.benchmark_manifest,
        benchmark_root_hash=ctx.bench.manifest.artifact_root_hash,
        code_revision=_git_revision(root),
        lockfile_hash=hash_file(lockfile) if lockfile.exists() else None,
        resolved_roles=resolved_roles,
        prompt_hashes=ctx.prompts.hashes(),
        procedure_hashes={
            procedure_id: sha256_text(procedure.model_dump_json())
            for procedure_id, procedure in sorted(ctx.bench.procedures.items())
        },
        interface_hashes={
            interface_id: sha256_text(interface.model_dump_json())
            for interface_id, interface in sorted(ctx.bench.interfaces.items())
        },
        provider_adapter_versions=adapter_versions(),
        run_clock=run_config.run_clock,
        matrix_seed=run_config.random_seed,
        matrix_cell_count=len(matrix.cells),
        matrix_hash=matrix.matrix_hash,
        tracks=run_config.tracks,
        formalization_conditions=formal.get("conditions", []),
        persistence_conditions=formal.get("persistence_conditions", []),
        repetitions=run_config.repetitions,
        concurrency=int(run_config.execution.get("concurrency", 1)),
        tracing=run_config.tracing,
        environment={
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "timezone": _dt.datetime.now().astimezone().tzname() or "unknown",
        },
        research_overrides=(
            {"allow_role_overlap": True}
            if models_config.separation_policy.allow_role_overlap
            else {}
        ),
        analysis_plan_hash=analysis_plan_hash,
        baseline_eligible=bool(execution_role and execution_role.baseline_eligible and not ctx.mocked),
        mocked=ctx.mocked,
    )
    path = run_dir / "run-manifest.json"
    json_write(path, manifest.model_dump())
    make_read_only(path)  # immutable after first model invocation (§21.2)
    return manifest


def dry_run_report(matrix: Matrix, run_config: RunConfig) -> dict[str, Any]:
    by_track: dict[str, int] = {}
    call_estimate = 0
    for cell in matrix.cells:
        by_track[cell.track] = by_track.get(cell.track, 0) + 1
        call_estimate += INVOCATIONS_PER_ARCH.get(cell.architecture, 2)
    return {
        "matrix_cells": len(matrix.cells),
        "cells_by_track": by_track,
        "estimated_model_calls": call_estimate,
        "estimated_cost_usd_at_placeholder_rate": round(call_estimate * DEFAULT_COST_PER_CALL_USD, 2),
        "skipped_combinations": matrix.skipped,
        "matrix_hash": matrix.matrix_hash,
        "repetitions": run_config.repetitions,
    }


def _write_result(run_dir: Path, result: CellResult) -> None:
    jsonl_append(run_dir / "cell-results.jsonl", result.summary())
    for record in result.invocations:
        jsonl_append(run_dir / "invocations.jsonl", record.model_dump())
    for ledger_record in result.ledger:
        jsonl_append(run_dir / "representation-ledger.jsonl", ledger_record.model_dump())
    for event in result.simulator_events:
        jsonl_append(run_dir / "simulator-events.jsonl", {"cell_id": result.cell.cell_id, **event})
    for event in result.procedure_events:
        jsonl_append(run_dir / "procedure-events.jsonl", {"cell_id": result.cell.cell_id, **event})
    for event in result.interface_events:
        jsonl_append(run_dir / "interface-events.jsonl", {"cell_id": result.cell.cell_id, **event})


def execute_run(
    root: Path,
    run_config: RunConfig,
    *,
    runs_dir: Path | None = None,
    run_id: str | None = None,
    mock_script: dict[str, Any] | None = None,
    cell_runner: Callable[[RunContext, MatrixCell], CellResult] = run_cell,
    progress: Callable[[str], None] | None = None,
) -> Path:
    ctx, matrix, models_config = build_run_context(root, run_config, run_id=run_id, mock_script=mock_script)
    # Held-out seal (§39.12, §49.10): the test split requires a frozen analysis plan.
    if run_config.selection.get("split") == "test" and not (root / "docs" / "ANALYSIS_PLAN.md").exists():
        raise RunError(
            "the held-out test split is sealed: freeze docs/ANALYSIS_PLAN.md before "
            "running it (spec §39.12)"
        )
    runs_dir = runs_dir or (root / "runs")
    run_dir = runs_dir / ctx.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    write_run_manifest(root, ctx, matrix, run_config, models_config, run_dir)
    jsonl_write(run_dir / "matrix.jsonl", [cell.to_dict() for cell in matrix.cells])
    if matrix.skipped:
        jsonl_write(run_dir / "matrix-skipped.jsonl", matrix.skipped)

    ordered = matrix.ordered(
        bool(run_config.execution.get("randomize_matrix_order", True)), run_config.random_seed
    )
    concurrency = int(run_config.execution.get("concurrency", 1))

    def _run_one(cell: MatrixCell) -> CellResult:
        try:
            return cell_runner(ctx, cell)
        except Exception as exc:  # never drop failed cells silently (§39.11)
            failed = CellResult(cell=cell)
            failed.schema_valid = False
            failed.error_category = f"harness_error: {type(exc).__name__}: {exc}"
            return failed

    if concurrency <= 1:
        results = []
        for index, cell in enumerate(ordered):
            result = _run_one(cell)
            _write_result(run_dir, result)
            results.append(result)
            if progress and (index + 1) % 25 == 0:
                progress(f"{index + 1}/{len(ordered)} cells")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            for result in pool.map(_run_one, ordered):
                _write_result(run_dir, result)

    json_write(run_dir / "run-summary.json", {
        "run_id": ctx.run_id,
        "cells_executed": len(ordered),
        "mocked": ctx.mocked,
    })
    return run_dir


def load_run(run_dir: Path) -> dict[str, Any]:
    """Load stored run artifacts for evaluation (no provider access needed)."""
    from lexstab.artifacts import jsonl_read

    manifest = json_read(run_dir / "run-manifest.json")
    results_path = run_dir / "cell-results.jsonl"
    results = jsonl_read(results_path) if results_path.exists() else []
    ledger_path = run_dir / "representation-ledger.jsonl"
    ledger = jsonl_read(ledger_path) if ledger_path.exists() else []
    invocations_path = run_dir / "invocations.jsonl"
    invocations = jsonl_read(invocations_path) if invocations_path.exists() else []
    return {
        "manifest": manifest,
        "results": results,
        "ledger": ledger,
        "invocations": invocations,
        "run_dir": str(run_dir),
    }
