"""Integration tests: freeze immutability, execution, rescoring, runner
equivalence, and elicitation (spec §16.2, §18.7, §42.15, §49.16)."""

import shutil
from pathlib import Path

import pytest

from lexstab import models
from lexstab.artifacts import find_repo_root, json_read, jsonl_append, jsonl_read
from lexstab.config import load_run_config
from lexstab.evaluate import evaluate_run
from lexstab.freeze import FreezeError, FrozenBenchmark, freeze_benchmark
from lexstab.hashing import hash_file
from lexstab.run import build_run_context, execute_run
from lexstab.runner import CellResult, ProviderInvocationFailure

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

    def test_provider_failure_stops_run_and_disqualifies_baseline(self, tmp_path):
        config = load_run_config(ROOT / "config/run.smoke.yaml")
        for name, spec in config.raw["tracks"].items():
            enabled = name == "boundary"
            spec["enabled"] = enabled
            config.tracks[name]["enabled"] = enabled
        config.raw["selection"]["limit_cases"] = 1
        config.selection["limit_cases"] = 1
        config.raw["execution"]["concurrency"] = 1
        config.execution["concurrency"] = 1

        def fail_first_invocation(ctx, cell):
            result = CellResult(cell=cell, schema_valid=False)
            result.error_category = "provider_http_400"
            result.invocations.append(models.InvocationRecord(
                run_id=ctx.run_id,
                cell_id=cell.cell_id,
                role="execution_primary",
                provider="anthropic",
                requested_model_id="claude-test",
                timestamp="2026-07-20T00:00:00Z",
                messages=[{"role": "system", "content": "test"}],
                requested_parameters={},
                raw_response={"status": 400},
                finish_reason="http_400",
                parse_status="error",
                parse_error="provider HTTP 400",
            ))
            raise ProviderInvocationFailure(
                result, "provider_http_400", "provider HTTP 400"
            )

        run_dir = execute_run(
            ROOT,
            config,
            runs_dir=tmp_path,
            run_id="provider-failure",
            cell_runner=fail_first_invocation,
        )
        summary = json_read(run_dir / "run-summary.json")
        results = jsonl_read(run_dir / "cell-results.jsonl")
        assert summary["status"] == "provider_failure"
        assert summary["healthy"] is False
        assert summary["baseline_eligible"] is False
        assert summary["provider_error_calls"] == 1
        assert summary["aborted_cells"] == len(results) - 1
        assert {row["cell_id"] for row in results} == {
            row["cell_id"] for row in jsonl_read(run_dir / "matrix.jsonl")
        }


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
    def test_runtime_rendering_and_procedure_follow_resolved_contrast_operation(
        self, tmp_path
    ):
        config = load_run_config(ROOT / "config/run.v0.2-rmi-check.yaml")
        config.raw["model_config"] = "config/models.mock.yaml"
        config.model_config_path = "config/models.mock.yaml"
        for name, track in config.tracks.items():
            track["enabled"] = name in ("boundary", "progressive_formalization")
        config.tracks["boundary"]["architectures"] = ["C_RUNTIME"]
        formal = config.tracks["progressive_formalization"]
        formal["conditions"] = ["P3_CANONICAL_PROCEDURE_PROPOSAL"]
        formal["persistence_conditions"] = []
        formal["run_component_ablations"] = False
        formal["run_language_persistence_ablation"] = False
        config.selection["case_ids"] = ["CLOSE_001"]
        config.selection["request_ids"] = ["REQ-CLOSE-001-CONTRAST-0002"]

        ctx, matrix, _models = build_run_context(ROOT, config, run_id="selector-map")
        rendered_cell = next(
            cell for cell in matrix.cells if cell.architecture == "C_RUNTIME"
        )
        procedure_cell = next(
            cell for cell in matrix.cells
            if cell.architecture == "P3_CANONICAL_PROCEDURE_PROPOSAL"
        )
        assert rendered_cell.rendering_id is None
        assert rendered_cell.rendering_category == "CANONICAL_LABEL"
        assert procedure_cell.procedure_id is None
        assert procedure_cell.procedure_selector == "resolved_operation"

        message = "Please attach the missing diagnostic logs before we continue."
        resolution = {
            "mapping_outcome": "MAPPED",
            "canonical_intent": {
                "entity_type": "INCIDENT",
                "entity_id": "INC-2450",
                "operation_id": "REQUEST_MORE_INFORMATION",
                "arguments": {"incident_id": "INC-2450", "message": message},
            },
            "candidate_mappings": [],
            "question": None,
            "preserved_user_terms": [],
            "uncertainties": [],
        }
        proposal = {
            "decision": "ACT",
            "operation_id": "REQUEST_MORE_INFORMATION",
            "arguments": {"incident_id": "INC-2450", "message": message},
            "question": None,
            "reason_code": None,
        }
        script = {
            f"boundary_canonicalizer:{rendered_cell.cell_id}:canonicalizer": resolution,
            f"execution_primary:{rendered_cell.cell_id}:executor": {
                "__tool__": {
                    "tool": "request_more_information",
                    "arguments": {"incident_id": "INC-2450", "message": message},
                }
            },
            f"boundary_canonicalizer:{procedure_cell.cell_id}:canonicalizer": resolution,
            f"execution_primary:{procedure_cell.cell_id}:procedure_executor": proposal,
        }
        run_dir = execute_run(
            ROOT, config, runs_dir=tmp_path,
            run_id="runtime-resolved-artifacts", mock_script=script,
        )
        results = {
            row["architecture"]: row
            for row in jsonl_read(run_dir / "cell-results.jsonl")
        }
        rendered = results["C_RUNTIME"]
        expected_rendering = ctx.bench.rendering_for_operation(
            "REQUEST_MORE_INFORMATION", "CANONICAL_LABEL"
        )
        assert rendered["rendering_id"] == expected_rendering.rendering_id
        assert rendered["rendering_text"].startswith("Request more information")
        assert "Close incident" not in rendered["rendering_text"]
        procedure = results["P3_CANONICAL_PROCEDURE_PROPOSAL"]
        expected_procedure = ctx.bench.procedure_for_operation(
            "REQUEST_MORE_INFORMATION"
        )
        assert procedure["procedure_id"] == expected_procedure.procedure_id
        assert procedure["decision"] == "ACT"

    def test_invalid_v1_canonical_shape_stops_before_execution(self, tmp_path):
        config = load_run_config(ROOT / "config/run.smoke.yaml")
        for name, track in config.tracks.items():
            track["enabled"] = name == "boundary"
        config.tracks["boundary"]["architectures"] = ["B_RUNTIME"]
        config.selection["case_ids"] = ["ESCALATE_001"]
        config.selection["request_ids"] = ["REQ-ESCALATE-001-0001"]

        _ctx, matrix, _models = build_run_context(ROOT, config, run_id="find-cell")
        assert len(matrix.cells) == 1
        cell = matrix.cells[0]
        legacy_ambiguous_shape = {
            "status": "RESOLVED",
            "entity_type": "INCIDENT",
            "entity_id": "INC-1047",
            "operation_id": "ESCALATE_INCIDENT",
            "arguments": {"destination_tier": 2},
        }
        script = {
            f"boundary_canonicalizer:{cell.cell_id}:canonicalizer": legacy_ambiguous_shape
        }
        run_dir = execute_run(
            ROOT,
            config,
            runs_dir=tmp_path,
            run_id="invalid-canonical-shape",
            mock_script=script,
        )
        result = jsonl_read(run_dir / "cell-results.jsonl")[0]
        assert result["schema_valid"] is False
        assert result["error_category"] == "invalid_canonical_resolution"
        assert result["decision"] is None
        assert result["invocation_count"] == 1
        simulator_path = run_dir / "simulator-events.jsonl"
        simulator_events = jsonl_read(simulator_path) if simulator_path.exists() else []
        assert not [event for event in simulator_events if event["cell_id"] == cell.cell_id]

    def test_corrected_p3_lp3_and_call_balanced_persistence_contracts(self, tmp_path):
        config = load_run_config(ROOT / "config/run.smoke.yaml")
        for name, track in config.tracks.items():
            track["enabled"] = name == "progressive_formalization"
        formal = config.tracks["progressive_formalization"]
        formal["conditions"] = ["P3_CANONICAL_PROCEDURE_PROPOSAL"]
        formal["persistence_conditions"] = [
            "LP0B_GOLD_START_LANGUAGE_BALANCED",
            "LP1_CANONICAL_ONCE",
            "LP3_CANONICAL_PROCEDURE_TOOL",
        ]
        formal["run_component_ablations"] = False
        formal["run_language_persistence_ablation"] = True
        config.selection["case_ids"] = ["ESCALATE_001", "REFUND_001"]
        config.selection["request_ids"] = [
            "REQ-ESCALATE-001-0001",
            "REQ-REFUND-001-0001",
        ]
        run_dir = execute_run(ROOT, config, runs_dir=tmp_path, run_id="corrected-contracts")
        results = jsonl_read(run_dir / "cell-results.jsonl")

        p3 = [row for row in results if row["architecture"] == "P3_CANONICAL_PROCEDURE_PROPOSAL"]
        assert p3 and all(row["schema_valid"] for row in p3)
        assert all(row["proposal"] and "proposal" not in row["proposal"] for row in p3)

        lp3 = [row for row in results if row["architecture"] == "LP3_CANONICAL_PROCEDURE_TOOL"]
        assert lp3 and all(row["schema_valid"] for row in lp3)
        assert all(row["decision"] == "ACT" for row in lp3)
        assert {row["tool_call"]["tool"] for row in lp3} == {
            "escalate_incident",
            "refund_duplicate_charge",
        }

        balanced = next(
            row for row in results
            if row["architecture"] == "LP0B_GOLD_START_LANGUAGE_BALANCED"
            and row["intent_mode"] == "gold"
        )
        canonical_once = next(
            row for row in results
            if row["architecture"] == "LP1_CANONICAL_ONCE"
            and row["intent_mode"] == "gold"
        )
        assert balanced["invocation_count"] == canonical_once["invocation_count"] == 4
        evaluate_run(ROOT, run_dir, bootstrap_samples=100)
        metrics = json_read(run_dir / "metrics.json")
        balanced_bom = metrics["complexity"][
            "LP0B_GOLD_START_LANGUAGE_BALANCED|gold|none|none"
        ]
        canonical_bom = metrics["complexity"][
            "LP1_CANONICAL_ONCE|gold|none|none"
        ]
        assert balanced_bom["mutable_model_stages"] == 4
        assert canonical_bom["mutable_model_stages"] == 4

    def test_gold_clarification_short_circuits_all_formalization_executors(self, tmp_path):
        config = load_run_config(ROOT / "config/run.smoke.yaml")
        config.raw["benchmark_manifest"] = "dataset/manifests/benchmark-v0.2.0.json"
        config.benchmark_manifest = "dataset/manifests/benchmark-v0.2.0.json"
        for name, track in config.tracks.items():
            track["enabled"] = name == "progressive_formalization"
        formal = config.tracks["progressive_formalization"]
        formal["conditions"] = [
            "P2_CANONICAL_PROPOSAL",
            "P3_CANONICAL_PROCEDURE_PROPOSAL",
            "P4_CANONICAL_PROCEDURE_TOOL",
        ]
        formal["persistence_conditions"] = []
        formal["run_component_ablations"] = True
        formal["run_language_persistence_ablation"] = False
        config.selection["case_ids"] = ["ESCALATE_005"]
        config.selection["request_ids"] = ["REQ-ESCALATE-005-INADEQUATE-0001"]
        run_dir = execute_run(ROOT, config, runs_dir=tmp_path, run_id="gold-clarify")
        results = [
            row for row in jsonl_read(run_dir / "cell-results.jsonl")
            if row["intent_mode"] == "gold"
        ]
        assert results
        assert all(row["decision"] == "CLARIFY" for row in results)
        assert all(row["schema_valid"] for row in results)
        assert all(row["invocation_count"] == 0 for row in results)
        assert not any(row["tool_call"] or row["proposal"] for row in results)

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
