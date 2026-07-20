"""Integration tests: authoring, discovery, red team, regression promotion,
experiments, and CLI help (spec §49.3, §49.13, §49.15)."""

import subprocess
import sys
from pathlib import Path

import pytest

from lexstab.artifacts import DomainStore, find_repo_root, jsonl_read, load_cases
from lexstab.authoring import AuthoringContext
from lexstab.config import load_models_config
from lexstab.prompts import PromptLibrary
from lexstab.providers.registry import build_provider

ROOT = find_repo_root(Path(__file__))


@pytest.fixture()
def authoring_ctx():
    models_config = load_models_config(ROOT / "config/models.mock.yaml")
    providers = {
        name: build_provider(models_config.roles[name])
        for name in ("authoring_generator", "authoring_equivalence_critic",
                     "authoring_adversarial_critic", "failure_analyst")
    }
    return AuthoringContext(
        root=ROOT, domain=DomainStore.load(ROOT), cases=load_cases(ROOT),
        prompts=PromptLibrary(ROOT / "prompts"), models_config=models_config,
        providers=providers, authoring_run_id="itest-authoring",
    )


def test_authoring_graph_produces_reviewable_candidates(authoring_ctx, tmp_path):
    from lexstab.authoring import review_candidates, write_candidates
    from lexstab.graphs.authoring import author_with_graph

    state = author_with_graph(
        authoring_ctx, case_ids=["ESCALATE_001"],
        axes=["operation_synonym", "entity_synonym"], count_per_axis=3, existing=[],
    )
    assert state["accepted_candidates"]
    candidate_path = tmp_path / "candidates.jsonl"
    count = write_candidates(state, candidate_path)
    assert count == len(state["accepted_candidates"])
    for row in jsonl_read(candidate_path):
        assert row["validation"]["status"] in ("CANDIDATE", "NEEDS_REVIEW")
        assert row["source"]["type"] == "synthetic"
        # generator can never approve its own candidates (§49.3)
        assert row["validation"]["approved_by"] is None
    result = review_candidates(
        candidate_path, reviewer_id="itest-reviewer", default_decision="APPROVE",
        approved_output=tmp_path / "approved.jsonl",
        rejected_output=tmp_path / "rejected.jsonl",
    )
    assert result["approved"] == count
    for row in jsonl_read(tmp_path / "approved.jsonl"):
        assert row["validation"]["status"] == "APPROVED"
        assert row["validation"]["reviewers"]


def test_rendering_discovery_blind_and_statistical(tmp_path):
    from lexstab.discovery import discover_renderings

    models_config = load_models_config(ROOT / "config/models.mock.yaml")
    provider = build_provider(models_config.role("execution_primary"))
    prompts = PromptLibrary(ROOT / "prompts")
    prompt = prompts.get("lexical-convergence.v1")
    assert "candidate" not in prompt.body.lower().split("do not")[0].split("preferred_term")[0]
    renderings = discover_renderings(
        ROOT, DomainStore.load(ROOT), models_config, provider,
        operation_ids=["ESCALATE_INCIDENT", "REASSIGN_INCIDENT"], samples=20,
        output=tmp_path / "discovered.jsonl",
    )
    assert len(renderings) == 2
    for rendering in renderings:
        assert rendering["discovery"]["sample_count"] == 20
        assert 0 < rendering["discovery"]["convergence_rate"] <= 1
        assert rendering["validation"]["status"] == "CANDIDATE"


def test_regression_promotion_requires_approval(tmp_path):
    from lexstab.artifacts import jsonl_write
    from lexstab.regression import RegressionError, promote_to_regression

    row = jsonl_read(ROOT / "dataset/requests/frozen/support-v0.1.0.jsonl")[0]
    unapproved = dict(row)
    unapproved["validation"] = {**row["validation"], "status": "CANDIDATE", "reviewers": []}
    corpus = tmp_path / "corpus.jsonl"
    jsonl_write(corpus, [unapproved])
    with pytest.raises(RegressionError, match="not human-approved"):
        promote_to_regression(
            ROOT, version="99.99.99", request_ids=[row["request_id"]],
            candidate_corpus=corpus, discovering_run_id="x", reason="test",
            approved_by="t", base_benchmark_manifest="dataset/manifests/benchmark-v0.1.0.json",
        )


def test_regression_suite_is_executable_as_frozen_overlay(tmp_path):
    from lexstab.artifacts import json_write
    from lexstab.config import load_run_config
    from lexstab.hashing import hash_json_artifact
    from lexstab.run import execute_run

    row = jsonl_read(ROOT / "dataset/requests/frozen/support-v0.1.0.jsonl")[0]
    suite = {
        "schema_version": "1.2.0",
        "suite_id": "test-regression-suite",
        "suite_version": "test",
        "base_benchmark_manifest": "dataset/manifests/benchmark-v0.1.0.json",
        "promotion": {"approved_by": "test"},
        "request_ids": [row["request_id"]],
        "requests": [row],
        "request_hashes": {row["request_id"]: hash_json_artifact(row)},
    }
    suite_path = tmp_path / "regression-suite.json"
    json_write(suite_path, suite)
    config = load_run_config(ROOT / "config/run.smoke.yaml")
    config.benchmark_manifest = str(suite_path)
    for name, track in config.tracks.items():
        track["enabled"] = name == "boundary"
    run_dir = execute_run(ROOT, config, runs_dir=tmp_path, run_id="regression-overlay")
    matrix = jsonl_read(run_dir / "matrix.jsonl")
    assert matrix
    assert {cell["request_id"] for cell in matrix} == {row["request_id"]}


def test_experiments_run_offline(tmp_path):
    from lexstab.experiments.code import run_code_experiment
    from lexstab.experiments.grammar import run_grammar_experiment
    from lexstab.experiments.modality import run_modality_experiment

    grammar = run_grammar_experiment(
        ROOT, ROOT / "dataset/grammar/editing-corpus.jsonl",
        "config/models.mock.yaml", "definition_only", tmp_path / "grammar.jsonl",
    )
    assert grammar["items"] == 4 and grammar["parse_rate"] == 1.0
    code = run_code_experiment(
        ROOT, ROOT / "dataset/code/families.jsonl",
        "config/models.mock.yaml", tmp_path / "code.jsonl",
    )
    assert code["equivalence_failures"] == []
    assert code["full_test_pass_rate"] == 1.0
    modality = run_modality_experiment(
        ROOT, ROOT / "dataset/modality/artifact-chains.jsonl",
        "config/models.mock.yaml", tmp_path / "modality.jsonl",
    )
    assert modality["chains"] == 3
    assert set(modality["accuracy_by_artifact"]) == {"typed_text", "human_transcript", "asr_transcript"}


DOCUMENTED_COMMANDS = [
    ["--help"],
    ["doctor", "--help"],
    ["schema", "validate", "--help"],
    ["schema", "generate", "--help"],
    ["domain", "--help"],
    ["cases", "--help"],
    ["requests", "--help"],
    ["contexts", "--help"],
    ["renderings", "--help"],
    ["memory", "--help"],
    ["procedures", "--help"],
    ["integrity", "--help"],
    ["request", "add", "--help"],
    ["author", "requests", "--help"],
    ["review", "requests", "--help"],
    ["review", "renderings", "--help"],
    ["discover", "renderings", "--help"],
    ["procedure", "add", "--help"],
    ["procedure", "freeze", "--help"],
    ["interfaces", "build", "--help"],
    ["interfaces", "compare", "--help"],
    ["interfaces", "validate", "--help"],
    ["benchmark", "freeze", "--help"],
    ["benchmark", "verify", "--help"],
    ["run", "--help"],
    ["evaluate", "--help"],
    ["report", "--help"],
    ["judge", "--help"],
    ["redteam", "--help"],
    ["regression", "promote", "--help"],
    ["regression", "verify", "--help"],
    ["experiment", "grammar", "--help"],
    ["experiment", "code", "--help"],
    ["experiment", "modality", "--help"],
    ["langsmith-export", "--help"],
]


@pytest.mark.parametrize("command", DOCUMENTED_COMMANDS,
                         ids=[" ".join(cmd) for cmd in DOCUMENTED_COMMANDS])
def test_cli_help(command):
    """Every documented command has working --help (spec §49.13)."""
    result = subprocess.run(
        [sys.executable, "-m", "lexstab.cli", *command],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    )
    assert result.returncode == 0, result.stderr[-500:]
