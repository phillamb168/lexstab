"""Guardrails for the focused RMI persistence replication workflow."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from lexstab.artifacts import find_repo_root, json_read, jsonl_read, load_cases
from lexstab.authoring import review_candidates
from lexstab.freeze import FrozenBenchmark, freeze_benchmark
from lexstab.replication import (
    VARIANT_CATEGORIES,
    ReplicationError,
    author_rmi_variants,
    load_rmi_replication_seed,
    scaffold_rmi_replication,
    suggested_variant_texts,
)

ROOT = find_repo_root(Path(__file__))
SEED_PATH = ROOT / "dataset/replication/seeds/rmi-v0.3.0.json"


def _prepare_base(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "schemas", tmp_path / "schemas")
    for relative in (
        "dataset/domain/v0.2.1",
        "dataset/cases/support-v0.2.1",
        "dataset/interfaces/v0.2.1",
        "dataset/splits",
    ):
        source = ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
    elicitation = tmp_path / "dataset/elicitation/approved-v0.2.1.jsonl"
    elicitation.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ROOT / "dataset/elicitation/approved-v0.2.1.jsonl",
        elicitation,
    )


def _scaffold(tmp_path: Path):
    _prepare_base(tmp_path)
    seed = load_rmi_replication_seed(SEED_PATH)
    messages = {card.case_id: card.public_message for card in seed.cases}
    result = scaffold_rmi_replication(
        tmp_path,
        seed,
        reviewed_messages=messages,
        creator="phillip",
    )
    return seed, result


def test_scaffold_creates_versioned_sources_but_no_manifest(tmp_path):
    seed, result = _scaffold(tmp_path)

    assert result["case_count"] == 8
    assert not (tmp_path / "dataset/manifests/benchmark-v0.3.0.json").exists()
    cases = load_cases(tmp_path, "dataset/cases/support-v0.3.0")
    assert len(cases) == 20
    assert set(result["case_ids"]) == {card.case_id for card in seed.cases}

    validation = json_read(tmp_path / "dataset/splits/v0.3.0/validation.json")
    assert set(result["case_ids"]) <= set(validation["case_ids"])
    for case_id in result["case_ids"]:
        case = cases[case_id]
        incident_id = case.canonical.entity_id
        before = case.initial_state["incidents"][incident_id]
        after = case.gold.resulting_state["incidents"][incident_id]
        message = case.canonical.arguments["message"]
        assert case.family_id == "RMI_REPLICATION"
        assert case.gold.arguments["message"] == message
        assert after["assigned_team"] == before["assigned_team"]
        assert after["support_tier"] == before["support_tier"]
        assert after["status"] == "PENDING_INFO"
        assert after["awaiting_party"] == "REPORTER"
        assert after["last_public_comment"] == message
        assert after["reporter_notification_sent"] is True

    with pytest.raises(ReplicationError, match="refusing to overwrite"):
        scaffold_rmi_replication(
            tmp_path,
            seed,
            reviewed_messages={card.case_id: card.public_message for card in seed.cases},
            creator="phillip",
        )


def test_authoring_writes_exactly_three_guarded_candidates_per_case(tmp_path):
    _, result = _scaffold(tmp_path)
    cases = load_cases(tmp_path, "dataset/cases/support-v0.3.0")
    variant_texts = {
        case_id: suggested_variant_texts(cases[case_id])
        for case_id in result["case_ids"]
    }

    authored = author_rmi_variants(
        tmp_path,
        version="0.3.0",
        variant_texts=variant_texts,
        creator="phillip",
    )

    assert authored["request_count"] == 24
    assert not (tmp_path / "dataset/manifests/benchmark-v0.3.0.json").exists()
    rows = jsonl_read(tmp_path / authored["candidate_path"])
    assert len(rows) == 24
    by_case: dict[str, list[dict]] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(row)
        case = cases[row["case_id"]]
        message = case.canonical.arguments["message"]
        assert row["text"].count(message) == 1
        assert case.canonical.entity_id in row["text"]
        assert row["validation"]["status"] == "CANDIDATE"
        assert row["source"]["type"] == "human"
    assert set(by_case) == set(result["case_ids"])
    assert all(len(rows_for_case) == len(VARIANT_CATEGORIES) for rows_for_case in by_case.values())
    for rows_for_case in by_case.values():
        assert {row["labels"]["lexical_distance_band"] for row in rows_for_case} == {
            "LOW", "MEDIUM", "HIGH"
        }

    config = yaml.safe_load((tmp_path / authored["run_config_path"]).read_text())
    formal = config["tracks"]["progressive_formalization"]
    assert formal["persistence_conditions"] == [
        "LP0B_GOLD_START_LANGUAGE_BALANCED",
        "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM",
        "LP1_CANONICAL_ONCE",
    ]
    assert all(
        modes == ["gold"]
        for modes in formal["persistence_intent_modes"].values()
    )
    assert config["selection"]["case_ids"] == result["case_ids"]
    assert len(config["selection"]["request_ids"]) == 24


def test_noninteractive_cli_path_uses_same_guarded_builders(tmp_path, monkeypatch):
    import lexstab.cli as cli
    from typer.testing import CliRunner

    _prepare_base(tmp_path)
    monkeypatch.setattr(cli, "_root", lambda: tmp_path)
    seed_destination = tmp_path / "dataset/replication/seeds/rmi-v0.3.0.json"
    seed_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SEED_PATH, seed_destination)

    runner = CliRunner()
    scaffold_result = runner.invoke(
        cli.app,
        [
            "replication", "scaffold-rmi",
            "--creator", "phillip",
        ],
        input=("a\n" * 8) + "CREATE\n",
    )
    assert scaffold_result.exit_code == 0, scaffold_result.output
    assert "benchmark manifest: not created" in scaffold_result.output

    author_result = runner.invoke(
        cli.app,
        [
            "replication", "author-rmi-variants",
            "--creator", "phillip",
        ],
        input=("\n" * 24) + "WRITE\n",
    )
    assert author_result.exit_code == 0, author_result.output
    assert "24 guarded human request candidates" in author_result.output
    assert "benchmark manifest: not created" in author_result.output


def test_versioned_split_is_used_only_when_operator_freezes(tmp_path):
    shutil.copytree(ROOT / "schemas", tmp_path / "schemas")
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    shutil.copytree(ROOT / "dataset", tmp_path / "dataset")

    seed = load_rmi_replication_seed(SEED_PATH)
    scaffold = scaffold_rmi_replication(
        tmp_path,
        seed,
        reviewed_messages={card.case_id: card.public_message for card in seed.cases},
        creator="phillip",
    )
    cases = load_cases(tmp_path, "dataset/cases/support-v0.3.0")
    authored = author_rmi_variants(
        tmp_path,
        version="0.3.0",
        variant_texts={
            case_id: suggested_variant_texts(cases[case_id])
            for case_id in scaffold["case_ids"]
        },
        creator="phillip",
    )
    review_candidates(
        tmp_path / authored["candidate_path"],
        reviewer_id="phillip",
        default_decision="APPROVE",
        approved_output=tmp_path / "dataset/requests/approved/support.jsonl",
    )

    manifest_path = freeze_benchmark(
        tmp_path,
        "0.3.0",
        split_config="dataset/splits/v0.3.0",
        changelog=json_read(tmp_path / "dataset/manifests/changelog-v0.3.0.json"),
    )
    benchmark = FrozenBenchmark(tmp_path, manifest_path)
    assert len(benchmark.cases) == 20
    assert set(scaffold["case_ids"]) <= set(benchmark.manifest.splits["validation"])
