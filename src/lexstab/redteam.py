"""Adaptive red team — Graph D (spec §17.2, §18.4).

Reads a frozen run's failures, clusters them, asks the failure analyst for
testable hypotheses, and generates adversarial candidates. Writes ONLY to the
candidate corpus; the frozen benchmark and its scores are never modified.
Statistical code, not the analyst model, tests any suggested hypothesis.
"""

from __future__ import annotations

import datetime as _dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

from lexstab.artifacts import jsonl_read, jsonl_write
from lexstab.authoring import AuthoringContext, build_candidate_record, generate_candidates, \
    challenge_equivalence, classify_adequacy, classify_ambiguity, validate_equivalence

WARNING = (
    "Red-team candidates are exploratory. They enter the candidate corpus for the "
    "NEXT benchmark version after validation and human review. They do not alter "
    "the frozen run's results (spec §17.2)."
)


def cluster_failures(scores: list[dict]) -> list[dict[str, Any]]:
    failures = [
        score for score in scores
        if not score.get("full_call_correct") and score.get("request_id")
    ]
    clusters: Counter = Counter()
    for score in failures:
        axes = tuple(sorted(score.get("metadata", {}).get("variation_axes", [])))
        key = (
            score["case_id"],
            axes,
            score.get("error_category") or "wrong_decision_or_action",
            score.get("metadata", {}).get("first_divergence_stage") or "final",
        )
        clusters[key] += 1
    return [
        {
            "case_id": case_id,
            "variation_axes": list(axes),
            "error_category": error,
            "stage": stage,
            "count": count,
        }
        for (case_id, axes, error, stage), count in clusters.most_common()
    ]


def blinded_failure_table(clusters: list[dict]) -> str:
    """Cluster table shown to the analyst: no architecture or model identity."""
    lines = ["case_id | variation_axes | error_category | stage | count"]
    for cluster in clusters:
        lines.append(
            f"{cluster['case_id']} | {','.join(cluster['variation_axes'])} | "
            f"{cluster['error_category']} | {cluster['stage']} | {cluster['count']}"
        )
    return "\n".join(lines)


def generate_hypotheses(ctx: AuthoringContext, clusters: list[dict]) -> dict | None:
    return ctx.invoke(
        "failure_analyst", "failure-analyst.v1",
        {
            "blinded_failure_table": blinded_failure_table(clusters),
            "metric_definitions": "full_call_correct: correct decision, tool, and all required arguments",
            "benchmark_coverage": json.dumps(sorted({c["case_id"] for c in clusters})),
        },
        "failure_hypotheses",
        mock_key="redteam:hypotheses",
    )


def run_redteam(
    ctx: AuthoringContext,
    run_dir: Path,
    *,
    max_candidates: int = 50,
    output: Path,
) -> dict[str, Any]:
    scores = jsonl_read(run_dir / "scores.jsonl")
    clusters = cluster_failures(scores)
    hypotheses = generate_hypotheses(ctx, clusters) or {"hypotheses": [], "coverage_gaps": []}
    candidate_axes = sorted({
        axis
        for hypothesis in hypotheses.get("hypotheses", [])
        for axis in hypothesis.get("candidate_red_team_axes", [])
    }) or ["idiomatic", "indirect_request"]
    generated: list[dict] = []
    existing_ids: set[str] = set()
    target_cases = sorted({cluster["case_id"] for cluster in clusters})
    generator_model = ctx.models_config.role("authoring_generator").model_id or "mock"
    for case_id in target_cases:
        if len(generated) >= max_candidates:
            break
        case = ctx.cases.get(case_id)
        if case is None:
            continue
        for candidate in generate_candidates(ctx, case, candidate_axes, 3, []):
            if len(generated) >= max_candidates:
                break
            equivalence = validate_equivalence(ctx, case, candidate["text"])
            adversarial = challenge_equivalence(ctx, case, candidate["text"], equivalence)
            adequacy = classify_adequacy(ctx, case, candidate["text"], "(no shared context)")
            ambiguity = classify_ambiguity(ctx, case, candidate["text"], "(no shared context)")
            record = build_candidate_record(
                ctx, case, candidate,
                {"equivalence": equivalence, "adversarial": adversarial,
                 "adequacy": adequacy, "ambiguity": ambiguity},
                existing_ids, generator_model,
            )
            record["source"]["type"] = "redteam"
            record["provenance"]["source_run_id"] = run_dir.name
            record["validation"]["status"] = "NEEDS_REVIEW"  # red-team always needs human review
            existing_ids.add(record["request_id"])
            generated.append(record)
    jsonl_write(output, generated)
    report = {
        "warning": WARNING,
        "source_run": run_dir.name,
        "failure_clusters": clusters,
        "hypotheses": hypotheses,
        "candidates_written": len(generated),
        "output": str(output),
        "created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return report
