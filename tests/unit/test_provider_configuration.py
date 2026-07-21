"""Provider-role resolution and mock eligibility controls."""

from pathlib import Path

import pytest

from lexstab.artifacts import find_repo_root
from lexstab.config import ConfigError, load_models_config, load_run_config
from lexstab.run import build_run_context, summarize_run_health

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


def test_v020_run_configs_use_frozen_sources_and_rmi_has_split_safe_check():
    expected_manifest = "dataset/manifests/benchmark-v0.2.0.json"
    expected_procedures = "dataset/procedures/frozen/support-v0.2.0.jsonl"
    expected_generic = "dataset/interfaces/v0.2.0/generic-action-proposal.json"
    expected_typed = "dataset/interfaces/v0.2.0/typed-tools/support.jsonl"

    for filename in (
        "run.v0.2-provider-check.yaml",
        "run.v0.2-rmi-check.yaml",
        "run.local.yaml",
    ):
        config = load_run_config(ROOT / "config" / filename)
        formal = config.tracks["progressive_formalization"]
        assert config.benchmark_manifest == expected_manifest
        assert formal["procedure_registry"] == expected_procedures
        assert formal["generic_action_interface"] == expected_generic
        assert formal["typed_action_interfaces"] == expected_typed

    provider_check = load_run_config(ROOT / "config/run.v0.2-provider-check.yaml")
    assert provider_check.selection["split"] == "development"
    assert not {"RMI_001", "CLOSE_001"} & set(provider_check.selection["case_ids"])

    rmi_check = load_run_config(ROOT / "config/run.v0.2-rmi-check.yaml")
    assert rmi_check.selection["split"] == "validation"
    assert {"RMI_001", "CLOSE_001"}.issubset(
        rmi_check.selection["case_ids"]
    )
    assert {
        "REQ-RMI-001-0004",
        "REQ-RMI-001-0005",
        "REQ-RMI-001-0006",
        "REQ-RMI-001-INADEQUATE-0003",
        "REQ-CLOSE-001-CONTRAST-0002",
    }.issubset(rmi_check.selection["request_ids"])

    full_run = load_run_config(ROOT / "config/run.local.yaml")
    assert full_run.execution["repetitions"] == 1


def test_length_termination_invalidates_health_and_baseline_eligibility():
    summary = summarize_run_health(
        [],
        configured_baseline_eligible=True,
        invocations=[{
            "cell_id": "cell-length-terminated",
            "finish_reason": "length",
        }],
    )
    assert summary["status"] == "length_terminated"
    assert summary["healthy"] is False
    assert summary["baseline_eligible"] is False
    assert summary["length_terminated_calls"] == 1
