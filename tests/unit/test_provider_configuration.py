"""Provider-role resolution and mock eligibility controls."""

from pathlib import Path

import pytest

from lexstab.artifacts import find_repo_root
from lexstab.config import ConfigError, load_models_config, load_run_config
from lexstab.run import build_run_context

ROOT = find_repo_root(Path(__file__))


def _models_file(tmp_path: Path) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(
        """
schema_version: "1.2.0"
roles:
  execution_primary:
    provider: anthropic
    model: ${TEST_EXECUTION_MODEL_ID}
    purpose: model_under_test
    baseline_eligible: true
  boundary_canonicalizer:
    provider: mock
    model: mock-canonicalizer
    purpose: runtime_canonicalization
separation_policy:
  allow_role_overlap: false
""".strip()
    )
    return path


def test_required_role_model_id_is_strict(tmp_path, monkeypatch):
    path = _models_file(tmp_path)
    monkeypatch.delenv("TEST_EXECUTION_MODEL_ID", raising=False)
    with pytest.raises(ConfigError, match="TEST_EXECUTION_MODEL_ID"):
        load_models_config(
            path, strict_env=True, strict_roles={"execution_primary"}
        )


def test_any_mocked_runtime_role_makes_run_ineligible(tmp_path, monkeypatch):
    path = _models_file(tmp_path)
    monkeypatch.setenv("TEST_EXECUTION_MODEL_ID", "real-execution-model")
    config = load_run_config(ROOT / "config/run.smoke.yaml")
    for name, track in config.tracks.items():
        track["enabled"] = name == "boundary"
    config.model_config_path = str(path)
    ctx, _matrix, _models = build_run_context(ROOT, config, run_id="mixed")
    assert ctx.mocked is True


def test_agent_loop_matrix_separates_gold_and_runtime_intent():
    config = load_run_config(ROOT / "config/run.smoke.yaml")
    for name, track in config.tracks.items():
        track["enabled"] = name == "agent_loop"
    config.tracks["agent_loop"]["conditions"] = ["AL_CANONICAL"]
    config.tracks["agent_loop"]["intent_modes"] = ["gold", "runtime"]
    _ctx, matrix, _models = build_run_context(ROOT, config, run_id="intent-modes")
    assert {cell.intent_mode for cell in matrix.cells} == {"gold", "runtime"}
