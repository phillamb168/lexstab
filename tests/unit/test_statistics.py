"""Unit tests: statistical machinery (spec §39)."""

import pytest

from lexstab.metrics.aggregate import adequacy_matrix_cell
from lexstab.metrics.statistics import (
    benjamini_hochberg,
    case_level_sign_test,
    cluster_bootstrap_delta,
    cluster_bootstrap_rate,
    mcnemar_exact,
    practical_equivalence,
)


def test_bootstrap_rate_point_estimate():
    observations = [("c1", 1.0), ("c1", 0.0), ("c2", 1.0), ("c2", 1.0)]
    interval = cluster_bootstrap_rate(observations, samples=500, seed=7)
    assert interval.estimate == pytest.approx(0.75)
    assert interval.n_clusters == 2
    assert interval.low <= interval.estimate <= interval.high


def test_bootstrap_rate_empty():
    interval = cluster_bootstrap_rate([], samples=10)
    assert interval.estimate is None


def test_bootstrap_is_seed_deterministic():
    observations = [(f"c{i}", float(i % 2)) for i in range(20)]
    a = cluster_bootstrap_rate(observations, samples=300, seed=42)
    b = cluster_bootstrap_rate(observations, samples=300, seed=42)
    assert (a.low, a.high) == (b.low, b.high)


def test_bootstrap_delta_direction():
    paired = [(f"c{i}", 0.0, 1.0) for i in range(10)]
    interval = cluster_bootstrap_delta(paired, samples=200, seed=1)
    assert interval.estimate == pytest.approx(1.0)
    assert interval.low == pytest.approx(1.0)


def test_mcnemar_known_value():
    # b=1, c=9 -> exact two-sided p ≈ 0.0215
    assert mcnemar_exact(1, 9) == pytest.approx(0.021484375)
    assert mcnemar_exact(0, 0) is None
    assert mcnemar_exact(5, 5) == 1.0


def test_case_level_sign_test_collapses_repeated_cells_before_inference():
    paired = []
    for case_number in range(1, 8):
        paired.extend((f"c{case_number}", 0.0, 1.0) for _ in range(3))
    paired.extend(("c8", 1.0, 1.0) for _ in range(3))

    result = case_level_sign_test(paired)

    assert result["b_better_cases"] == 7
    assert result["a_better_cases"] == 0
    assert result["tied_cases"] == 1
    assert result["n_independent_cases"] == 8
    assert result["n_non_tied_cases"] == 7
    assert result["sign_p"] == pytest.approx(0.015625)


def test_benjamini_hochberg():
    result = benjamini_hochberg({"a": 0.001, "b": 0.02, "c": 0.9}, alpha=0.05)
    assert result["a"]["significant_at_fdr"]
    assert not result["c"]["significant_at_fdr"]
    assert result["a"]["bh_adjusted"] == pytest.approx(0.003)


def test_benjamini_hochberg_adjusted_values_are_monotone():
    result = benjamini_hochberg({"a": 0.01, "b": 0.011, "c": 0.5})
    ordered = [result[name]["bh_adjusted"] for name in ("a", "b", "c")]
    assert ordered == sorted(ordered)
    assert result["a"]["bh_adjusted"] == pytest.approx(0.0165)


def test_practical_equivalence_verdicts():
    from lexstab.metrics.statistics import Interval

    equivalent = practical_equivalence("x", Interval(0.0, -0.005, 0.005, 10, 100), 0.01)
    assert equivalent.verdict == "practically_equivalent"
    better = practical_equivalence("x", Interval(0.10, 0.05, 0.15, 10, 100), 0.01)
    assert better.verdict == "exceeds_practical_margin"
    worse = practical_equivalence("x", Interval(-0.10, -0.15, -0.05, 10, 100), 0.01)
    assert worse.verdict == "practically_worse"
    wide = practical_equivalence("x", Interval(0.0, -0.20, 0.20, 10, 100), 0.01)
    assert wide.verdict == "inconclusive"
    assert wide.practically_equivalent is False


def test_adequacy_matrix_cell_derivation():
    # D-017: rows from frozen labels, columns from lexical distance band
    assert adequacy_matrix_cell({"metadata": {
        "adequacy": "ADEQUATE", "ambiguity": "UNAMBIGUOUS", "lexical_distance_band": "LOW",
    }}) == "adequate/conventional"
    assert adequacy_matrix_cell({"metadata": {
        "adequacy": "ADEQUATE", "ambiguity": "UNAMBIGUOUS", "lexical_distance_band": "HIGH",
    }}) == "adequate/varied"
    assert adequacy_matrix_cell({"metadata": {
        "adequacy": "INADEQUATE", "ambiguity": "AMBIGUOUS", "lexical_distance_band": "LOW",
    }}) == "inadequate_or_ambiguous/conventional"
    assert adequacy_matrix_cell({"metadata": {
        "adequacy": "ADEQUATE", "ambiguity": "AMBIGUOUS", "lexical_distance_band": "MEDIUM",
    }}) == "inadequate_or_ambiguous/varied"
