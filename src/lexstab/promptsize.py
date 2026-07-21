"""Deterministic prompt-size comparison for the LP0B preservation ablation.

This module makes no provider calls. Token counts are deliberately labeled as
four-UTF-8-bytes estimates because tokenization is provider and model specific.
The exact rendered character and byte counts are always retained.
"""

from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any

from lexstab.hashing import hash_json_artifact
from lexstab.prompts import PromptLibrary


FIXTURE: dict[str, str] = {
    "request_or_canonical_input": (
        'Request more information for incident INC-3120 with this public message: '
        '"Please attach the missing application logs and the approximate time of the failure."'
    ),
    "canonical_entity_definitions": (
        "INCIDENT is a support record identified by an INC-prefixed ID."
    ),
    "known_state": (
        '{"incidents":{"INC-3120":{"status":"open","owner_team":"service-desk",'
        '"awaiting_action_from":null}}}'
    ),
    "triage_result": (
        "Incident INC-3120 is open. Ask its reporter to attach the missing application "
        "logs and give the approximate time of the failure."
    ),
    "policies": "No listed policy governs this request.",
    "policy_result": (
        "No special policy is required. Keep incident INC-3120 with the service desk "
        "and ask its reporter to attach the missing application logs and give the "
        "approximate time of the failure."
    ),
    "allowed_operations": "REQUEST_MORE_INFORMATION",
    "task_input": (
        "Ask the reporter of incident INC-3120 to attach the missing application logs "
        "and give the approximate time of the failure."
    ),
    "domain_rules": "REQUEST_MORE_INFORMATION requires incident_id and message.",
    "shared_context": "No additional shared context.",
    "clarification_policy": (
        "Clarify only when a required operation argument is missing or ambiguous."
    ),
    "preservation_contract": "message",
}


PROMPT_PAIRS = (
    ("triage", "triage-language-handoff.v1", "triage-language-handoff-verbatim.v1"),
    ("policy", "policy-language-handoff.v2", "policy-language-handoff-verbatim.v1"),
    ("planner", "planner-language-handoff.v2", "planner-language-handoff-verbatim.v1"),
    ("action", "action-proposal-executor.v1", "action-proposal-executor-verbatim.v1"),
)


def _render(prompt, fixture: dict[str, str]) -> str:
    return prompt.render(**{
        variable: fixture[variable]
        for variable in prompt.required_variables
    })


def _counts(text: str) -> dict[str, int]:
    byte_count = len(text.encode("utf-8"))
    return {
        "characters": len(text),
        "utf8_bytes": byte_count,
        "estimated_tokens_four_bytes": math.ceil(byte_count / 4),
    }


def build_prompt_size_report(
    root: Path,
    *,
    target_median_percent: float = 2.0,
    per_stage_warning_percent: float = 5.0,
) -> dict[str, Any]:
    library = PromptLibrary(root / "prompts")
    rows = []
    for stage, baseline_id, reminder_id in PROMPT_PAIRS:
        baseline = _render(library.get(baseline_id), FIXTURE)
        reminder = _render(library.get(reminder_id), FIXTURE)
        base_counts = _counts(baseline)
        reminder_counts = _counts(reminder)
        delta_bytes = reminder_counts["utf8_bytes"] - base_counts["utf8_bytes"]
        delta_percent = (
            100.0 * delta_bytes / base_counts["utf8_bytes"]
            if base_counts["utf8_bytes"] else 0.0
        )
        rows.append({
            "stage": stage,
            "baseline_prompt_id": baseline_id,
            "reminder_prompt_id": reminder_id,
            "baseline": base_counts,
            "reminder": reminder_counts,
            "delta_utf8_bytes": delta_bytes,
            "delta_estimated_tokens": (
                reminder_counts["estimated_tokens_four_bytes"]
                - base_counts["estimated_tokens_four_bytes"]
            ),
            "delta_percent": delta_percent,
            "warning": delta_percent > per_stage_warning_percent,
        })
    percentages = [row["delta_percent"] for row in rows]
    median_percent = statistics.median(percentages) if percentages else 0.0
    total_base = sum(row["baseline"]["utf8_bytes"] for row in rows)
    total_reminder = sum(row["reminder"]["utf8_bytes"] for row in rows)
    return {
        "report_version": "prompt-size.v1",
        "provider_calls": 0,
        "counting_method": (
            "Exact characters and UTF-8 bytes; estimated tokens are ceil(UTF-8 bytes / 4). "
            "The estimate is not a provider tokenizer result."
        ),
        "fixture_hash": hash_json_artifact(FIXTURE),
        "fixture": FIXTURE,
        "thresholds": {
            "target_median_percent": target_median_percent,
            "per_stage_warning_percent": per_stage_warning_percent,
        },
        "stages": rows,
        "summary": {
            "median_delta_percent": median_percent,
            "median_target_met": median_percent < target_median_percent,
            "stages_above_warning": [row["stage"] for row in rows if row["warning"]],
            "total_baseline_utf8_bytes": total_base,
            "total_reminder_utf8_bytes": total_reminder,
            "total_delta_utf8_bytes": total_reminder - total_base,
            "total_delta_percent": (
                100.0 * (total_reminder - total_base) / total_base
                if total_base else 0.0
            ),
        },
    }


def render_prompt_size_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# LP0B prompt-size comparison",
        "",
        f"Fixture hash: `{report['fixture_hash']}`",
        "",
        report["counting_method"],
        "",
        "| Stage | Baseline bytes | Reminder bytes | Estimated token delta | Delta | Warning |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["stages"]:
        lines.append(
            f"| {row['stage']} | {row['baseline']['utf8_bytes']} | "
            f"{row['reminder']['utf8_bytes']} | {row['delta_estimated_tokens']} | "
            f"{row['delta_percent']:.2f}% | {'yes' if row['warning'] else 'no'} |"
        )
    summary = report["summary"]
    lines += [
        "",
        f"Median stage delta: **{summary['median_delta_percent']:.2f}%**. "
        f"Target met: **{'yes' if summary['median_target_met'] else 'no'}**.",
        "",
        f"Aggregate prompt delta: **{summary['total_delta_percent']:.2f}%** "
        f"({summary['total_delta_utf8_bytes']} UTF-8 bytes).",
        "",
    ]
    return "\n".join(lines)
