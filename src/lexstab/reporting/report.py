"""Report orchestration (spec §44, §49.14): metrics.json in, all formats out.

Reporting is read-only over evaluation outputs: it consumes ``metrics.json``,
``scores.jsonl``, and ``run-manifest.json`` and never re-scores anything.
``report-metadata.json`` records every generated file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from lexstab.artifacts import json_read, json_write, jsonl_read
from lexstab.reporting.charts import write_charts
from lexstab.reporting.html import render_html
from lexstab.reporting.markdown import render_report
from lexstab.reporting.tables import write_tables

DEFAULT_FORMATS = ("markdown", "html", "csv", "parquet", "json")


class ReportError(Exception):
    pass


def generate_report(
    root: Path,
    run_dir: Path,
    formats: Sequence[str] = DEFAULT_FORMATS,
) -> list[Path]:
    run_dir = Path(run_dir)
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        raise ReportError(
            f"{metrics_path} does not exist: run evaluation first "
            f"(`lexstab evaluate {run_dir}`) so metrics.json and scores.jsonl are "
            "available before reporting"
        )
    scores_path = run_dir / "scores.jsonl"
    if not scores_path.exists():
        raise ReportError(
            f"{scores_path} does not exist: run evaluation first "
            f"(`lexstab evaluate {run_dir}`)"
        )
    manifest_path = run_dir / "run-manifest.json"
    if not manifest_path.exists():
        raise ReportError(f"{manifest_path} does not exist: not a stored run directory")

    metrics: dict[str, Any] = json_read(metrics_path)
    scores = jsonl_read(scores_path)
    run_manifest = json_read(manifest_path)

    unknown = set(formats) - set(DEFAULT_FORMATS)
    if unknown:
        raise ReportError(f"unknown report formats: {sorted(unknown)}")

    generated: list[Path] = []
    if "csv" in formats or "parquet" in formats:
        generated.extend(write_tables(
            run_dir, metrics, scores,
            csv_output="csv" in formats,
            parquet_output="parquet" in formats,
        ))
    if "markdown" in formats or "html" in formats:
        generated.extend(write_charts(run_dir, metrics, scores))
        render_report(run_dir, metrics, scores, run_manifest)
        generated.append(run_dir / "report.md")
    if "html" in formats:
        generated.append(render_html(run_dir))
    if "json" in formats:
        generated.append(metrics_path)

    metadata_path = run_dir / "report-metadata.json"
    json_write(metadata_path, {
        "run_id": metrics.get("run_id"),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "formats": list(formats),
        "mocked": bool(run_manifest.get("mocked")),
        "files": sorted(str(path.relative_to(run_dir)) for path in generated),
    })
    generated.append(metadata_path)
    return generated
