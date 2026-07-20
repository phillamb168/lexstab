"""Statistical machinery (spec §39).

The canonical case is the primary resampling unit: the cluster bootstrap
resamples cases with replacement and keeps every variant/repetition inside a
sampled case. Practical equivalence is an interval-inside-margin decision, not
a failure to reject (§39.8).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Callable, Sequence


@dataclass
class Interval:
    estimate: float | None
    low: float | None
    high: float | None
    n_clusters: int
    n_observations: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimate": self.estimate,
            "ci_low": self.low,
            "ci_high": self.high,
            "n_cases": self.n_clusters,
            "n_observations": self.n_observations,
        }


def _rate(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def cluster_bootstrap_rate(
    observations: list[tuple[str, float]],
    *,
    samples: int = 10000,
    confidence: float = 0.95,
    seed: int = 104729,
) -> Interval:
    """Bootstrap a mean rate clustering on (case_id, value) observations."""
    clusters: dict[str, list[float]] = {}
    for case_id, value in observations:
        clusters.setdefault(case_id, []).append(value)
    case_ids = sorted(clusters)
    values = [value for _cid, value in observations]
    if not case_ids:
        return Interval(None, None, None, 0, 0)
    estimate = _rate(values)
    if len(case_ids) == 1:
        return Interval(estimate, estimate, estimate, 1, len(values))
    rng = random.Random(seed)
    stats = []
    for _ in range(samples):
        sampled: list[float] = []
        for _ in case_ids:
            sampled.extend(clusters[case_ids[rng.randrange(len(case_ids))]])
        stats.append(_rate(sampled))
    stats.sort()
    alpha = (1 - confidence) / 2
    low = stats[int(alpha * len(stats))]
    high = stats[min(int((1 - alpha) * len(stats)), len(stats) - 1)]
    return Interval(estimate, low, high, len(case_ids), len(values))


def cluster_bootstrap_delta(
    paired: list[tuple[str, float, float]],
    *,
    samples: int = 10000,
    confidence: float = 0.95,
    seed: int = 104729,
) -> Interval:
    """Bootstrap the mean of (b - a) over paired observations clustered by case."""
    clusters: dict[str, list[float]] = {}
    for case_id, value_a, value_b in paired:
        clusters.setdefault(case_id, []).append(value_b - value_a)
    case_ids = sorted(clusters)
    deltas = [value_b - value_a for _cid, value_a, value_b in paired]
    if not case_ids:
        return Interval(None, None, None, 0, 0)
    estimate = _rate(deltas)
    if len(case_ids) == 1:
        return Interval(estimate, estimate, estimate, 1, len(deltas))
    rng = random.Random(seed)
    stats = []
    for _ in range(samples):
        sampled: list[float] = []
        for _ in case_ids:
            sampled.extend(clusters[case_ids[rng.randrange(len(case_ids))]])
        stats.append(_rate(sampled))
    stats.sort()
    alpha = (1 - confidence) / 2
    low = stats[int(alpha * len(stats))]
    high = stats[min(int((1 - alpha) * len(stats)), len(stats) - 1)]
    return Interval(estimate, low, high, len(case_ids), len(deltas))


def mcnemar_exact(b: int, c: int) -> float | None:
    """Exact two-sided McNemar p-value from discordant counts (secondary, §39.4)."""
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    total = 0.0
    for i in range(0, k + 1):
        total += math.comb(n, i)
    p = 2.0 * total / (2**n)
    return min(1.0, p)


def benjamini_hochberg(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, dict[str, Any]]:
    """BH FDR correction for exploratory comparison families (§39.6)."""
    items = sorted(
        ((name, p) for name, p in pvalues.items() if p is not None), key=lambda item: item[1]
    )
    m = len(items)
    out: dict[str, dict[str, Any]] = {}
    max_significant_rank = 0
    for rank, (name, p) in enumerate(items, start=1):
        if p <= alpha * rank / m:
            max_significant_rank = rank
    raw_adjusted = [min(1.0, p * m / rank) for rank, (_name, p) in enumerate(items, start=1)]
    # BH adjusted values are the reverse cumulative minimum of the raw
    # rank-scaled values. Without this monotonicity step, adjacent hypotheses
    # can receive invalid, decreasing adjusted p-values.
    adjusted_values = list(raw_adjusted)
    for index in range(len(adjusted_values) - 2, -1, -1):
        adjusted_values[index] = min(adjusted_values[index], adjusted_values[index + 1])
    for rank, ((name, p), adjusted) in enumerate(zip(items, adjusted_values), start=1):
        out[name] = {
            "p": p,
            "bh_adjusted": adjusted,
            "significant_at_fdr": rank <= max_significant_rank,
        }
    return out


@dataclass
class EquivalenceDecision:
    comparison: str
    delta: Interval
    margin: float
    practically_equivalent: bool | None
    exceeds_margin: bool | None
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison": self.comparison,
            "delta": self.delta.to_dict(),
            "margin": self.margin,
            "practically_equivalent": self.practically_equivalent,
            "exceeds_margin": self.exceeds_margin,
            "verdict": self.verdict,
        }


def practical_equivalence(
    comparison: str, delta: Interval, margin: float
) -> EquivalenceDecision:
    """Interval-in-margin equivalence decision (§39.8). Quality is practically
    equivalent only when the entire interval lies inside ±margin."""
    if delta.estimate is None or delta.low is None or delta.high is None:
        return EquivalenceDecision(comparison, delta, margin, None, None, "insufficient_data")
    equivalent = -margin <= delta.low and delta.high <= margin
    exceeds = delta.low > margin  # whole interval above the margin: real improvement
    if equivalent:
        verdict = "practically_equivalent"
    elif exceeds:
        verdict = "exceeds_practical_margin"
    elif delta.high < -margin:
        verdict = "practically_worse"
    else:
        verdict = "inconclusive"
    return EquivalenceDecision(comparison, delta, margin, equivalent, exceeds, verdict)


def paired_discordance(paired: list[tuple[str, float, float]]) -> dict[str, int]:
    b = sum(1 for _c, a, bb in paired if a == 1 and bb == 0)
    c = sum(1 for _c, a, bb in paired if a == 0 and bb == 1)
    return {"a_only_correct": b, "b_only_correct": c, "mcnemar_p": mcnemar_exact(b, c)}
