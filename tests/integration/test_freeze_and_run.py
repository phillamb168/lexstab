"""Integration tests: freeze immutability, execution, rescoring, runner
equivalence, and elicitation (spec §16.2, §18.7, §42.15, §49.16)."""

import shutil
from pathlib import Path

import pytest

from lexstab.artifacts import find_repo_root, json_read, jsonl_append, jsonl_read
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

    def test_simulator_events_are_joined_before_scoring(self, small_run, tmp_path):
        copied = tmp_path / "event-join"
        shutil.copytree(small_run, copied)
        bench = FrozenBenchmark(ROOT, MANIFEST)
        result = next(
            row for row in jsonl_read(copied / "cell-results.jsonl")
            if row.get("request_id")
            and bench.requests[row["request_id"]].labels.expected_behavior.value == "CLARIFY"
        )
        jsonl_append(copied / "simulator-events.jsonl", {
            "cell_id": result["cell_id"],
            "event_type": "attempted",
            "tool": "escalate_incident",
            "arguments": {},
        })
        evaluate_run(ROOT, copied, bootstrap_samples=50)
        score = next(
            row for row in jsonl_read(copied / "scores.jsonl")
            if row["cell_id"] == result["cell_id"]
        )
        assert score["false_action"] is True


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


class TestFormalizationControls:
    def test_information_parity_fact_control_is_explicit(self, tmp_path):
        config = load_run_config(ROOT / "config/run.smoke.yaml")
        for name, track in config.tracks.items():
            track["enabled"] = name == "progressive_formalization"
        formal = config.tracks["progressive_formalization"]
        formal["conditions"] = [
            "P2_CANONICAL_PROPOSAL", "P3_CANONICAL_PROCEDURE_PROPOSAL"
        ]
        formal["persistence_conditions"] = []
        formal["run_language_persistence_ablation"] = False
        config.selection["case_ids"] = ["ESCALATE_001"]
        config.selection["request_ids"] = ["REQ-ESCALATE-001-0001"]
        run_dir = execute_run(ROOT, config, runs_dir=tmp_path, run_id="parity")
        results = jsonl_read(run_dir / "cell-results.jsonl")
        p2f = [
            row for row in results
            if row["architecture"] == "P2F_CANONICAL_FACTS_PROPOSAL"
        ]
        assert p2f
        parity_hashes = {
            stage["output"]["common_facts_hash"]
            for row in results
            for stage in row["stage_outputs"]
            if stage["stage"] == "information_parity"
        }
        assert len(parity_hashes) == 1
        p2f_cells = {row["cell_id"] for row in p2f}
        p2f_prompts = [
            message["content"]
            for invocation in jsonl_read(run_dir / "invocations.jsonl")
            if invocation["cell_id"] in p2f_cells
            for message in invocation["messages"]
        ]
        assert p2f_prompts
        assert all("SKILL_" not in prompt for prompt in p2f_prompts)

    def test_lexical_drift_uses_independent_authoring_role(self, tmp_path):
        config = load_run_config(ROOT / "config/run.smoke.yaml")
        for name, track in config.tracks.items():
            track["enabled"] = name == "agent_loop"
        agent = config.tracks["agent_loop"]
        agent["conditions"] = ["AL_DRIFT"]
        agent["intent_modes"] = ["gold"]
        config.selection["request_ids"] = ["REQ-REFUND-001-0001"]
        run_dir = execute_run(ROOT, config, runs_dir=tmp_path, run_id="drift-role")
        results = jsonl_read(run_dir / "cell-results.jsonl")
        assert results
        for result in results:
            drift_stages = [
                stage for stage in result["stage_outputs"]
                if stage["stage"].endswith("_drift")
            ]
            assert len(drift_stages) == 3
            assert all(stage["valid"] for stage in drift_stages)
            labels = [stage["output"]["alternate_label"] for stage in drift_stages]
            assert len(labels) == len(set(labels))
        invocations = jsonl_read(run_dir / "invocations.jsonl")
        # Stage IDs are not a top-level invocation field, so identify the
        # generator calls by their isolated role.
        drift_calls = [row for row in invocations if row["role"] == "authoring_generator"]
        assert drift_calls
        assert all(row["requested_model_id"] == "mock-generator" for row in drift_calls)
        assert all(row["role"] != "execution_primary" for row in drift_calls)


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
        adequacy = metrics["adequacy_assessment"]
        assert "A1_DIRECT_CLARIFY" in elicitation
        # The gates and A1 must not act while unresolved fields remain (§31.7).
        for arch in ("A1_DIRECT_CLARIFY", "B_EXTERNAL_GATE", "B_EXTERNAL_GATE_GOLD"):
            assert elicitation[arch]["false_action_rate"] == 0.0
        assert adequacy["B_EXTERNAL_GATE"]["n_observations"] > 0
        assert adequacy["B_EXTERNAL_GATE_GOLD"]["estimate"] == 1.0
        # The scripted answers make at least one case resolvable within limits.
        assert any(
            (value.get("resolution_rate") or 0) > 0 for value in elicitation.values()
        )

    def test_gold_gate_uses_frozen_labels(self, tmp_path):
        bench = FrozenBenchmark(ROOT, MANIFEST)
        assert bench.elicitation  # frozen elicitation cases exist
        for case in bench.elicitation.values():
            assert case.gold_initial_labels["adequacy"] == "INADEQUATE"
