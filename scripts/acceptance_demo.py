"""Acceptance demonstration (spec §49.16) — all 16 steps, fully mocked.

Runs in a temporary copy of the workspace so the repository's own frozen
artifacts are never touched. Every step asserts its outcome; the script exits
nonzero on the first failure. Mocked results are wiring evidence only.

Run:  uv run python scripts/acceptance_demo.py [--workspace DIR]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lexstab import models  # noqa: E402
from lexstab.artifacts import DomainStore, json_read, jsonl_read, load_cases  # noqa: E402
from lexstab.authoring import (  # noqa: E402
    AuthoringContext,
    add_human_request,
    review_candidates,
    write_candidates,
)
from lexstab.config import load_models_config, load_run_config  # noqa: E402
from lexstab.discovery import discover_renderings  # noqa: E402
from lexstab.evaluate import evaluate_run  # noqa: E402
from lexstab.freeze import FrozenBenchmark, freeze_benchmark  # noqa: E402
from lexstab.hashing import hash_file  # noqa: E402
from lexstab.prompts import PromptLibrary  # noqa: E402
from lexstab.providers.registry import build_provider  # noqa: E402
from lexstab.redteam import run_redteam  # noqa: E402
from lexstab.regression import load_regression_suite, promote_to_regression  # noqa: E402
from lexstab.run import build_run_context, dry_run_report, execute_run  # noqa: E402


STEP_COUNT = 16
_step = 0


def step(message: str) -> None:
    global _step
    _step += 1
    print(f"\n[{_step:02d}/{STEP_COUNT}] {message}")


def check(condition: bool, message: str) -> None:
    if not condition:
        print(f"  FAIL: {message}")
        sys.exit(1)
    print(f"  ok: {message}")


def build_workspace(target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    (target / "pyproject.toml").write_text((REPO / "pyproject.toml").read_text())
    for directory in ("schemas", "prompts", "config"):
        shutil.copytree(REPO / directory, target / directory)
    dataset = target / "dataset"
    for sub in ("domain", "cases", "splits", "interfaces"):
        shutil.copytree(REPO / "dataset" / sub, dataset / sub)
    for sub in ("requests/approved", "requests/candidate", "requests/rejected",
                "renderings/approved", "renderings/candidate",
                "procedures/approved", "memory/glossaries", "elicitation"):
        source = REPO / "dataset" / sub
        if source.exists():
            shutil.copytree(source, dataset / sub)
    (dataset / "contexts").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "dataset" / "contexts" / "approved.jsonl",
                dataset / "contexts" / "approved.jsonl")
    (dataset / "manifests").mkdir()
    (target / "runs").mkdir()
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()
    workspace = Path(args.workspace) if args.workspace else Path(
        tempfile.mkdtemp(prefix="lexstab-acceptance-")
    )
    root = build_workspace(workspace / "ws")
    print(f"workspace: {root}")

    # ------------------------------------------------------------------ 1
    step("Add one adequate human-authored request and one inadequate request with frozen context")
    adequate = add_human_request(
        root, case_id="ESCALATE_001",
        text="This one needs to land on Tier 2's desk today: incident INC-1047.",
        semantic_role="INVARIANT", adequacy="ADEQUATE", ambiguity="UNAMBIGUOUS",
        expected_behavior="EXECUTE", lexical_equivalence="INVARIANT",
        axes=["idiomatic", "indirect_request", "typed"], creator="demo-operator",
    )
    inadequate = add_human_request(
        root, case_id="ESCALATE_001",
        text="Please push this one up the chain.",
        semantic_role="CLARIFICATION", adequacy="INADEQUATE", ambiguity="AMBIGUOUS",
        expected_behavior="CLARIFY", lexical_equivalence="NOT_APPLICABLE",
        axes=["idiomatic", "pronoun_or_coreference", "context_insufficient", "typed"],
        creator="demo-operator", context_id="CTX-EMPTY-001",
        missing_information=["entity_reference", "destination_tier"],
    )
    check(adequate["validation"]["status"] == "CANDIDATE", "human requests enter CANDIDATE status")

    # ------------------------------------------------------------------ 2
    step("Generate synthetic variants with a non-MUT authoring model")
    models_config = load_models_config(root / "config/models.mock.yaml")
    exec_model = models_config.role("execution_primary").model_id
    gen_model = models_config.role("authoring_generator").model_id
    check(exec_model != gen_model, f"authoring model ({gen_model}) differs from MUT ({exec_model})")
    providers = {
        name: build_provider(models_config.roles[name])
        for name in ("authoring_generator", "authoring_equivalence_critic",
                     "authoring_adversarial_critic", "failure_analyst")
    }
    ctx = AuthoringContext(
        root=root, domain=DomainStore.load(root), cases=load_cases(root),
        prompts=PromptLibrary(root / "prompts"), models_config=models_config,
        providers=providers, authoring_run_id=f"demo-authoring-{uuid.uuid4().hex[:6]}",
    )
    from lexstab.graphs.authoring import author_with_graph

    existing = jsonl_read(root / "dataset/requests/approved/support.jsonl")
    state = author_with_graph(ctx, case_ids=["ESCALATE_002"], axes=["operation_synonym", "entity_synonym"],
                              count_per_axis=3, existing=existing)
    synth_path = root / "dataset/requests/candidate/demo-synthetic.jsonl"
    count = write_candidates(state, synth_path)
    check(count > 0, f"{count} synthetic candidates written")

    # ------------------------------------------------------------------ 3
    step("Review and freeze the requests")
    approved_corpus = root / "dataset/requests/approved/support.jsonl"
    for source in (root / "dataset/requests/candidate/manual.jsonl", synth_path):
        result = review_candidates(
            source, reviewer_id="demo-reviewer", default_decision="APPROVE",
            notes="acceptance demo review",
            approved_output=approved_corpus,
            rejected_output=root / "dataset/requests/rejected/rejected.jsonl",
        )
        check(result["approved"] > 0, f"approved {result['approved']} from {source.name}")

    # ------------------------------------------------------------------ 4
    step("Discover and freeze a candidate model-facing rendering")
    discovery_provider = build_provider(models_config.role("execution_primary"))
    discovered = discover_renderings(
        root, DomainStore.load(root), models_config, discovery_provider,
        operation_ids=["ESCALATE_INCIDENT"], samples=30,
        output=root / "dataset/renderings/candidate/demo-discovery.jsonl",
    )
    check(len(discovered) == 1, "one rendering discovered from blind naming")
    check(discovered[0]["discovery"]["convergence_rate"] > 0.5, "convergence statistics recorded")
    rendering_row = {key: value for key, value in discovered[0].items() if not key.startswith("_")}
    rendering_row["validation"] = {"status": "APPROVED", "reviewed_by": ["demo-reviewer"],
                                   "approved_at": "2026-07-20T00:00:00Z"}
    models.Rendering.model_validate(rendering_row)
    approved_renderings = jsonl_read(root / "dataset/renderings/approved/support.jsonl")
    approved_renderings.append(rendering_row)
    from lexstab.artifacts import jsonl_write

    jsonl_write(root / "dataset/renderings/approved/support.jsonl", approved_renderings)

    # ------------------------------------------------------------------ 5
    step("Create and freeze one reusable procedure plus equivalent interface artifacts")
    from lexstab.interfaces import build_generic_interface, build_typed_interface, compare_interfaces

    domain = DomainStore.load(root)
    generic = build_generic_interface(domain)
    typed = build_typed_interface(domain)
    report = compare_interfaces(domain, generic, typed)
    check(report["equivalent"], "generic and typed interfaces verified equivalent")
    procedures = jsonl_read(root / "dataset/procedures/approved/support.jsonl")
    check(any("ESCALATE" in row["procedure_id"] for row in procedures),
          "escalation procedure present in approved corpus")

    # ------------------------------------------------------------------ 6
    step("Freeze benchmark version 0.1.0")
    manifest_path = freeze_benchmark(root, "0.1.0", created_at="2026-07-20T00:00:00Z")
    bench = FrozenBenchmark(root, manifest_path)
    check(adequate["request_id"] in bench.requests, "human adequate request frozen")
    check(inadequate["request_id"] in bench.requests, "human inadequate request frozen")
    check("REN-ESCALATE-INCIDENT-DISCOVERED-001" in bench.renderings, "discovered rendering frozen")
    try:
        freeze_benchmark(root, "0.1.0")
        check(False, "refreeze must fail")
    except Exception:
        check(True, "refreezing the same version without a dev override fails")

    # ------------------------------------------------------------------ 7
    step("Configure one execution model and a separate evaluation/criticism model")
    judge_model = models_config.role("evaluation_judge").model_id
    check(exec_model != judge_model, f"judge model ({judge_model}) differs from MUT ({exec_model})")

    # ------------------------------------------------------------------ 8
    step("Dry-run the matrix and display estimated cost")
    run_config = load_run_config(root / "config/run.smoke.yaml")
    run_config.raw["selection"]["limit_cases"] = 5
    run_config.raw["execution"]["repetitions"] = 2
    run_config.selection["limit_cases"] = 5
    run_config.execution["repetitions"] = 2
    ctx_run, matrix, _mc = build_run_context(root, run_config)
    dry = dry_run_report(matrix, run_config)
    print(f"  matrix cells: {dry['matrix_cells']}, estimated calls: {dry['estimated_model_calls']}, "
          f"estimated cost: ${dry['estimated_cost_usd_at_placeholder_rate']}")
    check(dry["matrix_cells"] > 0, "dry run produced a matrix and cost estimate without provider calls")

    # ------------------------------------------------------------------ 9 + 10
    step("Execute A0, A1, B-Runtime, B-Gold, C-Runtime, C-Gold on 5 cases with 2 repetitions")
    run_dir = execute_run(root, run_config, run_id="demo-primary")
    results = jsonl_read(run_dir / "cell-results.jsonl")
    executed_archs = {row["architecture"] for row in results}
    for arch in ("A0_DIRECT", "A1_DIRECT_CLARIFY", "B_RUNTIME", "B_GOLD", "C_RUNTIME", "C_GOLD"):
        check(arch in executed_archs, f"{arch} executed")
    case_count = len({row["case_id"] for row in results})
    check(case_count >= 5, f"{case_count} cases executed")
    reps = {row["repetition"] for row in results}
    check(reps == {0, 1}, "two repetitions per cell")

    step("Execute P0-P4 plus LP0, LP0G, LP1-LP3 with a representation ledger")
    for arch in ("P0_RAW_PROPOSAL", "P1_CLARIFY_PROPOSAL", "P2_CANONICAL_PROPOSAL",
                 "P2F_CANONICAL_FACTS_PROPOSAL",
                 "P3_CANONICAL_PROCEDURE_PROPOSAL", "P4_CANONICAL_PROCEDURE_TOOL",
                 "LP0_LANGUAGE_THROUGHOUT", "LP0G_GOLD_START_LANGUAGE", "LP1_CANONICAL_ONCE",
                 "LP2_CANONICAL_PROCEDURE", "LP3_CANONICAL_PROCEDURE_TOOL"):
        check(arch in executed_archs, f"{arch} executed")
    ledger = jsonl_read(run_dir / "representation-ledger.jsonl")
    lp_cells = {row["cell_id"] for row in results if row["architecture"].startswith("LP")}
    ledger_cells = {row["cell_id"] for row in ledger}
    check(lp_cells <= ledger_cells, "every persistence cell has representation-ledger records")

    # ------------------------------------------------------------------ 11
    step("Produce deterministic scores and a local trace")
    metrics = evaluate_run(root, run_dir, bootstrap_samples=300)
    check((run_dir / "scores.jsonl").exists(), "scores.jsonl written")
    check((run_dir / "invocations.jsonl").exists(), "invocation traces written")
    check(metrics["completion"]["completion_rate"] == 1.0, "no missing cells")

    # ------------------------------------------------------------------ 12
    step("Generate the report (A1 vs B/C, B-Gold vs C-Gold, adequacy strata, P transitions, LP0G vs LP1, complexity)")
    from lexstab.reporting.report import generate_report

    generate_report(root, run_dir)
    report_text = (run_dir / "report.md").read_text()
    for needle in ("Does the added architecture earn its complexity?",
                   "C_GOLD - B_GOLD", "LP1 canonical once - LP0G gold-start prose",
                   "P1 - P0", "adequate/varied", "MOCKED"):
        check(needle in report_text, f"report contains {needle!r}")

    # ------------------------------------------------------------------ 13
    step("Rescore the run without making provider calls")
    scores_hash_before = hash_file(run_dir / "scores.jsonl")
    metrics2 = evaluate_run(root, run_dir, bootstrap_samples=300)
    check(hash_file(run_dir / "scores.jsonl") == scores_hash_before,
          "rescoring reproduces identical scores from stored artifacts")
    check(metrics2["headline"] == metrics["headline"], "metrics identical on rescore")

    # ------------------------------------------------------------------ 14
    step("Generate red-team candidates from failures without changing the frozen report")
    report_hash_before = hash_file(run_dir / "report.md")
    redteam_output = root / "dataset/requests/candidate/redteam-demo.jsonl"
    redteam_report = run_redteam(ctx, run_dir, max_candidates=10, output=redteam_output)
    check(redteam_report["candidates_written"] > 0, "red-team candidates written")
    check(hash_file(run_dir / "report.md") == report_hash_before, "frozen report unchanged")
    check(hash_file(run_dir / "scores.jsonl") == scores_hash_before, "frozen scores unchanged")

    # ------------------------------------------------------------------ 15
    step("Promote one approved failure into a new regression-suite version")
    candidates = jsonl_read(redteam_output)
    promote_id = candidates[0]["request_id"]
    review_candidates(
        redteam_output, reviewer_id="demo-reviewer",
        decisions={promote_id: "APPROVE"},
        approved_output=root / "dataset/requests/candidate/redteam-approved.jsonl",
        rejected_output=root / "dataset/requests/rejected/rejected.jsonl",
    )
    suite_path = promote_to_regression(
        root, version="0.1.0", request_ids=[promote_id],
        candidate_corpus=root / "dataset/requests/candidate/redteam-approved.jsonl",
        discovering_run_id="demo-primary", reason="acceptance demo promotion",
        approved_by="demo-reviewer",
        base_benchmark_manifest="dataset/manifests/benchmark-v0.1.0.json",
    )
    suite = load_regression_suite(root, "0.1.0")
    check(suite["request_ids"] == [promote_id], f"regression suite v0.1.0 created at {suite_path.name}")

    # ------------------------------------------------------------------ 16
    step("Static-glossary vs retrieved-memory smoke ablation without changing the frozen primary score")
    memory_config = load_run_config(root / "config/run.smoke.yaml")
    for name, spec in memory_config.raw["tracks"].items():
        spec["enabled"] = name == "memory_ablation"
    memory_config.tracks["memory_ablation"]["enabled"] = True
    memory_config.raw["selection"]["limit_cases"] = 2
    memory_config.selection["limit_cases"] = 2
    for name in list(memory_config.tracks):
        if name != "memory_ablation":
            memory_config.tracks[name]["enabled"] = False
    memory_dir = execute_run(root, memory_config, run_id="demo-memory")
    evaluate_run(root, memory_dir, bootstrap_samples=100)
    memory_metrics = json_read(memory_dir / "metrics.json")
    memory_archs = {row["architecture"] for row in memory_metrics["headline"]}
    check({"M1_STATIC_GLOSSARY", "M2_RETRIEVED_MEMORY"} <= memory_archs,
          "M1 and M2 memory conditions executed")
    check(hash_file(run_dir / "scores.jsonl") == scores_hash_before,
          "primary frozen score untouched by memory ablation")

    print(f"\nACCEPTANCE DEMONSTRATION COMPLETE — all {STEP_COUNT} steps passed (mocked, offline).")
    print(f"workspace preserved at: {root}")


if __name__ == "__main__":
    main()
