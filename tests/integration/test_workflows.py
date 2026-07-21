"""Integration tests: authoring, discovery, red team, regression promotion,
experiments, and CLI help (spec §49.3, §49.13, §49.15)."""

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from lexstab.artifacts import (
    DomainStore,
    find_repo_root,
    json_read,
    jsonl_read,
    jsonl_write,
    load_cases,
)
from lexstab.authoring import AuthoringContext
from lexstab.config import load_models_config
from lexstab.prompts import PromptLibrary
from lexstab.providers.registry import build_provider

ROOT = find_repo_root(Path(__file__))


def _request_review_fixture(request_id: str) -> dict:
    """Return a completed source row reset to the pre-review candidate state."""
    approved = jsonl_read(ROOT / "dataset/requests/approved/support.jsonl")
    row = copy.deepcopy(next(row for row in approved if row["request_id"] == request_id))
    row["validation"] = {
        **row["validation"],
        "status": "CANDIDATE",
        "reviewers": [],
        "approved_by": None,
        "approved_at": None,
        "adequacy_verified": None,
        "ambiguity_verified": None,
    }
    return row


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


def test_request_approval_atomically_supersedes_named_active_rows(tmp_path):
    from lexstab.authoring import review_candidates

    existing = jsonl_read(ROOT / "dataset/requests/approved/support.jsonl")
    target = next(
        row for row in existing
        if row["request_id"] == "REQ-CLOSE-001-CONTRAST-0002"
    )
    target = copy.deepcopy(target)
    target["validation"] = {**target["validation"], "status": "APPROVED"}
    candidate = _request_review_fixture("REQ-CLOSE-001-CONTRAST-0003")
    approved_path = tmp_path / "approved.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    jsonl_write(approved_path, [target])
    jsonl_write(candidate_path, [candidate])

    result = review_candidates(
        candidate_path,
        reviewer_id="phillip",
        default_decision="APPROVE",
        approved_output=approved_path,
        rejected_output=tmp_path / "rejected.jsonl",
    )

    assert result == {"approved": 1, "rejected": 0, "deferred": 0}
    by_id = {row["request_id"]: row for row in jsonl_read(approved_path)}
    assert by_id[target["request_id"]]["validation"]["status"] == "SUPERSEDED"
    assert by_id[candidate["request_id"]]["validation"]["status"] == "APPROVED"
    assert any(
        review["decision"] == "SUPERSEDE"
        for review in by_id[target["request_id"]]["validation"]["reviewers"]
    )


def test_request_approval_refuses_unknown_supersession_target(tmp_path):
    from lexstab.authoring import review_candidates

    candidate = _request_review_fixture("REQ-ESCALATE-001-0009")
    candidate = {
        **candidate,
        "provenance": {
            **candidate["provenance"],
            "supersedes_request_ids": ["REQ-DOES-NOT-EXIST-0001"],
        },
    }
    candidate_path = tmp_path / "candidate.jsonl"
    approved_path = tmp_path / "approved.jsonl"
    jsonl_write(candidate_path, [candidate])
    jsonl_write(approved_path, [])

    with pytest.raises(ValueError, match="unknown superseded requests"):
        review_candidates(
            candidate_path,
            reviewer_id="phillip",
            default_decision="APPROVE",
            approved_output=approved_path,
        )


def test_interactive_request_review_shows_complete_decision_context(
    tmp_path, monkeypatch,
):
    import lexstab.cli as cli
    from typer.testing import CliRunner

    candidates = [
        _request_review_fixture("REQ-ESCALATE-001-0009"),
        _request_review_fixture("REQ-CLOSE-001-CONTRAST-0003"),
    ]
    candidate_path = tmp_path / "corrective-v0.2.1.jsonl"
    jsonl_write(candidate_path, candidates)
    monkeypatch.setattr(cli, "_root", lambda: tmp_path)

    result = CliRunner().invoke(
        cli.app,
        [
            "review", "requests",
            "--input", str(candidate_path),
            "--reviewer", "phillip",
            "--interactive",
        ],
        input="d\nd\n",
    )

    assert result.exit_code == 0, result.output
    assert "semantic role: INVARIANT" in result.output
    assert "expected behavior: EXECUTE" in result.output
    assert "lexical equivalence: INVARIANT" in result.output
    assert "variation axes: indirect_request, syntactic_paraphrase" in result.output
    assert (
        "supersedes on approval: REQ-ESCALATE-001-CLARIFY-OWNERSHIP-0001"
        in result.output
    )
    assert "contrast operation: REQUEST_MORE_INFORMATION" in result.output
    assert (
        "Which version of the client was installed when the incident occurred?"
        in result.output
    )
    assert "[d]efer" in result.output
    assert "contains_organizatio" not in result.output


def test_rendering_discovery_blind_and_statistical(tmp_path):
    from lexstab.discovery import discover_renderings

    models_config = load_models_config(ROOT / "config/models.mock.yaml")
    provider = build_provider(models_config.role("execution_primary"))
    prompts = PromptLibrary(ROOT / "prompts")
    prompt = prompts.get("operation-lexical-convergence.v1")
    assert "candidate" not in prompt.body.lower().split("do not")[0].split("preferred_term")[0]
    operation_ids = [
        "ESCALATE_INCIDENT", "REASSIGN_INCIDENT", "CLOSE_INCIDENT",
        "REQUEST_MORE_INFORMATION", "REQUEST_APPROVAL", "REFUND_DUPLICATE_CHARGE",
        "REQUEST_MANAGER_REVIEW", "SUSPEND_ACCOUNT",
    ]
    renderings = discover_renderings(
        ROOT, DomainStore.load(ROOT), models_config, provider,
        operation_ids=operation_ids, samples=20,
        output=tmp_path / "discovered.jsonl",
    )
    assert len(renderings) == len(operation_ids)
    for rendering in renderings:
        assert rendering["discovery"]["sample_count"] == 20
        assert 0 < rendering["discovery"]["convergence_rate"] <= 1
        assert rendering["validation"]["status"] == "CANDIDATE"
        canonical = next(
            row for row in jsonl_read(ROOT / "dataset/renderings/approved/support.jsonl")
            if row["operation_id"] == rendering["operation_id"]
            and row["category"] == "CANONICAL_LABEL"
        )
        reference_span = rendering["discovery"].get(
            "reference_template_label_span", canonical["label"]
        )
        assert rendering["template"][len(rendering["label"]):] == canonical["template"][len(reference_span):]


def test_rendering_discovery_checkpoints_and_resumes_paid_samples(tmp_path):
    from lexstab.discovery import discover_renderings
    from lexstab.providers.local import MockProvider

    class CountingMockProvider(MockProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def _call_once(self, **kwargs):
            self.calls += 1
            return super()._call_once(**kwargs)

    models_config = load_models_config(ROOT / "config/models.mock.yaml")
    provider = CountingMockProvider()
    output = tmp_path / "resumable.jsonl"
    operation_ids = ["ESCALATE_INCIDENT", "CLOSE_INCIDENT"]
    first = discover_renderings(
        ROOT,
        DomainStore.load(ROOT),
        models_config,
        provider,
        operation_ids=operation_ids,
        samples=3,
        output=output,
    )
    assert len(first) == 2
    assert provider.calls == 6
    assert len(jsonl_read(tmp_path / "resumable.samples.jsonl")) == 6

    second = discover_renderings(
        ROOT,
        DomainStore.load(ROOT),
        models_config,
        provider,
        operation_ids=operation_ids,
        samples=3,
        output=output,
    )
    assert len(second) == 2
    assert provider.calls == 6
    audit = json_read(tmp_path / "resumable.summary.json")["checkpoint_audit"]
    assert audit["attempt_rows"] == 6
    assert audit["unique_sample_keys"] == 6
    assert audit["superseded_attempts"] == 0


def test_rendering_discovery_preserves_invalid_samples_and_fails_fast(tmp_path):
    from lexstab.discovery import DiscoveryError, discover_renderings
    from lexstab.providers.base import ProviderResponse
    from lexstab.providers.local import MockProvider

    class InvalidMockProvider(MockProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def _kind_lexical_name(self, text, metadata):
            self.calls += 1
            return ProviderResponse(
                raw={"mock": True, "content": "not-json"},
                text="not-json",
                tool_calls=[],
                tool_call_mode="mock",
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                finish_reason="stop",
                reported_model_id="mock",
            )

    models_config = load_models_config(ROOT / "config/models.mock.yaml")
    provider = InvalidMockProvider()
    output = tmp_path / "invalid.jsonl"
    with pytest.raises(DiscoveryError, match="no valid structured responses"):
        discover_renderings(
            ROOT,
            DomainStore.load(ROOT),
            models_config,
            provider,
            operation_ids=["CLOSE_INCIDENT"],
            samples=50,
            output=output,
        )
    assert provider.calls == 5
    checkpoint = jsonl_read(tmp_path / "invalid.samples.jsonl")
    assert len(checkpoint) == 5
    assert {row["status"] for row in checkpoint} == {"INVALID"}


def test_rendering_review_can_approve_and_defer_independently(tmp_path):
    from lexstab.discovery import discover_renderings, review_rendering_candidates

    models_config = load_models_config(ROOT / "config/models.mock.yaml")
    provider = build_provider(models_config.role("execution_primary"))
    candidates_path = tmp_path / "candidates.jsonl"
    candidates = discover_renderings(
        ROOT,
        DomainStore.load(ROOT),
        models_config,
        provider,
        operation_ids=["ESCALATE_INCIDENT", "CLOSE_INCIDENT"],
        samples=2,
        output=candidates_path,
    )
    existing_discovered = next(
        row for row in jsonl_read(ROOT / "dataset/renderings/approved/support.jsonl")
        if row["category"] == "MODEL_DISCOVERED"
    )
    approved_path = tmp_path / "approved.jsonl"
    rejected_path = tmp_path / "rejected.jsonl"
    jsonl_write(approved_path, [existing_discovered])
    by_operation = {row["operation_id"]: row for row in candidates}

    result = review_rendering_candidates(
        candidates_path,
        approved_path,
        rejected_path,
        reviewer="phillip",
        decisions={
            by_operation["ESCALATE_INCIDENT"]["rendering_id"]: "DEFER",
            by_operation["CLOSE_INCIDENT"]["rendering_id"]: "APPROVE",
        },
    )
    assert result == {"approved": 1, "rejected": 0, "deferred": 1}
    remaining = jsonl_read(candidates_path)
    assert [row["operation_id"] for row in remaining] == ["ESCALATE_INCIDENT"]
    assert remaining[0]["validation"]["status"] == "NEEDS_REVIEW"
    approved = jsonl_read(approved_path)
    assert any(row["operation_id"] == "CLOSE_INCIDENT" for row in approved)


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
    from lexstab.experiments.canonical_envelope import run_canonical_envelope_diagnostic
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
    envelope = run_canonical_envelope_diagnostic(
        ROOT,
        ROOT / "dataset/manifests/benchmark-v0.1.0.json",
        ROOT / "config/models.mock.yaml",
        tmp_path / "canonical-envelope.jsonl",
        case_ids=["ESCALATE_001"],
    )
    assert envelope["headline_eligible"] is False
    assert len(jsonl_read(tmp_path / "canonical-envelope.jsonl")) == 3


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
    ["experiment", "canonical-envelope", "--help"],
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
