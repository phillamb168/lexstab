"""Integration tests: freeze immutability, execution, rescoring, runner
equivalence, and elicitation (spec §16.2, §18.7, §42.15, §49.16)."""

import shutil
from pathlib import Path

import pytest

from lexstab.artifacts import find_repo_root, json_read, jsonl_read
from lexstab.config import load_run_config
from lexstab.evaluate import evaluate_run
from lexstab.freeze import FreezeError, FrozenBenchmark, freeze_benchmark
from lexstab.hashing import hash_file
from lexstab.run import execute_run

ROOT = find_repo_root(Path(__file__))
MANIFEST = ROOT / "dataset" / "manifests" / "benchmark-v0.1.0.json"


@pytest.fixture(scope="module")
def small_run(tmp_path_factory):
    """One tiny boundary-track run shared across tests in this module."""
    runs_dir = tmp_path_factory.mktemp("runs")
    config = load_run_config(ROOT / "config/run.smoke.yaml")
    for name, spec in config.raw["tracks"].items():
        enabled = name == "boundary"
        spec["enabled"] = enabled
        config.tracks[name]["enabled"] = enabled
    config.raw["selection"]["limit_cases"] = 2
    config.selection["limit_cases"] = 2
    run_dir = execute_run(ROOT, config, runs_dir=runs_dir, run_id="itest-boundary")
    return run_dir


class TestFreeze:
    def test_manifest_loads_and_verifies(self):
        bench = FrozenBenchmark(ROOT, MANIFEST)
        assert bench.manifest.benchmark_version == "0.1.0"
        assert len(bench.cases) == 12

    def test_refreeze_without_override_fails(self):
        with pytest.raises(FreezeError, match="already exists"):
            freeze_benchmark(ROOT, "0.1.0")

    def test_tamper_detection(self, tmp_path):
        import os

        frozen = ROOT / "dataset/requests/frozen/support-v0.1.0.jsonl"
        backup = tmp_path / "backup.jsonl"
        shutil.copy(frozen, backup)
        os.chmod(frozen, 0o644)
        try:
            original = frozen.read_text()
            frozen.write_text(original.replace("Tier 2", "Tier 4", 1))
            with pytest.raises(Exception, match="hash mismatch"):
                FrozenBenchmark(ROOT, MANIFEST)
        finally:
            frozen.write_text(backup.read_text())
            os.chmod(frozen, 0o444)
        FrozenBenchmark(ROOT, MANIFEST)  # restored


class TestRunAndRescore:
    def test_run_manifest_immutable(self, small_run):
        import os

        assert not os.access(small_run / "run-manifest.json", os.W_OK)

    def test_mocked_run_is_baseline_ineligible(self, small_run):
        manifest = json_read(small_run / "run-manifest.json")
        assert manifest["mocked"] is True
        assert manifest["baseline_eligible"] is False

    def test_all_cells_executed_and_traced(self, small_run):
        matrix = jsonl_read(small_run / "matrix.jsonl")
        results = jsonl_read(small_run / "cell-results.jsonl")
        assert {row["cell_id"] for row in matrix} == {row["cell_id"] for row in results}
        invocations = jsonl_read(small_run / "invocations.jsonl")
        assert invocations
        for record in invocations:
            assert record["messages"], "raw prompts retained"
            assert record["provider"] == "mock"

    def test_rescore_without_model(self, small_run, monkeypatch):
        # Rescoring must not construct any provider adapter.
        import lexstab.providers.registry as registry

        def _forbidden(*args, **kwargs):
            raise AssertionError("evaluation must not build providers")

        monkeypatch.setattr(registry, "build_provider", _forbidden)
        metrics_a = evaluate_run(ROOT, small_run, bootstrap_samples=100)
        hash_a = hash_file(small_run / "scores.jsonl")
        metrics_b = evaluate_run(ROOT, small_run, bootstrap_samples=100)
        assert hash_file(small_run / "scores.jsonl") == hash_a
        assert metrics_a["headline"] == metrics_b["headline"]

    def test_first_attempts_visible(self, small_run):
        scores = jsonl_read(small_run / "scores.jsonl")
        invalid = [row for row in scores if not row["schema_valid"]]
        for row in invalid:
            assert row["full_call_correct"] is False  # scored, not hidden


class TestRunnerEquivalence:
    def test_graph_matches_procedural(self, tmp_path):
        from lexstab.graphs.execution import compare_runners, graph_run_cell
        from lexstab.runner import run_cell

        config = load_run_config(ROOT / "config/run.smoke.yaml")
        for name, spec in config.raw["tracks"].items():
            enabled = name in ("boundary", "post_canonical")
            spec["enabled"] = enabled
            config.tracks[name]["enabled"] = enabled
        config.raw["selection"]["limit_cases"] = 1
        config.selection["limit_cases"] = 1
        dir_a = execute_run(ROOT, config, runs_dir=tmp_path, run_id="proc",
                            cell_runner=run_cell)
        dir_b = execute_run(ROOT, config, runs_dir=tmp_path, run_id="graph",
                            cell_runner=graph_run_cell)
        comparison = compare_runners(dir_a, dir_b)
        assert comparison["equivalent"], comparison["mismatched_cells"][:5]


class TestElicitation:
    def test_multi_turn_resolution(self, tmp_path):
        config = load_run_config(ROOT / "config/run.smoke.yaml")
        for name, spec in config.raw["tracks"].items():
            enabled = name == "intent_elicitation"
            spec["enabled"] = enabled
            config.tracks[name]["enabled"] = enabled
        run_dir = execute_run(ROOT, config, runs_dir=tmp_path, run_id="elicit")
        evaluate_run(ROOT, run_dir, bootstrap_samples=100)
        metrics = json_read(run_dir / "metrics.json")
        elicitation = metrics["elicitation"]
        assert "A1_DIRECT_CLARIFY" in elicitation
        # The gates and A1 must not act while unresolved fields remain (§31.7).
        for arch in ("A1_DIRECT_CLARIFY", "B_EXTERNAL_GATE", "B_EXTERNAL_GATE_GOLD"):
            assert elicitation[arch]["false_action_rate"] == 0.0
        # The scripted answers make at least one case resolvable within limits.
        assert any(
            (value.get("resolution_rate") or 0) > 0 for value in elicitation.values()
        )

    def test_gold_gate_uses_frozen_labels(self, tmp_path):
        bench = FrozenBenchmark(ROOT, MANIFEST)
        assert bench.elicitation  # frozen elicitation cases exist
        for case in bench.elicitation.values():
            assert case.gold_initial_labels["adequacy"] == "INADEQUATE"
