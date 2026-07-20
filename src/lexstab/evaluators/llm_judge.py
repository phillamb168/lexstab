"""Optional blinded LLM judge route (spec §35.3-35.5; D-016).

Judges score only outputs that lack a formal oracle (clarification usefulness
here). Prompts hide provider, model, architecture, and favored condition;
candidates are keyed by opaque IDs. Scores are exploratory unless a human
calibration record exists (judge-calibration.json with >=2 raters).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from lexstab.artifacts import json_read, jsonl_read, jsonl_write
from lexstab.config import ModelsConfig
from lexstab.prompts import PromptLibrary
from lexstab.providers.base import BaseAdapter, extract_json_object
from lexstab.providers.registry import build_provider

CLARIFICATION_RUBRIC = (
    "PASS when the clarification question, on its own, would let a cooperative "
    "user supply the information that distinguishes the gold candidate "
    "interpretations or fills the gold missing fields. FAIL when it asks for "
    "already-present information, asks about an unrelated matter, or would not "
    "distinguish the candidates. UNCERTAIN when the rubric cannot determine it."
)


def _opaque_id(cell_id: str) -> str:
    return "cand-" + hashlib.sha256(cell_id.encode()).hexdigest()[:10]


def calibration_status(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "judge-calibration.json"
    if not path.exists():
        return {"calibrated": False, "reason": "no judge-calibration.json"}
    record = json_read(path)
    raters = record.get("human_raters", [])
    if len(raters) < 2:
        return {"calibrated": False, "reason": "fewer than two human raters"}
    if not record.get("paraphrase_robustness"):
        return {"calibrated": False, "reason": "no paraphrase robustness record"}
    return {"calibrated": True, "record": record}


def judge_clarifications(
    root: Path,
    run_dir: Path,
    models_config: ModelsConfig,
    *,
    provider: BaseAdapter | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Judge stored clarification questions for usefulness. Reads the frozen
    gold targets as reference; never sees architecture or model identity."""
    role = models_config.role("evaluation_judge")
    adapter = provider or build_provider(role)
    prompts = PromptLibrary(root / "prompts")
    scores = jsonl_read(run_dir / "scores.jsonl")
    results = {row["cell_id"]: row for row in jsonl_read(run_dir / "cell-results.jsonl")}
    judged = []
    for score in scores:
        if score.get("clarification_outcome") not in ("TP", "FN"):
            continue
        result = results.get(score["cell_id"], {})
        question = result.get("question")
        if not question:
            continue
        expected = score.get("metadata", {})
        reference = json.dumps(
            {
                "missing_information": expected.get("missing_information", []),
                "clarification_targets": expected.get("clarification_targets", []),
                "candidate_operation": expected.get("expected_operation_id"),
                "known_arguments": expected.get("expected_arguments", {}),
                "expected_behavior": expected.get("expected_behavior"),
            },
            sort_keys=True,
        )
        record = adapter.invoke(
            role="evaluation_judge",
            model_id=role.model_id or "",
            messages=[{
                "role": "system",
                "content": prompts.get("semantic-equivalence-judge.v1").render(
                    task_input="A user request required clarification before action.",
                    reference=reference,
                    candidate_output=question,
                    rubric=CLARIFICATION_RUBRIC,
                ),
            }],
            tools=None,
            response_schema=None,
            parameters=role.parameters,
            metadata={
                "run_id": score["run_id"],
                "cell_id": _opaque_id(score["cell_id"]),  # blinded
                "timestamp": "",
                "response_kind": "judge_result",
            },
        )
        obj, _err = extract_json_object(record.normalized_text)
        judged.append({
            "cell_id": score["cell_id"],
            "opaque_id": _opaque_id(score["cell_id"]),
            "criterion": "clarification_usefulness",
            "judge": obj,
            "parse_ok": obj is not None,
        })
        if limit and len(judged) >= limit:
            break
    calibration = calibration_status(run_dir)
    for row in judged:
        row["calibrated"] = calibration["calibrated"]
        row["analysis_label"] = "primary_eligible" if calibration["calibrated"] else "exploratory"
    jsonl_write(run_dir / "judge-records.jsonl", judged)
    return judged
