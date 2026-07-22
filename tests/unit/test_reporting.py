"""Reporting layer tests (spec §44, §49.14): end-to-end over the smoke run
plus pure-function checks for the table builders."""

from __future__ import annotations

from pathlib import Path

import pytest

from lexstab.reporting.html import markdown_to_html
from lexstab.reporting.markdown import (
    _CONCLUSION_NOT_MEASURED,
    _complexity_conclusion,
    _executive_summary,
    _measurement_validity_section,
)
from lexstab.reporting.report import generate_report
from lexstab.reporting.tables import (
    format_ci,
    headline_table,
    interpretation_verdict,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = REPO_ROOT / "runs" / "smoke-0001"


@pytest.fixture(scope="module")
def generated() -> list[Path]:
    if not RUN_DIR.exists():
        pytest.skip(f"{RUN_DIR} not present")
    return generate_report(REPO_ROOT, RUN_DIR)


def test_report_markdown_contents(generated: list[Path]) -> None:
    report = RUN_DIR / "report.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Does the added architecture earn its complexity?" in text
    assert "MOCKED SMOKE RUN" in text
    for architecture in (
        "A0_DIRECT", "A1_DIRECT_CLARIFY", "B_RUNTIME", "C_RUNTIME",
        "B_GOLD", "C_GOLD", "P0_RAW_PROPOSAL", "P4_CANONICAL_PROCEDURE_TOOL",
    ):
        assert architecture in text
    assert "Null and negative results" in text
    assert "Analysis labels" in text
    assert "procedure facts" in text


def test_component_summary_uses_information_parity_ablation_labels() -> None:
    metrics = {
        "component_ablations": [
            {
                "ablation": "procedure information (gold P2 vs unordered fact control)",
                "delta": {"estimate": 0.1},
                "verdict": "exceeds_practical_margin",
            },
            {
                "ablation": "procedure structure and named handle (fact control vs gold P3)",
                "delta": {"estimate": 0.2},
                "verdict": "exceeds_practical_margin",
            },
        ]
    }
    summary = "\n".join(
        _executive_summary(metrics, [], {"mocked": True, "repetitions": 1})
    )
    assert "procedure facts delta" in summary
    assert "procedure structure delta" in summary


def test_focused_run_does_not_receive_full_complexity_verdict() -> None:
    conclusion, winners = _complexity_conclusion({"primary_comparisons": []})
    assert conclusion == _CONCLUSION_NOT_MEASURED
    assert winners == []


def test_focused_summary_says_unconfigured_transitions_were_not_measured() -> None:
    metrics = {
        "formalization_transitions": [{
            "transition": "P1_CLARIFY_PROPOSAL -> P2_CANONICAL_PROPOSAL",
            "marginal_quality": {
                "delta": {"estimate": None},
                "verdict": "insufficient_data",
            },
        }],
    }
    summary = "\n".join(
        _executive_summary(metrics, [], {"mocked": False, "repetitions": 1})
    )
    assert "Progressive-formalization transitions were not measured" in summary


def test_measurement_validity_reports_collapsed_source_variants() -> None:
    metrics = {
        "effective_input_audit": {
            "groups": [{
                "architecture": "LP1_CANONICAL_ONCE",
                "intent_mode": "gold",
                "case_id": "CASE_1",
                "n_cells": 3,
                "n_source_requests": 3,
                "n_unique_first_model_inputs": 1,
                "source_lexical_distance_bands": ["HIGH", "LOW", "MEDIUM"],
                "classification": (
                    "SOURCE_VARIANTS_COLLAPSED_TO_IDENTICAL_MODEL_INPUT"
                ),
                "claim_scope": "does_not_test_source_lexical_variation",
            }],
        },
    }
    section = "\n".join(_measurement_validity_section(metrics))
    assert "stochastic repetitions" in section
    assert "does_not_test_source_lexical_variation" in section


def test_report_html_generated(generated: list[Path]) -> None:
    html_path = RUN_DIR / "report.html"
    assert html_path.exists()
    text = html_path.read_text(encoding="utf-8")
    assert "<table>" in text
    assert "does-the-added-architecture-earn-its-complexity" in text


def test_charts_generated(generated: list[Path]) -> None:
    pngs = sorted((RUN_DIR / "charts").glob("*.png"))
    assert len(pngs) >= 8, [png.name for png in pngs]
    svgs = sorted((RUN_DIR / "charts").glob("*.svg"))
    assert {png.stem for png in pngs} == {svg.stem for svg in svgs}


def test_tables_generated(generated: list[Path]) -> None:
    csvs = sorted((RUN_DIR / "tables").glob("*.csv"))
    assert csvs
    names = {path.name for path in csvs}
    assert "headline.csv" in names
    assert "primary-comparisons.csv" in names


def test_analysis_parquet_loadable(generated: list[Path]) -> None:
    import duckdb

    parquet = RUN_DIR / "tables" / "analysis-table.parquet"
    assert parquet.exists()
    source = str(parquet).replace("'", "''")
    rows = duckdb.sql(f"SELECT count(*) FROM read_parquet('{source}')").fetchone()[0]
    assert rows > 0
    columns = {
        row[0] for row in
        duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{source}')").fetchall()
    }
    assert "architecture" in columns
    assert "metadata_primary_h1" in columns


def test_report_metadata_written(generated: list[Path]) -> None:
    metadata = RUN_DIR / "report-metadata.json"
    assert metadata.exists()
    assert metadata in generated


def test_format_ci() -> None:
    assert format_ci({"estimate": 0.68, "ci_low": 0.55, "ci_high": 0.79}) == "0.68 [0.55, 0.79]"
    assert format_ci({"estimate": 0.5, "ci_low": None, "ci_high": None}) == "0.50"
    assert format_ci({"estimate": None}) == "n/a"
    assert format_ci(None) == "n/a"


def test_interpretation_verdict_names_the_blocking_gate() -> None:
    assert interpretation_verdict({
        "interpretation_allowed": False,
        "interpretation_warning": (
            "Causal interpretation withheld because 5 independent canonical "
            "case(s) were available; at least 6 are required."
        ),
    }) == "withheld: sample-size gate"
    assert interpretation_verdict({
        "interpretation_allowed": False,
        "failed_interpretation_cohorts": [{"architecture": "A0"}],
    }) == "withheld: schema-validity gate"


def test_headline_table_synthetic() -> None:
    metrics = {
        "headline": [{
            "track": "boundary",
            "architecture": "A0_DIRECT",
            "n_cells": 10,
            "full_call_accuracy": {
                "estimate": 0.8, "ci_low": 0.6, "ci_high": 0.9,
                "n_cases": 5, "n_observations": 10,
            },
            "final_state_accuracy": {
                "estimate": 0.7, "ci_low": 0.5, "ci_high": 0.85,
                "n_cases": 5, "n_observations": 10,
            },
            "operational_invariance": {"estimate": 0.4, "n_cases": 5},
            "contrast_accuracy": {
                "estimate": None, "ci_low": None, "ci_high": None,
                "n_cases": 0, "n_observations": 0,
            },
            "false_action_rate": 0.0,
            "clarification": {"precision": None, "recall": 0.0,
                              "unnecessary_clarification_rate": 0.1},
        }],
    }
    rows = headline_table(metrics)
    assert len(rows) == 1
    row = rows[0]
    assert row["architecture"] == "A0_DIRECT"
    assert row["full_call"] == "0.80 [0.60, 0.90]"
    assert row["full_call_estimate"] == 0.8
    assert row["full_call_n"] == 10
    assert row["final_state"] == "0.70 [0.50, 0.85]"
    assert row["invariance"] == "0.40 (n=5 cases)"
    assert row["contrast"] == "n/a"
    assert row["false_action"] == "0.00 (n=10)"
    assert row["unnecessary_clarification_rate"] == 0.1


def test_headline_table_empty_metrics() -> None:
    assert headline_table({}) == []


def test_markdown_converter_basics() -> None:
    html = markdown_to_html(
        "# Title\n\nSome **bold** and `code`.\n\n"
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n"
        "- item one\n- item two\n\n> warning\n\n![chart](charts/x.png)\n"
    )
    assert '<h1 id="title">Title</h1>' in html
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html
    assert "<tr><th>A</th><th>B</th></tr>" in html
    assert "<tr><td>1</td><td>2</td></tr>" in html
    assert "<li>item one</li>" in html
    assert "<blockquote>" in html
    assert '<img src="charts/x.png" alt="chart">' in html
