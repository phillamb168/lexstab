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
