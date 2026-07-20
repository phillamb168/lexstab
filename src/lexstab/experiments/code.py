"""Experiment 5: code identifier renaming (spec §28; D-014).

Mechanically verifies pre-mutation variant equivalence over a generated input
space, then scores model modifications by executable tests in a subprocess.
The primary metric is test success, never judge opinion (§28.7).
"""

from __future__ import annotations

import os
import resource
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from lexstab.artifacts import jsonl_read, jsonl_write
from lexstab.config import load_models_config
from lexstab.prompts import PromptLibrary
from lexstab.providers.registry import build_provider


def mechanical_equivalence(
    variant_a: dict, variant_b: dict, *, trusted_fixture: bool = False
) -> bool:
    """Run both variants' behavior probe over the declared input space and
    compare outputs (§28.3)."""
    probe = variant_a.get("equivalence_probe")
    if not probe:
        return False
    outputs = []
    for variant in (variant_a, variant_b):
        code = variant["code"] + "\n" + probe.replace("{class_name}", variant["class_name"]) \
            .replace("{ctor_arg}", variant["ctor_arg"]).replace("{method}", variant["method"])
        result = _run_python(code, trusted_fixture=trusted_fixture)
        if result["returncode"] != 0:
            return False
        outputs.append(result["stdout"])
    return outputs[0] == outputs[1]


def _trusted_limits() -> None:
    """Defense in depth for repository-owned mock fixtures only.

    This is not the sandbox for generated code. It merely prevents a broken
    fixture from consuming unbounded local resources during offline tests.
    """
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))


def _run_python(
    code: str, timeout: int = 20, *, trusted_fixture: bool = False
) -> dict[str, Any]:
    """Execute Python only in an isolated container.

    Host execution is reserved for repository-owned fixtures in deterministic
    mock tests. Provider-generated code is never run directly on the host.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "candidate.py"
        path.write_text(code)
        Path(tmp).chmod(0o755)
        path.chmod(0o444)
        if trusted_fixture:
            minimal_env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            command = [sys.executable, "-I", str(path)]
            preexec_fn = _trusted_limits if sys.platform.startswith("linux") else None
        else:
            runtime = os.environ.get("LEXSTAB_CODE_SANDBOX_RUNTIME", "docker")
            runtime_path = shutil.which(runtime)
            if not runtime_path:
                return {
                    "returncode": -2,
                    "stdout": "",
                    "stderr": (
                        f"code sandbox unavailable: {runtime!r} was not found; "
                        "generated code was not executed"
                    ),
                }
            image = os.environ.get(
                "LEXSTAB_CODE_SANDBOX_IMAGE", "python:3.13-alpine"
            )
            command = [
                runtime_path, "run", "--rm",
                "--network", "none",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--pids-limit", "64",
                "--memory", "256m",
                "--cpus", "1",
                "--user", "65534:65534",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                "--volume", f"{tmp}:/workspace:ro",
                image,
                "python", "-I", "/workspace/candidate.py",
            ]
            minimal_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
            preexec_fn = None
        try:
            proc = subprocess.run(
                command,
                capture_output=True, text=True, timeout=timeout, cwd=tmp,
                env=minimal_env,
                preexec_fn=preexec_fn,
            )
            return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "timeout"}


def score_modification(
    variant: dict, modified_code: str, *, trusted_fixture: bool = False
) -> dict[str, Any]:
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
    test_result = _run_python(
        modified_code + "\n" + variant["feature_tests"],
        trusted_fixture=trusted_fixture,
    )
    regression_result = _run_python(
        modified_code + "\n" + variant["regression_tests"],
        trusted_fixture=trusted_fixture,
    )
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
    models_config = load_models_config(
        root / models_path,
        strict_env=True,
        strict_roles={"execution_primary"},
    )
    role = models_config.role("execution_primary")
    adapter = build_provider(role)
    variants = jsonl_read(dataset_path)
    by_family: dict[str, list[dict]] = {}
    for variant in variants:
        by_family.setdefault(variant["program_family_id"], []).append(variant)

    rows = []
    for family_id, family in sorted(by_family.items()):
        for pair_index in range(len(family) - 1):
            equivalent = mechanical_equivalence(
                family[pair_index], family[pair_index + 1],
                trusted_fixture=(role.provider == "mock"),
            )
            if not equivalent:
                rows.append({"family": family_id, "error": "pre-mutation equivalence failed",
                             "variants": [family[pair_index]["variant_id"],
                                          family[pair_index + 1]["variant_id"]]})
        for variant in family:
            record = adapter.invoke(
                role="execution_primary",
                model_id=role.model_id or "",
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
            score = score_modification(
                variant, modified, trusted_fixture=(role.provider == "mock")
            )
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
