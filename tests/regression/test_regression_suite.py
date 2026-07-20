"""Regression suite tests (spec §17.3, §45): fast CI-runnable checks of
previously observed, promoted failure patterns plus suite integrity."""

from pathlib import Path

import pytest

from lexstab.artifacts import find_repo_root
from lexstab.regression import load_regression_suite

ROOT = find_repo_root(Path(__file__))


def test_regression_suite_hash_integrity():
    path = ROOT / "dataset" / "manifests" / "regression-v0.1.0.json"
    if not path.exists():
        pytest.skip("no regression suite promoted yet in this workspace")
    suite = load_regression_suite(ROOT, "0.1.0")
    assert suite["promotion"]["discovering_run_id"]
    assert suite["request_ids"]


class TestKnownFailurePatterns:
    """Permanent deterministic checks derived from failures observed during
    harness development. Each one pins a fixed bug class (spec §17.3)."""

    def test_prompt_instruction_text_never_leaks_into_mock_sections(self):
        # Original failure: 'RESOLVED' in the canonicalizer prompt's JSON example
        # leaked into the USER REQUEST section and matched the CLOSE lexicon.
        from lexstab.providers.mockbrain import extract_section

        prompt = (
            "USER REQUEST\nPut INC-2210 in front of Tier 3.\n\n"
            "Return one JSON object.\n\nWhen exactly one mapping is supported:\n"
            '{\n  "status": "RESOLVED"\n}\n'
        )
        assert extract_section(prompt, "USER REQUEST") == "Put INC-2210 in front of Tier 3."

    def test_gold_injected_cells_score_execute_not_act(self):
        # Original failure: request-free gold cells compared behavior 'EXECUTE'
        # against gold decision literal 'ACT' and always scored wrong.
        from lexstab.evaluators.deterministic import expected_outcome
        from lexstab.freeze import FrozenBenchmark

        bench = FrozenBenchmark(ROOT, ROOT / "dataset/manifests/benchmark-v0.1.0.json")
        expected = expected_outcome(bench, bench.cases["ESCALATE_001"], None, "T0")
        assert expected["behavior"] == "EXECUTE"

    def test_combined_scripted_answers_match_any_order(self):
        # Original failure: sorted target join produced a key that never matched
        # the scripted 'a_and_b' answer key.
        from lexstab.freeze import FrozenBenchmark
        from lexstab.runner import _match_answer

        bench = FrozenBenchmark(ROOT, ROOT / "dataset/manifests/benchmark-v0.1.0.json")
        ecase = bench.elicitation["ELICIT-ESCALATE-001"]
        answer, keys = _match_answer(
            ecase, None, ["destination_tier", "entity_reference"]
        )
        assert answer == ecase.scripted_user_answers["entity_reference_and_destination_tier"]

    def test_agent_loop_canonical_propagation_preserves_arguments(self):
        # Original failure: AL_CANONICAL later stages received only prior typed
        # outputs, losing canonical arguments (amount_usd) and failing every cell.
        from lexstab.config import load_run_config
        from lexstab.run import execute_run
        from lexstab.artifacts import jsonl_read
        import tempfile

        config = load_run_config(ROOT / "config/run.smoke.yaml")
        for name, spec in config.raw["tracks"].items():
            enabled = name == "agent_loop"
            spec["enabled"] = enabled
            config.tracks[name]["enabled"] = enabled
        config.tracks["agent_loop"]["conditions"] = ["AL_CANONICAL"]
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = execute_run(ROOT, config, runs_dir=Path(tmp), run_id="al-regress")
            results = jsonl_read(run_dir / "cell-results.jsonl")
            assert results
            for row in results:
                assert row["decision"] == "ACT", row["cell_id"]
                assert row["tool_call"]["arguments"].get("amount_usd") == 120.0

    def test_lp_canonical_state_flows_downstream(self):
        # Original failure: LP1 stages received only prior typed outputs, losing
        # the canonical resolution and failing every non-refund case.
        from lexstab.config import load_run_config
        from lexstab.run import execute_run
        from lexstab.artifacts import jsonl_read
        import tempfile

        config = load_run_config(ROOT / "config/run.smoke.yaml")
        for name, spec in config.raw["tracks"].items():
            enabled = name == "progressive_formalization"
            spec["enabled"] = enabled
            config.tracks[name]["enabled"] = enabled
        formal = config.tracks["progressive_formalization"]
        formal["conditions"] = []
        formal["persistence_conditions"] = ["LP1_CANONICAL_ONCE"]
        config.raw["selection"]["limit_cases"] = 1
        config.selection["limit_cases"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = execute_run(ROOT, config, runs_dir=Path(tmp), run_id="lp1-regress")
            results = jsonl_read(run_dir / "cell-results.jsonl")
            gold_cells = [row for row in results if row["intent_mode"] == "gold"
                          and row["request_id"].endswith("-0001")]
            assert gold_cells
            for row in gold_cells:
                assert row["decision"] == "ACT", row["cell_id"]
