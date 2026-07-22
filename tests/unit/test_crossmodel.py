import json
from pathlib import Path

import pytest

from lexstab.metrics.crossmodel import LP0B, LP0BV, LP1, compare_runs


def _write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def _make_run(
    root: Path,
    *,
    run_id: str,
    model_id: str,
    lp0b: tuple[int, int],
    evaluation_hash: str = "sha256:evaluator",
) -> Path:
    run_dir = root / run_id
    run_dir.mkdir()
    manifest = {
        "run_id": run_id,
        "created_at": "2026-07-21T00:00:00Z",
        "benchmark_root_hash": "sha256:benchmark",
        "matrix_hash": "sha256:matrix",
        "matrix_seed": 104729,
        "run_clock": "2026-07-20T12:00:00Z",
        "prompt_hashes": {"p": "sha256:p"},
        "procedure_hashes": {"procedure": "sha256:procedure"},
        "interface_hashes": {"interface": "sha256:interface"},
        "code_revision": "revision-a",
        "mocked": False,
        "resolved_roles": {
            "execution_primary": {
                "model_id": model_id,
                "provider": "anthropic",
                "parameters": {"max_tokens": 1024},
            },
            "evaluation_judge": {
                "enabled": False,
                "model_id": "judge",
                "provider": "test",
            },
        },
    }
    _write_json(run_dir / "run-manifest.json", manifest)
    _write_json(
        run_dir / "run-summary.json",
        {
            "run_id": run_id,
            "status": "complete",
            "healthy": True,
            "baseline_eligible": True,
        },
    )
    _write_json(
        run_dir / "metrics.json",
        {
            "run_id": run_id,
            "evaluation_harness_source_hash": evaluation_hash,
            "completion": {"completion_rate": 1.0, "matrix_cells": 6, "scored_cells": 6},
        },
    )

    matrix: list[dict] = []
    scores: list[dict] = []
    invocations: list[dict] = []
    values = {
        LP0B: lp0b,
        LP0BV: lp0b,
        LP1: (1, 1),
    }
    for architecture in (LP0B, LP0BV, LP1):
        for index, value in enumerate(values[architecture], start=1):
            case_id = f"CASE_{index}"
            request_id = f"REQ_{index}"
            cell_id = f"{architecture}-{index}"
            matrix.append(
                {
                    "cell_id": cell_id,
                    "case_id": case_id,
                    "request_id": request_id,
                    "repetition": 0,
                    "architecture": architecture,
                }
            )
            scores.append(
                {
                    "cell_id": cell_id,
                    "case_id": case_id,
                    "request_id": request_id,
                    "repetition": 0,
                    "architecture": architecture,
                    "final_state_correct": bool(value),
                    "verbatim_arguments_correct": bool(value),
                    "full_call_correct": bool(value),
                    "rendering_id": None,
                    "metadata": {
                        "intent_mode": "gold",
                        "procedure_selection": "none",
                        "procedure_packaging": "none",
                        "primary_h1": True,
                    },
                }
            )
            invocations.append(
                {
                    "cell_id": cell_id,
                    "role": "execution_primary",
                    "finish_reason": "end_turn",
                    "latency_ms": 10,
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                }
            )
    _write_jsonl(run_dir / "matrix.jsonl", matrix)
    _write_jsonl(run_dir / "scores.jsonl", scores)
    _write_jsonl(run_dir / "invocations.jsonl", invocations)
    return run_dir


def test_compare_runs_computes_persistence_difference_in_differences(tmp_path: Path):
    opus = _make_run(
        tmp_path,
        run_id="opus",
        model_id="claude-opus-4-8",
        lp0b=(1, 0),
    )
    sonnet = _make_run(
        tmp_path,
        run_id="sonnet",
        model_id="claude-sonnet-5",
        lp0b=(0, 0),
    )

    result = compare_runs(
        [opus, sonnet],
        baseline_model="claude-opus-4-8",
        samples=100,
    )

    assert result["compatibility"]["compatible"] is True
    assert result["models"]["claude-opus-4-8"]["execution_usage"]["calls"] == 6
    opus_benefit = result["models"]["claude-opus-4-8"]["persistence"][
        "within_model_benefits"
    ]["canonical_once_minus_prose"]["final_state_correct"]
    assert opus_benefit["delta_b_minus_a"]["estimate"] == 0.5

    pair = result["pairwise_persistence"][
        "claude-opus-4-8 -> claude-sonnet-5"
    ]
    did = pair["difference_in_differences"]["canonical_once_minus_prose"][
        "final_state_correct"
    ]
    assert did["difference_in_differences"]["estimate"] == 0.5
    assert did["case_level_sign_test"]["b_better_cases"] == 1
    assert did["case_level_sign_test"]["tied_cases"] == 1


def test_compare_runs_rejects_different_evaluator_versions(tmp_path: Path):
    first = _make_run(tmp_path, run_id="first", model_id="a", lp0b=(1, 0))
    second = _make_run(
        tmp_path,
        run_id="second",
        model_id="b",
        lp0b=(0, 0),
        evaluation_hash="sha256:different",
    )

    with pytest.raises(ValueError, match="evaluation harness source hash differs"):
        compare_runs([first, second], samples=10)


def test_compare_runs_rejects_different_matrices(tmp_path: Path):
    first = _make_run(tmp_path, run_id="first", model_id="a", lp0b=(1, 0))
    second = _make_run(tmp_path, run_id="second", model_id="b", lp0b=(0, 0))
    rows = [json.loads(line) for line in (second / "matrix.jsonl").read_text().splitlines()]
    rows[0]["request_id"] = "DIFFERENT"
    _write_jsonl(second / "matrix.jsonl", rows)

    with pytest.raises(ValueError, match="matrix rows differ"):
        compare_runs([first, second], samples=10)


def test_compare_runs_requires_two_unique_models(tmp_path: Path):
    first = _make_run(tmp_path, run_id="first", model_id="same", lp0b=(1, 0))
    second = _make_run(tmp_path, run_id="second", model_id="same", lp0b=(0, 0))

    with pytest.raises(ValueError, match="must be unique"):
        compare_runs([first, second], samples=10)
