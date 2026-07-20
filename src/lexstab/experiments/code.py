"""Experiment 5: code identifier renaming (spec §28; D-014).

Mechanically verifies pre-mutation variant equivalence over a generated input
space, then scores model modifications by executable tests in a subprocess.
The primary metric is test success, never judge opinion (§28.7).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from lexstab.artifacts import jsonl_read, jsonl_write
from lexstab.config import load_models_config
from lexstab.prompts import PromptLibrary
from lexstab.providers.registry import build_provider


def mechanical_equivalence(variant_a: dict, variant_b: dict) -> bool:
    """Run both variants' behavior probe over the declared input space and
    compare outputs (§28.3)."""
    probe = variant_a.get("equivalence_probe")
    if not probe:
        return False
    outputs = []
    for variant in (variant_a, variant_b):
        code = variant["code"] + "\n" + probe.replace("{class_name}", variant["class_name"]) \
            .replace("{ctor_arg}", variant["ctor_arg"]).replace("{method}", variant["method"])
        result = _run_python(code)
        if result["returncode"] != 0:
            return False
        outputs.append(result["stdout"])
    return outputs[0] == outputs[1]


def _run_python(code: str, timeout: int = 20) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "candidate.py"
        path.write_text(code)
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(path)],
                capture_output=True, text=True, timeout=timeout, cwd=tmp,
            )
            return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "timeout"}


def score_modification(variant: dict, modified_code: str) -> dict[str, Any]:
    compile_ok = True
    try:
        compile(modified_code, "<candidate>", "exec")
    except SyntaxError as exc:
        compile_ok = False
        return {"compile_ok": False, "error": str(exc), "tests_passed": False,
                "regression_passed": False, "forbidden_renames": []}
    forbidden = [
        original for original in variant.get("identifier_map", {})
        if original not in modified_code
    ]
    test_result = _run_python(modified_code + "\n" + variant["feature_tests"])
    regression_result = _run_python(modified_code + "\n" + variant["regression_tests"])
    return {
        "compile_ok": compile_ok,
        "tests_passed": test_result["returncode"] == 0,
        "regression_passed": regression_result["returncode"] == 0,
        "forbidden_renames": forbidden,
        "test_stderr": test_result["stderr"][-400:] if test_result["returncode"] != 0 else "",
    }


def run_code_experiment(
    root: Path, dataset_path: Path, models_path: str, output: Path,
) -> dict[str, Any]:
    prompts = PromptLibrary(root / "prompts")
    models_config = load_models_config(root / models_path, strict_env=False)
    role = models_config.role("execution_primary")
    adapter = build_provider(role)
    variants = jsonl_read(dataset_path)
    by_family: dict[str, list[dict]] = {}
    for variant in variants:
        by_family.setdefault(variant["program_family_id"], []).append(variant)

    rows = []
    for family_id, family in sorted(by_family.items()):
        for pair_index in range(len(family) - 1):
            equivalent = mechanical_equivalence(family[pair_index], family[pair_index + 1])
            if not equivalent:
                rows.append({"family": family_id, "error": "pre-mutation equivalence failed",
                             "variants": [family[pair_index]["variant_id"],
                                          family[pair_index + 1]["variant_id"]]})
        for variant in family:
            record = adapter.invoke(
                role="execution_primary",
                model_id=role.model_id or "mock",
                messages=[{
                    "role": "system",
                    "content": prompts.get("code-modification.v1").render(
                        language=variant["language"],
                        requirement=variant["requirement"],
                        code=variant["code"],
                    ),
                }],
                tools=None, response_schema=None, parameters=role.parameters,
                metadata={"run_id": "code", "cell_id": f"code:{variant['variant_id']}",
                          "timestamp": "", "response_kind": "source_code"},
            )
            modified = record.normalized_text or ""
            if modified.startswith("```"):
                modified = "\n".join(
                    line for line in modified.splitlines()
                    if not line.strip().startswith("```")
                )
            score = score_modification(variant, modified)
            rows.append({
                "family": family_id,
                "variant_id": variant["variant_id"],
                "identifier_condition": variant["identifier_condition"],
                **score,
            })
    jsonl_write(output, rows)
    scored = [row for row in rows if "variant_id" in row]
    return {
        "variants": len(scored),
        "full_test_pass_rate": (
            round(sum(1 for row in scored if row["tests_passed"] and row["regression_passed"])
                  / len(scored), 4) if scored else None
        ),
        "forbidden_rename_rate": (
            round(sum(1 for row in scored if row["forbidden_renames"]) / len(scored), 4)
            if scored else None
        ),
        "equivalence_failures": [row for row in rows if "error" in row],
        "output": str(output),
    }
