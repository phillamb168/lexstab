"""Optional LangSmith mirror (spec §23.4; D-015).

Local JSONL artifacts remain the source of truth; this exporter mirrors run
metadata when LANGSMITH_TRACING=true and the langsmith package plus API key
are available. Everything degrades to a no-op otherwise.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from lexstab.artifacts import json_read, jsonl_read


def langsmith_enabled() -> bool:
    return os.environ.get("LANGSMITH_TRACING", "").lower() == "true" and bool(
        os.environ.get("LANGSMITH_API_KEY")
    )


def _metadata_for_score(score: dict, manifest: dict) -> dict[str, Any]:
    meta = score.get("metadata", {})
    return {
        "benchmark_root_hash": manifest.get("benchmark_root_hash"),
        "run_id": manifest.get("run_id"),
        "case_id": score.get("case_id"),
        "request_id": score.get("request_id"),
        "rendering_id": score.get("rendering_id"),
        "procedure_id": score.get("procedure_id"),
        "action_interface_id": score.get("interface_id"),
        "architecture": score.get("architecture"),
        "track": score.get("track"),
        "model_id": score.get("model_id"),
        "repetition": score.get("repetition"),
        "persistence_condition": (
            score.get("architecture") if str(score.get("architecture", "")).startswith("LP") else None
        ),
        "formalization_condition": (
            score.get("architecture") if str(score.get("architecture", "")).startswith("P") else None
        ),
        "variation_axes": meta.get("variation_axes"),
        "adequacy": meta.get("adequacy"),
        "ambiguity": meta.get("ambiguity"),
        "expected_behavior": meta.get("expected_behavior"),
    }


def export_run(run_dir: Path, project: str | None = None) -> dict[str, Any]:
    """Mirror a stored run's scores to LangSmith as run trees. No-op without
    credentials; never raises on missing optional dependency."""
    if not langsmith_enabled():
        return {"exported": 0, "reason": "LangSmith tracing disabled or unconfigured"}
    try:
        from langsmith import Client
    except ImportError:
        return {"exported": 0, "reason": "langsmith package not installed"}
    client = Client()
    manifest = json_read(run_dir / "run-manifest.json")
    project_name = project or os.environ.get("LANGSMITH_PROJECT", "lexstab-local")
    scores = jsonl_read(run_dir / "scores.jsonl")
    exported = 0
    for score in scores:
        client.create_run(
            name=f"{score['architecture']}:{score['cell_id']}",
            run_type="chain",
            project_name=project_name,
            inputs={"cell_id": score["cell_id"]},
            outputs={"full_call_correct": score.get("full_call_correct"),
                     "final_state_correct": score.get("final_state_correct")},
            extra={"metadata": _metadata_for_score(score, manifest)},
        )
        exported += 1
    return {"exported": exported, "project": project_name}
