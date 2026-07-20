"""Generated code must fail closed when no isolated runtime is available."""

from lexstab.experiments.code import _run_python


def test_generated_code_is_not_run_on_host_without_sandbox(monkeypatch):
    monkeypatch.setenv("LEXSTAB_CODE_SANDBOX_RUNTIME", "definitely-not-installed")
    result = _run_python("raise SystemExit('must not run')")
    assert result["returncode"] == -2
    assert "not executed" in result["stderr"]
