"""Provider-free whole-track repair composition tests."""

from pathlib import Path

import pytest

from lexstab.artifacts import json_read, json_write, jsonl_read, jsonl_write
from lexstab.compose import CompositionError, compose_track_repair


def _manifest(run_id: str, *, canonicalizer_tokens: int) -> dict:
    return {
        "run_id": run_id,
        "run_name": "test",
        "created_at": "2026-01-01T00:00:00Z",
        "benchmark_manifest_path": "dataset/manifests/test.json",
        "benchmark_root_hash": "sha256:benchmark",
        "code_revision": "abc123",
        "lockfile_hash": "sha256:lock",
        "prompt_hashes": {"p": "sha256:p"},
        "procedure_hashes": {},
        "interface_hashes": {},
        "run_clock": "2026-01-01T00:00:00Z",
        "matrix_seed": 1,
        "matrix_cell_count": 2,
        "matrix_hash": "sha256:matrix",
        "baseline_eligible": True,
        "mocked": False,
        "research_overrides": {},
        "resolved_roles": {
            "execution_primary": {
                "provider": "anthropic", "model_id": "opus", "enabled": True,
                "baseline_eligible": True, "parameters": {"max_tokens": 1024},
            },
            "boundary_canonicalizer": {
                "provider": "openrouter", "model_id": "gemini", "enabled": True,
                "baseline_eligible": False,
                "parameters": {"temperature": 0.0, "max_tokens": canonicalizer_tokens},
            },
        },
    }


def _write_source(path: Path, *, replacement: bool = False) -> None:
    path.mkdir()
    json_write(path / "run-manifest.json", _manifest(
        "replacement" if replacement else "base",
        canonicalizer_tokens=8192 if replacement else 4096,
    ))
    full_matrix = [
        {"cell_id": "boundary", "track": "boundary", "architecture": "A0"},
        {"cell_id": "intent", "track": "intent_elicitation", "architecture": "B"},
    ]
    matrix = [full_matrix[1]] if replacement else full_matrix
    jsonl_write(path / "matrix.jsonl", matrix)
    if replacement:
        results = [{"cell_id": "intent", "error_category": None}]
        invocations = [{"cell_id": "intent", "finish_reason": "stop"}]
    else:
        results = [
            {"cell_id": "boundary", "error_category": None},
            {"cell_id": "intent", "error_category": "invalid_canonical_resolution"},
        ]
        invocations = [
            {"cell_id": "boundary", "finish_reason": "stop"},
            {"cell_id": "intent", "finish_reason": "length"},
        ]
    jsonl_write(path / "cell-results.jsonl", results)
    jsonl_write(path / "invocations.jsonl", invocations)
    json_write(path / "run-summary.json", {
        "healthy": replacement,
        "configured_baseline_eligible": True,
        "baseline_eligible": replacement,
    })


def test_compose_replaces_complete_track_and_removes_failed_invocation(tmp_path):
    base = tmp_path / "base"
    replacement = tmp_path / "replacement"
    output = tmp_path / "composite"
    _write_source(base)
    _write_source(replacement, replacement=True)

    compose_track_repair(
        base, replacement, output, tracks={"intent_elicitation"}
    )

    results = {row["cell_id"]: row for row in jsonl_read(output / "cell-results.jsonl")}
    assert set(results) == {"boundary", "intent"}
    assert results["intent"]["error_category"] is None
    assert all(
        row["finish_reason"] != "length"
        for row in jsonl_read(output / "invocations.jsonl")
    )
    summary = json_read(output / "run-summary.json")
    assert summary["healthy"] is True
    assert summary["baseline_eligible"] is True
    provenance = json_read(output / "composition-provenance.json")
    assert provenance["reused_matrix_cells"] == 1
    assert provenance["replacement_matrix_cells"] == 1
    assert provenance["parameter_differences"] == {
        "boundary_canonicalizer": {
            "max_tokens": {"base": 4096, "replacement": 8192}
        }
    }


def test_compose_rejects_partial_track_replacement(tmp_path):
    base = tmp_path / "base"
    replacement = tmp_path / "replacement"
    output = tmp_path / "composite"
    _write_source(base)
    _write_source(replacement, replacement=True)
    jsonl_write(replacement / "matrix.jsonl", [])

    with pytest.raises(CompositionError, match="no matrix cells"):
        compose_track_repair(
            base, replacement, output, tracks={"intent_elicitation"}
        )


def test_compose_rejects_model_change(tmp_path):
    base = tmp_path / "base"
    replacement = tmp_path / "replacement"
    output = tmp_path / "composite"
    _write_source(base)
    _write_source(replacement, replacement=True)
    manifest = json_read(replacement / "run-manifest.json")
    manifest["resolved_roles"]["execution_primary"]["model_id"] = "different-model"
    json_write(replacement / "run-manifest.json", manifest)

    with pytest.raises(CompositionError, match="differs in model_id"):
        compose_track_repair(
            base, replacement, output, tracks={"intent_elicitation"}
        )


def test_compose_rejects_non_budget_parameter_change(tmp_path):
    base = tmp_path / "base"
    replacement = tmp_path / "replacement"
    output = tmp_path / "composite"
    _write_source(base)
    _write_source(replacement, replacement=True)
    manifest = json_read(replacement / "run-manifest.json")
    manifest["resolved_roles"]["boundary_canonicalizer"]["parameters"][
        "temperature"
    ] = 0.2
    json_write(replacement / "run-manifest.json", manifest)

    with pytest.raises(CompositionError, match="unsupported parameters"):
        compose_track_repair(
            base, replacement, output, tracks={"intent_elicitation"}
        )
