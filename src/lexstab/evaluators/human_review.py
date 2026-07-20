"""Human adjudication records (spec §23.1, §35.5, §49.9).

Judge UNCERTAIN results and judge-human disagreements route here. Records
preserve rubric, reviewer ID, timestamp, and notes in
``runs/<id>/human-review.jsonl``.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from lexstab.artifacts import jsonl_append, jsonl_read


def pending_review_queue(run_dir: Path) -> list[dict[str, Any]]:
    """Cells whose judge output requires human adjudication."""
    judge_path = run_dir / "judge-records.jsonl"
    if not judge_path.exists():
        return []
    reviewed = {
        row["cell_id"]
        for row in (jsonl_read(run_dir / "human-review.jsonl")
                    if (run_dir / "human-review.jsonl").exists() else [])
    }
    queue = []
    for row in jsonl_read(judge_path):
        judge = row.get("judge") or {}
        needs_review = (
            not row.get("parse_ok")
            or judge.get("score") == "UNCERTAIN"
            or judge.get("human_review_required")
        )
        if needs_review and row["cell_id"] not in reviewed:
            queue.append(row)
    return queue


def record_human_review(
    run_dir: Path,
    *,
    cell_id: str,
    criterion: str,
    rubric: str,
    reviewer_id: str,
    decision: str,
    notes: str = "",
) -> dict[str, Any]:
    record = {
        "cell_id": cell_id,
        "criterion": criterion,
        "rubric": rubric,
        "reviewer_id": reviewer_id,
        "decision": decision,
        "notes": notes,
        "reviewed_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    jsonl_append(run_dir / "human-review.jsonl", record)
    return record
