"""Required report visualizations (spec §44.6).

Every chart function takes ``(metrics, scores, out_dir)``, writes PNG and SVG
under ``runs/<id>/charts/``, and returns the PNG path — or ``None`` when the
run lacks the data for that view. Ordering is deterministic (sorted keys).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

_BAR_COLOR = "#4878a8"
_ACCENT_COLOR = "#b0413e"


def _save(fig, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{name}.png"
    fig.savefig(png, dpi=120, bbox_inches="tight")
    fig.savefig(out_dir / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)
    return png


def _family(score: dict) -> str:
    family = score.get("metadata", {}).get("family_id")
    if family:
        return family
    return score["case_id"].split("_", 1)[0]


def accuracy_by_architecture(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    rows = [
        row for row in metrics.get("headline", [])
        if (row.get("full_call_accuracy") or {}).get("estimate") is not None
    ]
    if not rows:
        return None
    labels = [f"{row['architecture']}\n({row['track']})" for row in rows]
    estimates = [row["full_call_accuracy"]["estimate"] for row in rows]
    lows = [est - (row["full_call_accuracy"].get("ci_low") or est)
            for est, row in zip(estimates, rows)]
    highs = [(row["full_call_accuracy"].get("ci_high") or est) - est
             for est, row in zip(estimates, rows)]
    fig, ax = plt.subplots(figsize=(max(8, 0.7 * len(rows)), 4.5))
    ax.bar(range(len(rows)), estimates, yerr=[lows, highs], capsize=3, color=_BAR_COLOR)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels(labels, rotation=90, fontsize=7)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("full-call accuracy")
    ax.set_title("Full-call accuracy by architecture (case-clustered 95% CI)")
    return _save(fig, out_dir, "accuracy_by_architecture")


def paired_bgold_cgold_deltas(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    def _case_rates(arch: str) -> dict[str, float]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for score in scores:
            if score["architecture"] == arch and score.get("full_call_correct") is not None:
                grouped[score["case_id"]].append(1.0 if score["full_call_correct"] else 0.0)
        return {case: sum(vals) / len(vals) for case, vals in grouped.items()}

    b_gold = _case_rates("B_GOLD")
    c_gold = _case_rates("C_GOLD")
    cases = sorted(set(b_gold) & set(c_gold))
    if not cases:
        return None
    deltas = [c_gold[case] - b_gold[case] for case in cases]
    fig, ax = plt.subplots(figsize=(7, max(3, 0.4 * len(cases))))
    ax.scatter(deltas, range(len(cases)), color=_BAR_COLOR, zorder=3)
    ax.axvline(0.0, color="gray", linewidth=1)
    ax.set_yticks(range(len(cases)))
    ax.set_yticklabels(cases, fontsize=8)
    ax.set_xlabel("C_GOLD - B_GOLD full-call accuracy delta")
    ax.set_title("Paired B_GOLD vs C_GOLD per-case deltas")
    return _save(fig, out_dir, "paired_bgold_cgold_deltas")


def worst_variant_by_family(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    robustness = metrics.get("robustness") or {}
    per_family: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for arch, entry in sorted(robustness.items()):
        for case_id, info in sorted((entry.get("worst_variants_by_case") or {}).items()):
            value = info.get("worst_variant_accuracy")
            if value is not None:
                per_family[case_id.split("_", 1)[0]][arch].append(value)
    if not per_family:
        return None
    families = sorted(per_family)
    archs = sorted({arch for by_arch in per_family.values() for arch in by_arch})
    fig, ax = plt.subplots(figsize=(max(7, 1.2 * len(families)), 4.5))
    width = 0.8 / max(1, len(archs))
    for index, arch in enumerate(archs):
        values = [
            sum(per_family[family].get(arch, [])) / len(per_family[family][arch])
            if per_family[family].get(arch) else 0.0
            for family in families
        ]
        ax.bar([i + index * width for i in range(len(families))], values,
               width=width, label=arch)
    ax.set_xticks([i + 0.4 for i in range(len(families))])
    ax.set_xticklabels(families)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("worst-variant accuracy")
    ax.set_title("Worst-variant accuracy by operation family")
    ax.legend(fontsize=6, ncol=2)
    return _save(fig, out_dir, "worst_variant_by_family")


def clarification_precision_recall(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    points = []
    for row in metrics.get("headline", []):
        clar = row.get("clarification") or {}
        if clar.get("precision") is not None and clar.get("recall") is not None:
            points.append((row["architecture"], row["track"], clar["recall"], clar["precision"]))
    if not points:
        return None
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    for arch, track, recall, precision in sorted(points):
        ax.scatter(recall, precision, color=_BAR_COLOR, zorder=3)
        ax.annotate(f"{arch} ({track})", (recall, precision), fontsize=7,
                    xytext=(4, 4), textcoords="offset points")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("clarification recall")
    ax.set_ylabel("clarification precision")
    ax.set_title("Clarification precision vs recall by architecture")
    return _save(fig, out_dir, "clarification_precision_recall")


def contrast_vs_invariance(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    points = []
    for row in metrics.get("headline", []):
        contrast = (row.get("contrast_accuracy") or {}).get("estimate")
        invariance = (row.get("operational_invariance") or {}).get("estimate")
        if contrast is not None and invariance is not None:
            points.append((row["architecture"], contrast, invariance))
    if not points:
        return None
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    for arch, contrast, invariance in sorted(points):
        ax.scatter(contrast, invariance, color=_BAR_COLOR, zorder=3)
        ax.annotate(arch, (contrast, invariance), fontsize=7,
                    xytext=(4, 4), textcoords="offset points")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("contrast (semantic discrimination) accuracy")
    ax.set_ylabel("operational invariance")
    ax.set_title("Contrast accuracy vs operational invariance\n(the desirable region is high on both axes)")
    return _save(fig, out_dir, "contrast_vs_invariance")


def first_divergence_distribution(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    persistence = metrics.get("persistence") or {}
    conditions = sorted(
        arch for arch, entry in persistence.items()
        if entry.get("first_divergence_distribution")
    )
    if not conditions:
        return None
    stages = sorted({
        stage for arch in conditions
        for stage in persistence[arch]["first_divergence_distribution"]
    })
    fig, ax = plt.subplots(figsize=(max(7, 1.4 * len(conditions)), 4.5))
    bottoms = [0.0] * len(conditions)
    for stage in stages:
        values = [
            persistence[arch]["first_divergence_distribution"].get(stage, 0)
            for arch in conditions
        ]
        ax.bar(range(len(conditions)), values, bottom=bottoms, label=stage)
        bottoms = [b + v for b, v in zip(bottoms, values)]
    ax.set_xticks(range(len(conditions)))
    ax.set_xticklabels(conditions, rotation=30, ha="right", fontsize=7)
    ax.set_ylabel("trajectories")
    ax.set_title("First-divergence stage distribution by persistence condition")
    ax.legend(fontsize=7)
    return _save(fig, out_dir, "first_divergence_distribution")


def model_by_rendering_heatmap(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for score in scores:
        rendering = score.get("rendering_id")
        if rendering and score.get("full_call_correct") is not None:
            grouped[(score["architecture"], rendering)].append(
                1.0 if score["full_call_correct"] else 0.0
            )
    renderings = sorted({rendering for _arch, rendering in grouped})
    if len(renderings) < 2:
        return None
    archs = sorted({arch for arch, _rendering in grouped})
    matrix = [
        [
            sum(grouped[(arch, rendering)]) / len(grouped[(arch, rendering)])
            if grouped.get((arch, rendering)) else float("nan")
            for rendering in renderings
        ]
        for arch in archs
    ]
    fig, ax = plt.subplots(figsize=(max(6, 1.4 * len(renderings)), max(3, 0.6 * len(archs) + 1)))
    image = ax.imshow(matrix, vmin=0.0, vmax=1.0, cmap="viridis", aspect="auto")
    ax.set_xticks(range(len(renderings)))
    ax.set_xticklabels(renderings, rotation=45, ha="right", fontsize=6)
    ax.set_yticks(range(len(archs)))
    ax.set_yticklabels(archs, fontsize=7)
    fig.colorbar(image, ax=ax, label="full-call accuracy")
    ax.set_title("Architecture by rendering full-call accuracy")
    return _save(fig, out_dir, "model_by_rendering_heatmap")


def cost_latency_by_architecture(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    rows = [row for row in metrics.get("headline", []) if row.get("usage")]
    if not rows:
        return None
    labels = [f"{row['architecture']}\n({row['track']})" for row in rows]
    panels = [
        ("mean_model_calls", "mean model calls"),
        ("mean_total_tokens", "mean total tokens"),
        ("latency_p95_ms", "p95 latency (ms)"),
    ]
    fig, axes = plt.subplots(3, 1, figsize=(max(8, 0.7 * len(rows)), 9), sharex=True)
    for ax, (field, title) in zip(axes, panels):
        values = [row["usage"].get(field) or 0.0 for row in rows]
        ax.bar(range(len(rows)), values, color=_BAR_COLOR)
        ax.set_ylabel(title, fontsize=8)
    axes[-1].set_xticks(range(len(rows)))
    axes[-1].set_xticklabels(labels, rotation=90, fontsize=6)
    axes[0].set_title("Cost and latency by architecture")
    return _save(fig, out_dir, "cost_latency_by_architecture")


def complexity_frontier(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    points = []
    for row in metrics.get("headline", []):
        calls = (row.get("usage") or {}).get("mean_model_calls")
        accuracy = (row.get("full_call_accuracy") or {}).get("estimate")
        if calls is not None and accuracy is not None:
            points.append((row["architecture"], calls, accuracy))
    if not points:
        return None
    fig, ax = plt.subplots(figsize=(7, 5.5))
    for arch, calls, accuracy in sorted(points):
        ax.scatter(calls, accuracy, color=_BAR_COLOR, zorder=3)
        ax.annotate(arch, (calls, accuracy), fontsize=6,
                    xytext=(4, 4), textcoords="offset points")
    ax.set_xlabel("mean model calls per cell")
    ax.set_ylabel("full-call accuracy")
    ax.set_ylim(0, 1.05)
    ax.set_title("Architecture complexity frontier (Pareto view)")
    return _save(fig, out_dir, "complexity_frontier")


def memory_conditions(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    rows = [
        row for row in metrics.get("headline", [])
        if row["architecture"].startswith("M")
        and (row.get("full_call_accuracy") or {}).get("estimate") is not None
    ]
    if not rows:
        return None
    labels = [row["architecture"] for row in rows]
    estimates = [row["full_call_accuracy"]["estimate"] for row in rows]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(range(len(rows)), estimates, color=_BAR_COLOR)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("full-call accuracy")
    ax.set_title("Semantic memory conditions (M0-M4)")
    return _save(fig, out_dir, "memory_conditions")


def p_transition_deltas(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    transitions = [
        transition for transition in metrics.get("formalization_transitions", [])
        if "->" in transition["transition"] and "vs strong baseline" not in transition["transition"]
        and (transition.get("marginal_quality") or {}).get("delta", {}).get("estimate") is not None
    ]
    if not transitions:
        return None
    labels = [t["transition"].replace(" -> ", "\n-> ") for t in transitions]
    deltas = [t["marginal_quality"]["delta"]["estimate"] for t in transitions]
    lows = [d - (t["marginal_quality"]["delta"].get("ci_low") or d)
            for d, t in zip(deltas, transitions)]
    highs = [(t["marginal_quality"]["delta"].get("ci_high") or d) - d
             for d, t in zip(deltas, transitions)]
    fig, ax = plt.subplots(figsize=(max(8, 3.0 * len(transitions)), 5))
    ax.bar(range(len(transitions)), deltas, yerr=[lows, highs], capsize=4, color=_BAR_COLOR)
    ax.axhline(0.0, color="gray", linewidth=1)
    for index, transition in enumerate(transitions):
        ax.annotate(
            transition["marginal_quality"].get("verdict", ""),
            (index, deltas[index]), fontsize=6, ha="center",
            xytext=(0, 14), textcoords="offset points", color=_ACCENT_COLOR,
        )
    ax.set_xticks(range(len(transitions)))
    ax.set_xticklabels(labels, fontsize=6)
    ax.set_ylabel("final-state accuracy delta")
    ax.set_title("Adjacent P-transition marginal quality deltas (95% CI)")
    return _save(fig, out_dir, "p_transition_deltas")


def persistence_depth_vs_accuracy(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    points = []
    for arch, entry in sorted((metrics.get("persistence") or {}).items()):
        depth = entry.get("mean_nl_persistence_depth")
        accuracy = entry.get("final_state_accuracy")
        if depth is not None and accuracy is not None:
            points.append((arch, depth, accuracy))
    if not points:
        return None
    fig, ax = plt.subplots(figsize=(7, 5))
    for arch, depth, accuracy in points:
        ax.scatter(depth, accuracy, color=_BAR_COLOR, zorder=3)
        ax.annotate(arch, (depth, accuracy), fontsize=7,
                    xytext=(4, 4), textcoords="offset points")
    ax.set_xlabel("mean natural-language persistence depth")
    ax.set_ylabel("final-state accuracy")
    ax.set_ylim(0, 1.05)
    ax.set_title("NL persistence depth vs final-state accuracy")
    return _save(fig, out_dir, "persistence_depth_vs_accuracy")


def action_boundary_error_decomposition(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for score in scores:
        arch = score["architecture"]
        if not (arch.startswith("P") or arch.startswith("LP")):
            continue
        category = score.get("error_category")
        if category:
            grouped[arch][category] += 1
    if not grouped:
        return None
    archs = sorted(grouped)
    categories = sorted({cat for by_cat in grouped.values() for cat in by_cat})
    fig, ax = plt.subplots(figsize=(max(7, 1.2 * len(archs)), 4.5))
    bottoms = [0.0] * len(archs)
    for category in categories:
        values = [grouped[arch].get(category, 0) for arch in archs]
        ax.bar(range(len(archs)), values, bottom=bottoms, label=category)
        bottoms = [b + v for b, v in zip(bottoms, values)]
    ax.set_xticks(range(len(archs)))
    ax.set_xticklabels(archs, rotation=30, ha="right", fontsize=7)
    ax.set_ylabel("error count")
    ax.set_title("Error decomposition for proposal/typed-interface conditions")
    ax.legend(fontsize=7)
    return _save(fig, out_dir, "action_boundary_error_decomposition")


def procedure_adherence_by_family(metrics: dict, scores: list[dict], out_dir: Path) -> Path | None:
    grouped: dict[str, list[float]] = defaultdict(list)
    for score in scores:
        adherence = score.get("procedure_adherence")
        if isinstance(adherence, dict) and adherence.get("full_adherence") is not None:
            grouped[_family(score)].append(1.0 if adherence["full_adherence"] else 0.0)
    if not grouped:
        return None
    families = sorted(grouped)
    rates = [sum(grouped[family]) / len(grouped[family]) for family in families]
    fig, ax = plt.subplots(figsize=(max(6, 1.2 * len(families)), 4.5))
    ax.bar(range(len(families)), rates, color=_BAR_COLOR)
    for index, family in enumerate(families):
        ax.annotate(f"n={len(grouped[family])}", (index, rates[index]), fontsize=7,
                    ha="center", xytext=(0, 4), textcoords="offset points")
    ax.set_xticks(range(len(families)))
    ax.set_xticklabels(families)
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("full-adherence rate")
    ax.set_title("Procedure full-adherence rate by operation family")
    return _save(fig, out_dir, "procedure_adherence_by_family")


CHART_FUNCTIONS = [
    accuracy_by_architecture,
    paired_bgold_cgold_deltas,
    worst_variant_by_family,
    clarification_precision_recall,
    contrast_vs_invariance,
    first_divergence_distribution,
    model_by_rendering_heatmap,
    cost_latency_by_architecture,
    complexity_frontier,
    memory_conditions,
    p_transition_deltas,
    persistence_depth_vs_accuracy,
    action_boundary_error_decomposition,
    procedure_adherence_by_family,
]


def write_charts(run_dir: Path, metrics: dict[str, Any], scores: list[dict]) -> list[Path]:
    out_dir = Path(run_dir) / "charts"
    written = []
    for chart in CHART_FUNCTIONS:
        path = chart(metrics, scores, out_dir)
        if path is not None:
            written.append(path)
    return written
