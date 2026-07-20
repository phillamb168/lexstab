"""Local trace helpers (spec §23.1-23.3).

The runner writes append-only JSONL traces through :mod:`lexstab.run`; this
module provides the span-view reader used by tests and the results guide.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lexstab.artifacts import jsonl_read

TRACE_FILES = [
    "run-manifest.json",
    "matrix.jsonl",
    "cell-results.jsonl",
    "invocations.jsonl",
    "simulator-events.jsonl",
    "representation-ledger.jsonl",
    "procedure-events.jsonl",
    "interface-events.jsonl",
    "scores.jsonl",
    "judge-records.jsonl",
    "human-review.jsonl",
    "metrics.json",
    "report.md",
    "report.html",
]


def cell_span(run_dir: Path, cell_id: str) -> dict[str, Any]:
    """Assemble the §23.2 span view for one matrix cell from stored traces."""
    span: dict[str, Any] = {"cell_id": cell_id}
    for name, key in (
        ("invocations.jsonl", "model_invocations"),
        ("simulator-events.jsonl", "simulator_transitions"),
        ("representation-ledger.jsonl", "representation_handoffs"),
        ("procedure-events.jsonl", "procedure_selection"),
        ("interface-events.jsonl", "interface_events"),
        ("scores.jsonl", "deterministic_evaluation"),
    ):
        path = run_dir / name
        if path.exists():
            span[key] = [row for row in jsonl_read(path) if row.get("cell_id") == cell_id]
    return span


def redact(text: str) -> str:
    """Credential redaction for exported traces (§23.5); env values never enter
    prompts, but exported artifacts are scrubbed defensively."""
    import os
    import re

    redacted = text
    for name, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        if name.endswith(("_API_KEY", "_TOKEN", "_SECRET")):
            redacted = redacted.replace(value, f"<redacted:{name}>")
    redacted = re.sub(r"sk-[A-Za-z0-9\-_]{16,}", "<redacted:key>", redacted)
    return redacted
