"""Markdown report generation (spec §44.1, §44.8, §49.14).

Every sentence is a mechanical readout of ``metrics.json``: verdicts come from
the prespecified practical-equivalence decisions, questions the run cannot
answer say so, and null or negative results are never suppressed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lexstab.reporting.tables import (
    comparison_table,
    failure_views,
    format_ci,
    headline_table,
    interpretation_verdict,
    transition_table,
)

_COMPLEXITY_TITLE = "Does the added architecture earn its complexity?"

_CONCLUSION_EARNS = "Added architecture earns its complexity."
_CONCLUSION_STRATA = "Added architecture earns its complexity only for named high-risk strata."
_CONCLUSION_EQUIVALENT = "Added architecture is practically equivalent but operationally more expensive."
_CONCLUSION_INSUFFICIENT = (
    "Evidence is insufficient because equivalence margins or sample sizes were not adequate."
)
_CONCLUSION_NOT_MEASURED = (
    "The configured run did not measure the full architecture-complexity comparison."
)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def _md_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "_No data in this run._\n"
    header = "| " + " | ".join(title for _key, title in columns) + " |"
    rule = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, rule]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(row.get(key)) for key, _title in columns) + " |")
    return "\n".join(lines) + "\n"


def _comparison_lookup(metrics: dict) -> dict[str, dict]:
    return {c["comparison"]: c for c in metrics.get("primary_comparisons", [])}


def _delta_sentence(comparison: dict | None, subject: str) -> str:
    if comparison is None or (comparison.get("delta") or {}).get("estimate") is None:
        return f"{subject} was not measured in this run."
    if not comparison.get("interpretation_allowed", True):
        return (
            f"{subject} was measured, but interpretation is withheld: "
            f"{comparison.get('interpretation_warning') or 'measurement validity gate failed'}"
        )
    delta = comparison["delta"]
    case_sign = comparison.get("case_level_sign_test") or {}
    sign_suffix = ""
    if case_sign.get("n_independent_cases"):
        sign_suffix = (
            f" Case directions favored B/A/tie in "
            f"{case_sign.get('b_better_cases')}/{case_sign.get('a_better_cases')}/"
            f"{case_sign.get('tied_cases')} cases; exact sign p="
            f"{_fmt(case_sign.get('sign_p'))}."
        )
    return (
        f"{subject}: delta {format_ci(delta, digits=3)} against margin "
        f"±{_fmt(comparison.get('margin'))}, verdict **{comparison.get('verdict')}** "
        f"({comparison.get('n_pairs')} pairs, {delta.get('n_cases')} cases)."
        f"{sign_suffix}"
    )


def _adjacent_transitions(metrics: dict) -> list[dict]:
    return [
        t for t in metrics.get("formalization_transitions", [])
        if "->" in t["transition"] and "vs strong baseline" not in t["transition"]
    ]


def _measured_adjacent_transitions(metrics: dict) -> list[dict]:
    return [
        transition for transition in _adjacent_transitions(metrics)
        if ((transition.get("marginal_quality") or {}).get("delta") or {}).get(
            "estimate"
        ) is not None
    ]


def _largest_supported_transition(metrics: dict) -> dict | None:
    supported = [
        t for t in _adjacent_transitions(metrics)
        if (t.get("marginal_quality") or {}).get("verdict") == "exceeds_practical_margin"
        and (t.get("marginal_quality") or {}).get("interpretation_allowed", True)
    ]
    if not supported:
        return None
    return max(supported, key=lambda t: t["marginal_quality"]["delta"]["estimate"] or 0.0)


def _vs_a1_comparisons(metrics: dict) -> list[dict]:
    return [
        c for c in metrics.get("primary_comparisons", [])
        if c["comparison"].endswith("- A1_DIRECT_CLARIFY")
    ]


def _complexity_conclusion(metrics: dict) -> tuple[str, list[str]]:
    """Pick exactly one §44.8 conclusion mechanically from the verdicts."""
    comparisons = _vs_a1_comparisons(metrics)
    verdicts = {c["comparison"]: c.get("verdict") for c in comparisons}
    if not verdicts:
        return _CONCLUSION_NOT_MEASURED, []
    if any(not c.get("interpretation_allowed", True) for c in comparisons):
        return _CONCLUSION_INSUFFICIENT, []
    winners = [name for name, verdict in verdicts.items() if verdict == "exceeds_practical_margin"]
    if winners:
        return _CONCLUSION_EARNS, winners
    if any(verdict in ("inconclusive", "insufficient_data") for verdict in verdicts.values()):
        return _CONCLUSION_INSUFFICIENT, []
    return _CONCLUSION_EQUIVALENT, []


# ---------------------------------------------------------------- sections


def _header(metrics: dict, run_manifest: dict) -> list[str]:
    root_hash = metrics.get("benchmark_root_hash") or run_manifest.get("benchmark_root_hash", "")
    short_hash = root_hash.split(":")[-1][:12]
    lines = [
        f"# Lexical stability report: {metrics.get('run_id', 'unknown run')}",
        "",
        f"- Run: `{metrics.get('run_id')}`",
        f"- Benchmark root hash: `{short_hash}`",
        f"- Code revision: `{run_manifest.get('code_revision', 'unknown')}`",
        f"- Evaluation harness source hash: "
        f"`{metrics.get('evaluation_harness_source_hash', 'unknown')}`",
        f"- Benchmark manifest: `{run_manifest.get('benchmark_manifest_path', 'unknown')}`",
        f"- Matrix hash: `{run_manifest.get('matrix_hash', 'unknown')}`",
        f"- Mocked: {_fmt(bool(run_manifest.get('mocked')))}",
        "",
        f"<details><summary>Full benchmark root hash</summary><code>{root_hash}</code></details>",
        "",
        "Resolved model roles:",
        "",
    ]
    for role, config in sorted((run_manifest.get("resolved_roles") or {}).items()):
        lines.append(
            f"- {role}: `{config.get('model_id')}` (provider `{config.get('provider')}`, "
            f"enabled {_fmt(bool(config.get('enabled')))})"
        )
    lines.append("")
    if run_manifest.get("mocked"):
        lines += [
            "> **MOCKED SMOKE RUN — wiring validation only; results are not evidence for "
            "or against any hypothesis (spec §17.4).**",
            "",
        ]
    run_health = metrics.get("run_health") or {}
    if run_health:
        lines += [
            f"- Run health: `{run_health.get('status', 'unknown')}`",
            "",
        ]
    composition = (
        (run_manifest.get("research_overrides") or {}).get("composition") or {}
    )
    if composition:
        role_differences = composition.get("parameter_differences") or {}
        lines += [
            "> **PROVENANCE-LINKED TRACK COMPOSITE.** Source runs remain immutable. "
            "The complete replacement track was substituted before provider-free scoring.",
            "",
            f"- Base source run: `{composition.get('base_run_id')}`",
            f"- Replacement source run: `{composition.get('replacement_run_id')}`",
            f"- Replaced tracks: `{', '.join(composition.get('replaced_tracks') or [])}`",
            f"- Recorded response-budget differences: `{role_differences}`",
            f"- Composition provenance: `{composition.get('provenance_path')}` "
            f"(`{composition.get('provenance_hash')}`)",
            "",
        ]
    if not metrics.get("baseline_eligible", run_manifest.get("baseline_eligible", False)):
        lines += [
            "> This run is not baseline-eligible; every conclusion below is "
            "baseline-ineligible and cannot be promoted to a regression baseline.",
            "",
        ]
    return lines


def _executive_summary(metrics: dict, scores: list[dict], run_manifest: dict) -> list[str]:
    comparisons = _comparison_lookup(metrics)
    robustness = metrics.get("robustness") or {}
    lines = ["## Executive summary", ""]

    reference_arch = "A0_DIRECT" if "A0_DIRECT" in robustness else (
        sorted(robustness)[0] if robustness else None
    )
    if reference_arch:
        entry = robustness[reference_arch]
        answer1 = (
            f"For {reference_arch}, base-variant accuracy was {_fmt(entry.get('base_accuracy'))} "
            f"against mean-variant accuracy {_fmt(entry.get('mean_variant_accuracy'))} "
            f"(robustness gap {_fmt(entry.get('robustness_gap'))}, worst-variant "
            f"{_fmt(entry.get('worst_variant_accuracy'))}, operational invariance "
            f"{_fmt(entry.get('operational_invariance_rate'))} over {entry.get('n_cases')} cases)."
        )
    else:
        answer1 = "Robustness metrics were not measured in this run."
    lines += ["1. **Did raw lexical variants change operational performance?** " + answer1, ""]

    attribution = (metrics.get("adequacy_matrix") or {}).get("_attribution") or {}
    if attribution.get("total_failures"):
        answer2 = (
            f"{attribution['failures_in_inadequate_or_ambiguous_strata']} of "
            f"{attribution['total_failures']} failures "
            f"({_fmt(attribution.get('proportion'))}) fell in inadequate or ambiguous strata."
        )
    else:
        answer2 = "Adequacy attribution was not measured in this run."
    lines += [
        "2. **How much error was associated with request inadequacy or ambiguity rather "
        "than lexical variation?** " + answer2, "",
    ]

    lines += [
        "3. **Did A1's clarification policy materially improve the direct baseline?** "
        + _delta_sentence(comparisons.get("A1_DIRECT_CLARIFY - A0_DIRECT"),
                          "A1_DIRECT_CLARIFY vs A0_DIRECT (full call)"), "",
        "4. **Did runtime canonicalization improve the full pipeline beyond A1?** "
        + _delta_sentence(comparisons.get("B_RUNTIME - A1_DIRECT_CLARIFY"),
                          "B_RUNTIME vs A1_DIRECT_CLARIFY (full call)"), "",
        "5. **Did a stable rendering improve post-canonical execution?** "
        + _delta_sentence(comparisons.get("C_GOLD - B_GOLD"), "C_GOLD vs B_GOLD (full call)")
        + " "
        + _delta_sentence(
            comparisons.get("F_MODEL_DISCOVERED - C_GOLD"),
            "F_MODEL_DISCOVERED vs C_GOLD (full call)",
        ), "",
    ]

    headline_by_arch = {
        (row["track"], row["architecture"]): row for row in metrics.get("headline", [])
    }
    a0 = headline_by_arch.get(("boundary", "A0_DIRECT"))
    a1 = headline_by_arch.get(("boundary", "A1_DIRECT_CLARIFY"))
    if a0 and a1:
        answer6 = (
            f"A1 clarification precision {_fmt(a1['clarification'].get('precision'))} / recall "
            f"{_fmt(a1['clarification'].get('recall'))} against A0 precision "
            f"{_fmt(a0['clarification'].get('precision'))} / recall "
            f"{_fmt(a0['clarification'].get('recall'))}; unnecessary clarification "
            f"{_fmt(a1['clarification'].get('unnecessary_clarification_rate'))} (A1) vs "
            f"{_fmt(a0['clarification'].get('unnecessary_clarification_rate'))} (A0); "
            f"false-action rate {_fmt(a1.get('false_action_rate'))} (A1) vs "
            f"{_fmt(a0.get('false_action_rate'))} (A0)."
        )
    else:
        answer6 = "Boundary-track clarification metrics were not measured in this run."
    lines += ["6. **Did clarification behavior improve or degrade?** " + answer6, ""]

    lines += [
        "7. **Did stable terminology improve invariance without harming semantic "
        "discrimination?** "
        + _delta_sentence(comparisons.get("Stable - Lexical drift"),
                          "AL_CANONICAL vs AL_DRIFT (final state)"), "",
        "8. **Did semantic memory or retrieval add value beyond a static glossary?** "
        + _delta_sentence(comparisons.get("Retrieved memory - Static glossary"),
                          "M2_RETRIEVED_MEMORY vs M1_STATIC_GLOSSARY (full call)"), "",
    ]

    models = sorted({score.get("model_id") for score in scores if score.get("model_id")})
    repetitions = run_manifest.get("repetitions")
    families = sorted({
        score.get("metadata", {}).get("family_id") for score in scores
        if score.get("metadata", {}).get("family_id")
    })
    if len(models) < 2:
        answer9 = (
            f"Only one execution model ({models[0] if models else 'none'}) ran; cross-model "
            f"and cross-version stability were not measured in this run "
            f"({len(families)} operation families, repetitions={_fmt(repetitions)})."
        )
    else:
        answer9 = (
            f"{len(models)} models ran ({', '.join(models)}) across {len(families)} operation "
            f"families with repetitions={_fmt(repetitions)}; per-model splits are in "
            f"`tables/` and the rendering heatmap."
        )
    lines += [
        "9. **Were effects stable across models, versions, operation families, and "
        "repetitions?** " + answer9, "",
    ]

    if run_manifest.get("mocked"):
        answer10 = (
            "All results are mock-provider artifacts by construction; no substantive "
            "conclusion about evaluator artifacts or benchmark confounds can be drawn."
        )
    else:
        warnings = metrics.get("measurement_warnings") or []
        input_audit = metrics.get("effective_input_audit") or {}
        collapsed_groups = input_audit.get(
            "n_collapsed_source_variant_groups", 0
        )
        sample_warnings = [
            comparison for comparison in metrics.get("primary_comparisons", [])
            if comparison.get("interpretation_warning")
        ]
        answer10 = (
            f"Automated contract checks flagged {len(warnings)} cohort(s) below the "
            "schema-validity interpretation gate and "
            f"{len(sample_warnings)} primary comparison(s) with sample-size or "
            "operation-family limits. "
            + (
                "Those cohorts remain reported but are not given causal interpretations. "
                if warnings or sample_warnings else
                "No cohort or comparison fell below those gates. "
            )
            + (
                f"The effective-input audit found {collapsed_groups} cohort-case "
                "group(s) where multiple source request variants became one identical "
                "first model input; those groups do not test source lexical variation. "
                if collapsed_groups else
                "The effective-input audit found no source-variant groups collapsed "
                "to one identical first model input. "
            )
            + "Treat single-benchmark effects as unreplicated."
        )
    lines += [
        "10. **Which results may be evaluator artifacts or benchmark confounds?** "
        + answer10, "",
    ]

    conclusion, winners = _complexity_conclusion(metrics)
    answer11 = (
        f"Mechanical verdict: **{conclusion}** See "
        f"[{_COMPLEXITY_TITLE}](#does-the-added-architecture-earn-its-complexity)."
    )
    lines += ["11. **Does the added architecture earn its complexity?** " + answer11, ""]

    largest = _largest_supported_transition(metrics)
    if largest:
        delta = largest["marginal_quality"]["delta"]
        answer12 = (
            f"The largest practically supported marginal gain was **{largest['transition']}** "
            f"with final-state delta {format_ci(delta, digits=3)}."
        )
    elif _measured_adjacent_transitions(metrics):
        answer12 = (
            "No progressive-formalization transition cleared its practical threshold in this run."
        )
    else:
        answer12 = "Progressive-formalization transitions were not measured in this run."
    lines += [
        "12. **At which progressive-formalization transition, if any, did reliability "
        "improve materially?** " + answer12, "",
        "13. **Did canonicalize-once outperform repeated natural-language handoffs?** "
        + _delta_sentence(comparisons.get("LP1 canonical once - LP0B call-balanced prose"),
                          "LP1 vs LP0B (final state, call-balanced primary comparison)"), "",
    ]

    ablations = {
        entry.get("ablation"): entry for entry in metrics.get("component_ablations", [])
        if (entry.get("delta") or {}).get("estimate") is not None
    }
    labels = {
        "canonical state (gold intent vs raw request)": "canonical state",
        "procedure information (gold P2 vs unordered fact control)": "procedure facts",
        "procedure structure and named handle (fact control vs gold P3)": "procedure structure",
        "action interface (gold P3 vs gold P4)": "action interface",
    }
    measured = [
        (labels[name], entry["delta"]["estimate"], entry.get("verdict"))
        for name, entry in ablations.items() if name in labels
    ]
    if measured:
        best = max(measured, key=lambda item: item[1])
        readout = "; ".join(
            f"{label} delta {_fmt(estimate)} ({verdict})" for label, estimate, verdict in sorted(measured)
        )
        if best[0] in (
            "procedure facts", "procedure structure", "action interface"
        ) and best[2] == "exceeds_practical_margin":
            answer14 = (
                f"Yes: the **{best[0]}** component explains more of the gain than lexical "
                f"normalization or canonical intent ({readout})."
            )
        else:
            answer14 = (
                f"The largest measured component was **{best[0]}** "
                f"(delta {_fmt(best[1])}, verdict {best[2]}); component readout: {readout}."
            )
    else:
        answer14 = "Component ablations were not measured in this run."
    lines += [
        "14. **Did reusable procedure facts, structure, or the typed action interface explain more "
        "of the gain than lexical normalization?** " + answer14, "",
    ]
    return lines


def _headline_section(metrics: dict) -> list[str]:
    rows = headline_table(metrics)
    table = _md_table(rows, [
        ("architecture", "Architecture"),
        ("track", "Track"),
        ("intent_mode", "Intent"),
        ("procedure_selection", "Procedure selection"),
        ("procedure_packaging", "Packaging"),
        ("full_call", "Full-call"),
        ("final_state", "Final-state"),
        ("invariance", "Invariance"),
        ("contrast", "Contrast"),
        ("false_action", "False action"),
        ("n_cells", "n cells"),
        ("n_independent_cases", "Cases"),
        ("n_operation_families", "Families"),
        ("interpretation_scope", "Scope"),
    ])
    return [
        "## Headline results (§44.2)", "",
        "Every rate carries its case-clustered 95% interval and denominator. The "
        "false-action column reports the raw rate over the cell denominator (the "
        "metrics file records no interval for it).", "",
        table,
    ]


def _comparison_section(metrics: dict) -> list[str]:
    rows = comparison_table(metrics)
    table = _md_table(rows, [
        ("comparison", "Primary comparison"),
        ("delta", "Difference [95% CI]"),
        ("margin", "Margin"),
        ("verdict", "Practical threshold met?"),
        ("n_pairs", "n pairs"),
        ("n_cases", "n cases"),
        ("n_operation_families", "Families"),
        ("interpretation_scope", "Scope"),
        ("case_b_better", "B wins (cases)"),
        ("case_a_better", "A wins (cases)"),
        ("case_ties", "Ties (cases)"),
        ("case_sign_p", "Case sign p"),
    ])
    return [
        "## Primary comparisons (§44.3)", "",
        "Confidence intervals use a canonical-case cluster bootstrap. The exact "
        "sign test reduces every case to one direction before inference. Cell-level "
        "McNemar values remain in metrics.json for backward-compatible diagnostics "
        "but are not inferential when variants or repetitions share a case.", "",
        table,
    ]


def _transitions_section(metrics: dict) -> list[str]:
    rows = transition_table(metrics)
    adjacent = [row for row in rows if "vs strong baseline" not in row["transition"]]
    baseline = [row for row in rows if "vs strong baseline" in row["transition"]]
    lines = [
        "## Progressive-formalization transitions", "",
        "Adjacent marginal deltas (final state; paired, case-clustered):", "",
        _md_table(adjacent, [
            ("transition", "Transition"),
            ("quality_delta", "Quality delta [95% CI]"),
            ("verdict", "Verdict"),
            ("false_action_delta", "False-action delta"),
            ("calls_delta", "Calls delta"),
            ("tokens_delta", "Tokens delta"),
            ("latency_ms_delta", "Latency delta (ms)"),
            ("n_pairs", "n pairs"),
        ]),
        "Equivalence against the strong direct baseline P1:", "",
        _md_table(baseline, [
            ("transition", "Comparison"),
            ("quality_delta", "Quality delta [95% CI]"),
            ("verdict", "Verdict"),
            ("n_pairs", "n pairs"),
        ]),
    ]
    ablation_rows = []
    for entry in metrics.get("component_ablations", []):
        delta = entry.get("delta") or {}
        ablation_rows.append({
            "ablation": entry.get("ablation"),
            "delta": format_ci(delta, digits=3) if delta else "n/a",
            "verdict": interpretation_verdict(entry),
            "n_pairs": entry.get("n_pairs"),
        })
    lines += [
        "Gold-injected component ablations (§33.9):", "",
        _md_table(ablation_rows, [
            ("ablation", "Ablation"),
            ("delta", "Delta [95% CI]"),
            ("verdict", "Verdict"),
            ("n_pairs", "n pairs"),
        ]),
    ]
    return lines


def _persistence_section(metrics: dict) -> list[str]:
    comparisons = _comparison_lookup(metrics)
    persistence = metrics.get("persistence") or {}
    lines = ["## Persistence and representation flow", ""]
    lines += [
        "- Primary: " + _delta_sentence(
            comparisons.get("LP1 canonical once - LP0B call-balanced prose"),
            "LP1_CANONICAL_ONCE vs LP0B_GOLD_START_LANGUAGE_BALANCED (final state)"),
        "- Extra-call prose control (secondary): " + _delta_sentence(
            comparisons.get("LP1 canonical once - LP0G gold-start prose (secondary)"),
            "LP1_CANONICAL_ONCE vs LP0G_GOLD_START_LANGUAGE (final state)"),
        "- Practical end-to-end (secondary): " + _delta_sentence(
            comparisons.get("LP1 - LP0 practical end-to-end"),
            "LP1_CANONICAL_ONCE vs LP0_LANGUAGE_THROUGHOUT (final state)"),
        "- Visible verbatim reminder effect: " + _delta_sentence(
            comparisons.get(
                "LP0BV visible verbatim contract - LP0B call-balanced prose"
            ),
            "LP0BV vs LP0B (verbatim argument preservation)"),
        "- Canonical-once vs visible verbatim reminder: " + _delta_sentence(
            comparisons.get(
                "LP1 canonical once - LP0BV visible verbatim contract"
            ),
            "LP1 vs LP0BV (verbatim argument preservation)"),
        "",
    ]
    rows = [
        {
            "condition": arch,
            "n": entry.get("n"),
            "depth": entry.get("mean_nl_persistence_depth"),
            "reinterpretations": entry.get("mean_reinterpretation_count"),
            "representation_changes": entry.get("mean_representation_changes"),
            "verbatim": entry.get("verbatim_preservation_accuracy"),
            "final_state": entry.get("final_state_accuracy"),
            "cases": entry.get("n_independent_cases"),
            "families": entry.get("n_operation_families"),
            "scope": entry.get("interpretation_scope"),
            "recovered": entry.get(
                "intermediate_divergence_then_final_recovery_count"
            ),
            "not_recovered": entry.get(
                "intermediate_divergence_without_final_recovery_count"
            ),
            "pristine_success": entry.get("pristine_final_success_count"),
            "recovery_rate": entry.get(
                "recovery_rate_after_intermediate_verbatim_divergence"
            ),
        }
        for arch, entry in sorted(persistence.items())
    ]
    lines += [
        _md_table(rows, [
            ("condition", "Condition"),
            ("n", "n"),
            ("depth", "Mean NL persistence depth"),
            ("reinterpretations", "Mean reinterpretations"),
            ("representation_changes", "Mean representation changes"),
            ("verbatim", "Verbatim preservation"),
            ("final_state", "Final-state accuracy"),
            ("cases", "Cases"),
            ("families", "Families"),
            ("scope", "Interpretation scope"),
            ("recovered", "Diverged then recovered"),
            ("not_recovered", "Diverged, not recovered"),
            ("pristine_success", "Pristine success"),
            ("recovery_rate", "Recovery after divergence"),
        ]),
        "Divergence distributions are deterministic token-level diagnostics. They do not "
        "claim semantic equivalence or nonequivalence. First divergence is not a "
        "monotonic failure label: a later stage may restore the exact value, which is "
        "why recovery is reported separately.", "",
    ]
    divergence_rows: list[dict[str, Any]] = []
    divergence_fields = (
        ("first_divergence_distribution", "any"),
        ("first_operation_divergence_distribution", "operation"),
        ("first_argument_divergence_distribution", "argument"),
        ("first_verbatim_argument_divergence_distribution", "verbatim argument"),
    )
    for arch, entry in sorted(persistence.items()):
        for field, kind in divergence_fields:
            for stage, count in sorted((entry.get(field) or {}).items()):
                divergence_rows.append({
                    "condition": arch,
                    "kind": kind,
                    "stage": stage,
                    "n": count,
                })
    lines += [_md_table(divergence_rows, [
        ("condition", "Condition"), ("kind", "Divergence kind"),
        ("stage", "First divergence"), ("n", "n"),
    ])]
    return lines


def _elicitation_section(metrics: dict) -> list[str]:
    rows = [
        {
            "architecture": arch,
            "n": entry.get("n"),
            "resolution_rate": entry.get("resolution_rate"),
            "final_resolution_accuracy": entry.get("final_resolution_accuracy"),
            "false_action_rate": entry.get("false_action_rate"),
            "unresolved_without_action": entry.get("unresolved_without_action_rate"),
            "mean_turns": entry.get("mean_turns_to_resolution"),
            "mean_model_calls": entry.get("mean_model_calls"),
        }
        for arch, entry in sorted((metrics.get("elicitation") or {}).items())
    ]
    return [
        "## Intent elicitation (§38.5)", "",
        _md_table(rows, [
            ("architecture", "Architecture"),
            ("n", "n"),
            ("resolution_rate", "Resolution rate"),
            ("final_resolution_accuracy", "Final resolution accuracy"),
            ("false_action_rate", "False action"),
            ("unresolved_without_action", "Unresolved w/o action"),
            ("mean_turns", "Mean turns"),
            ("mean_model_calls", "Mean model calls"),
        ]),
    ]


def _adequacy_section(metrics: dict) -> list[str]:
    matrix = metrics.get("adequacy_matrix") or {}
    rows = [
        {
            "cell": cell,
            "n": entry.get("n"),
            "error_rate": entry.get("error_rate"),
            "false_action_rate": entry.get("false_action_rate"),
        }
        for cell, entry in sorted(matrix.items()) if not cell.startswith("_")
    ]
    lines = [
        "## Adequacy matrix (§9.2)", "",
        _md_table(rows, [
            ("cell", "Cell"),
            ("n", "n"),
            ("error_rate", "Error rate"),
            ("false_action_rate", "False-action rate"),
        ]),
    ]
    attribution = matrix.get("_attribution") or {}
    if attribution.get("total_failures") is not None:
        lines += [
            f"Attribution: {attribution.get('failures_in_inadequate_or_ambiguous_strata')} of "
            f"{attribution.get('total_failures')} failures "
            f"({_fmt(attribution.get('proportion'))}) occurred in inadequate or ambiguous "
            "strata rather than under pure lexical variation.", "",
        ]
    return lines


def _robustness_section(metrics: dict) -> list[str]:
    robustness = metrics.get("robustness") or {}
    rows = [
        {
            "architecture": arch,
            "base": entry.get("base_accuracy"),
            "mean": entry.get("mean_variant_accuracy"),
            "worst": entry.get("worst_variant_accuracy"),
            "gap": entry.get("robustness_gap"),
            "spread": entry.get("best_to_worst_spread"),
            "consistency": entry.get("within_case_consistency"),
            "invariance": entry.get("operational_invariance_rate"),
            "n_cases": entry.get("n_cases"),
        }
        for arch, entry in sorted(robustness.items())
    ]
    lines = [
        "## Robustness (§38.2)", "",
        _md_table(rows, [
            ("architecture", "Architecture"),
            ("base", "Base"),
            ("mean", "Mean variant"),
            ("worst", "Worst variant"),
            ("gap", "Robustness gap"),
            ("spread", "Best-to-worst spread"),
            ("consistency", "Within-case consistency"),
            ("invariance", "Operational invariance"),
            ("n_cases", "n cases"),
        ]),
        "Worst variants (lowest accuracy first):", "",
    ]
    worst_rows = []
    for arch, entry in sorted(robustness.items()):
        for case_id, info in sorted((entry.get("worst_variants_by_case") or {}).items()):
            worst_rows.append({
                "architecture": arch,
                "case_id": case_id,
                "request_id": info.get("worst_request_id"),
                "accuracy": info.get("worst_variant_accuracy"),
            })
    worst_rows.sort(key=lambda row: (row["accuracy"] or 0.0, row["architecture"], row["case_id"]))
    lines += [_md_table(worst_rows[:10], [
        ("architecture", "Architecture"),
        ("case_id", "Case"),
        ("request_id", "Worst request"),
        ("accuracy", "Accuracy"),
    ])]
    return lines


def _failure_section(metrics: dict, scores: list[dict]) -> list[str]:
    lines = ["## Failure views (§44.5)", ""]
    columns_by_view = {
        "worst_variants_by_case": [
            ("architecture", "Architecture"), ("case_id", "Case"),
            ("worst_request_id", "Worst request"), ("worst_variant_accuracy", "Accuracy"),
        ],
        "errors_by_adequacy_cell": [
            ("adequacy_cell", "Cell"), ("n", "n"),
            ("error_rate", "Error rate"), ("false_action_rate", "False-action rate"),
        ],
        "variation_axis_error_rates": [
            ("variation_axis", "Variation axis"), ("n", "n"),
            ("errors", "Errors"), ("error_rate", "Error rate"),
        ],
        "first_divergence_stages": [
            ("architecture", "Architecture"), ("stage", "Stage"), ("n", "n"),
        ],
        "clarify_requests_with_action": [
            ("architecture", "Architecture"), ("case_id", "Case"),
            ("request_id", "Request"), ("decision", "Decision"),
        ],
        "unnecessary_clarifications": [
            ("architecture", "Architecture"), ("case_id", "Case"),
            ("request_id", "Request"), ("repetition", "Repetition"),
        ],
        "interface_and_proposal_errors": [
            ("architecture", "Architecture"), ("case_id", "Case"),
            ("request_id", "Request"), ("error_category", "Error category"),
            ("interface_errors", "Interface errors"),
        ],
        "failures_by_architecture_case": [
            ("architecture", "Architecture"), ("case_id", "Case"),
            ("n", "n"), ("failures", "Failures"), ("failure_rate", "Failure rate"),
        ],
    }
    views = failure_views(metrics, scores)
    for view_name, columns in columns_by_view.items():
        rows = views.get(view_name, [])
        title = view_name.replace("_", " ").capitalize()
        lines += [f"### {title}", ""]
        if rows:
            lines += [_md_table(rows[:10], columns)]
            if len(rows) > 10:
                lines += [f"_{len(rows) - 10} additional rows in `tables/failure-"
                          f"{view_name.replace('_', '-')}.csv`._", ""]
        else:
            lines += ["_No rows for this view in this run._", ""]
    return lines


def _complexity_section(metrics: dict) -> list[str]:
    comparisons = {c["comparison"]: c for c in _vs_a1_comparisons(metrics)}
    headline_by_arch: dict[tuple[str, str, str, str], dict] = {}
    for row in metrics.get("headline", []):
        headline_by_arch[
            (
                row["architecture"],
                row.get("intent_mode", "none"),
                row.get("procedure_selection", "none"),
                row.get("procedure_packaging", "none"),
            )
        ] = row
    complexity = metrics.get("complexity") or {}
    robustness = metrics.get("robustness") or {}
    rows = []
    for cohort_key in sorted(complexity):
        bom = complexity[cohort_key]
        arch = bom.get("architecture", cohort_key)
        if arch == "A1_DIRECT_CLARIFY":
            continue
        measured = bom.get("measured") or {}
        cohort = (
            arch,
            bom.get("intent_mode", "none"),
            bom.get("procedure_selection", "none"),
            bom.get("procedure_packaging", "none"),
        )
        headline = headline_by_arch.get(cohort, {})
        robust = robustness.get(arch, {})
        quality = next(
            (c for label, c in comparisons.items() if label.startswith(arch + " ")), None
        )
        rows.append({
            "architecture": f"{arch} [{cohort[1]}/{cohort[2]}/{cohort[3]}]",
            "quality_vs_a1": quality.get("verdict") if quality else "no primary comparison",
            "full_call": format_ci(headline.get("full_call_accuracy") or {}),
            "invariance": (headline.get("operational_invariance") or {}).get("estimate"),
            "worst_variant": robust.get("worst_variant_accuracy"),
            "false_action": headline.get("false_action_rate"),
            "unnecessary_clarification": (headline.get("clarification") or {}).get(
                "unnecessary_clarification_rate"
            ),
            "calls": measured.get("mean_model_calls"),
            "tokens": measured.get("mean_total_tokens"),
            "p95_ms": measured.get("latency_p95_ms"),
            "stages": bom.get("mutable_model_stages"),
            "services": len(bom.get("external_services") or []),
            "stores": ", ".join(bom.get("persisted_stores") or []) or "none",
            "nl_handoffs": bom.get("nl_handoffs"),
        })
    lines = [
        f"## {_COMPLEXITY_TITLE}", "",
        "Each architecture against the strong baseline A1_DIRECT_CLARIFY over the §44.8 "
        "dimensions: task quality (practical-equivalence verdict), robustness, safety, "
        "clarification burden, runtime, and the infrastructure/operations bill of "
        "materials. Dimensions are reported separately; no opaque combined score is used.", "",
        _md_table(rows, [
            ("architecture", "Architecture"),
            ("quality_vs_a1", "Quality vs A1"),
            ("full_call", "Full-call"),
            ("invariance", "Invariance"),
            ("worst_variant", "Worst variant"),
            ("false_action", "False action"),
            ("unnecessary_clarification", "Unnecessary clarification"),
            ("calls", "Mean calls"),
            ("tokens", "Mean tokens"),
            ("p95_ms", "p95 latency (ms)"),
            ("stages", "Mutable stages"),
            ("services", "External services"),
            ("stores", "Persisted stores"),
            ("nl_handoffs", "NL handoffs"),
        ]),
        "The complexity frontier chart (`charts/complexity_frontier.png`) provides the "
        "Pareto view over measured cost and quality.", "",
    ]
    conclusion, winners = _complexity_conclusion(metrics)
    if conclusion == _CONCLUSION_EARNS:
        lines += [
            f"**Conclusion: {conclusion}** The following comparisons exceeded their "
            f"practical margins: {', '.join(winners)}.", "",
        ]
    elif conclusion == _CONCLUSION_EQUIVALENT:
        lines += [
            f"**Conclusion: {conclusion}** Every architecture compared against "
            "A1_DIRECT_CLARIFY was within (or below) its prespecified practical-equivalence "
            "margin while requiring more model stages, services, or stores. The additional "
            "normalization architecture is not justified for the tested domain (spec §49.14).", "",
        ]
    else:
        lines += [f"**Conclusion: {conclusion}**", ""]

    largest = _largest_supported_transition(metrics)
    if largest:
        delta = largest["marginal_quality"]["delta"]
        lines += [
            f"P ladder: the transition with the largest practically supported marginal gain "
            f"was **{largest['transition']}** (final-state delta {format_ci(delta, digits=3)}). "
            "No earlier cumulative layer is credited for this gain.", "",
        ]
    elif _measured_adjacent_transitions(metrics):
        lines += [
            "P ladder: no transition cleared its practical threshold; no tested "
            "formalization transition earned its complexity in this run.", "",
        ]
    else:
        lines += ["P ladder: no transitions were measured in this run.", ""]
    return lines


def _null_results_section(metrics: dict) -> list[str]:
    rows = [
        {
            "comparison": c["comparison"],
            "delta": format_ci(c.get("delta") or {}, digits=3),
            "margin": c.get("margin"),
            "verdict": c.get("verdict"),
        }
        for c in metrics.get("primary_comparisons", [])
        if c.get("verdict") in ("practically_equivalent", "practically_worse")
    ]
    lines = ["## Null and negative results", ""]
    if rows:
        lines += [
            "The following prespecified comparisons were practically equivalent or "
            "practically worse. They are reported, not suppressed.", "",
            _md_table(rows, [
                ("comparison", "Comparison"),
                ("delta", "Delta [95% CI]"),
                ("margin", "Margin"),
                ("verdict", "Verdict"),
            ]),
        ]
    else:
        lines += ["No primary comparison resolved to practically_equivalent or "
                  "practically_worse in this run.", ""]
    return lines


def _analysis_labels_section(metrics: dict) -> list[str]:
    labels = metrics.get("analysis_labels") or {}
    lines = ["## Analysis labels", ""]
    for tier in ("primary", "secondary", "exploratory"):
        names = labels.get(tier) or []
        lines.append(f"- **{tier.capitalize()}**: {', '.join(names) if names else 'none'}")
    lines.append("")
    fdr = metrics.get("exploratory_fdr") or {}
    rows = [
        {
            "comparison": name,
            "p": entry.get("p"),
            "bh_adjusted": entry.get("bh_adjusted"),
            "significant": entry.get("significant_at_fdr"),
        }
        for name, entry in sorted(fdr.items())
    ]
    lines += [
        "Exploratory family with Benjamini-Hochberg FDR control (canonical-case exact "
        "sign-test p-values; the primary decisions above remain the "
        "interval-in-margin verdicts):", "",
        _md_table(rows, [
            ("comparison", "Comparison"),
            ("p", "p"),
            ("bh_adjusted", "BH-adjusted p"),
            ("significant", "Significant at FDR"),
        ]),
    ]
    return lines


def _charts_section(run_dir: Path) -> list[str]:
    charts_dir = Path(run_dir) / "charts"
    pngs = sorted(charts_dir.glob("*.png")) if charts_dir.exists() else []
    lines = ["## Charts (§44.6)", ""]
    if not pngs:
        lines += ["_No charts were generated for this run._", ""]
        return lines
    for png in pngs:
        title = png.stem.replace("_", " ")
        lines += [f"### {title}", "", f"![{title}](charts/{png.name})", ""]
    return lines


def _measurement_validity_section(metrics: dict) -> list[str]:
    warnings = metrics.get("measurement_warnings") or []
    rows = [
        {
            "architecture": warning.get("architecture"),
            "intent": warning.get("intent_mode"),
            "selection": warning.get("procedure_selection"),
            "packaging": warning.get("procedure_packaging"),
            "schema_validity": warning.get("schema_validity"),
            "minimum": warning.get("minimum"),
            "interpretation": warning.get("interpretation"),
        }
        for warning in warnings
    ]
    thresholds = metrics.get("interpretation_thresholds") or {}
    comparison_warnings = [
        {
            "comparison": comparison.get("comparison"),
            "cases": comparison.get("n_independent_cases"),
            "families": comparison.get("n_operation_families"),
            "scope": comparison.get("interpretation_scope"),
            "warning": comparison.get("interpretation_warning"),
        }
        for comparison in metrics.get("primary_comparisons", [])
        if comparison.get("interpretation_warning")
    ]
    input_audit = metrics.get("effective_input_audit") or {}
    input_rows = [
        {
            "architecture": group.get("architecture"),
            "intent": group.get("intent_mode"),
            "case": group.get("case_id"),
            "cells": group.get("n_cells"),
            "source_requests": group.get("n_source_requests"),
            "unique_inputs": group.get("n_unique_first_model_inputs"),
            "bands": ", ".join(group.get("source_lexical_distance_bands") or []),
            "classification": group.get("classification"),
            "claim_scope": group.get("claim_scope"),
        }
        for group in input_audit.get("groups", [])
        if group.get("n_source_requests", 0) > 1
    ]
    return [
        "## Measurement validity", "",
        "Raw observations are never removed or rescored by these gates. Causal "
        "interpretation requires at least "
        f"{thresholds.get('minimum_independent_cases_for_interpretation', 'n/a')} "
        "independent canonical cases. Generalization beyond the tested operations "
        "requires at least "
        f"{thresholds.get('minimum_operation_families_for_generalization', 'n/a')} "
        "operation families. Cohorts below the schema-contract gate also cannot support "
        "a causal component claim.", "",
        _md_table(rows, [
            ("architecture", "Architecture"),
            ("intent", "Intent"),
            ("selection", "Selection"),
            ("packaging", "Packaging"),
            ("schema_validity", "Schema validity"),
            ("minimum", "Required"),
            ("interpretation", "Interpretation"),
        ]),
        "Sample-size and operation-family interpretation warnings:", "",
        _md_table(comparison_warnings, [
            ("comparison", "Comparison"),
            ("cases", "Cases"),
            ("families", "Families"),
            ("scope", "Scope"),
            ("warning", "Warning"),
        ]),
        "Effective model-input identity audit:", "",
        "Frozen source-request labels describe the source corpus, not necessarily "
        "the text presented to the execution model. The audit hashes the first "
        "model-visible invocation inside each exact cohort and canonical case. If "
        "multiple source requests collapse to one identical input, those cells are "
        "stochastic repetitions for that condition and cannot support a claim about "
        "source lexical distance.", "",
        _md_table(input_rows, [
            ("architecture", "Architecture"),
            ("intent", "Intent"),
            ("case", "Case"),
            ("cells", "Cells"),
            ("source_requests", "Source requests"),
            ("unique_inputs", "Unique first inputs"),
            ("bands", "Nominal bands"),
            ("classification", "Classification"),
            ("claim_scope", "Claim scope"),
        ]),
    ]


def _rendering_contrast_section(metrics: dict) -> list[str]:
    rendering = metrics.get("rendering_contrast") or {}
    comparisons = [
        rendering.get("all_cases_comparison") or {},
        rendering.get("lexically_distinct_comparison") or {},
    ]
    rows = [
        {
            "comparison": entry.get("comparison"),
            "delta": format_ci(entry.get("delta"), digits=3),
            "verdict": interpretation_verdict(entry),
            "n_pairs": entry.get("n_pairs"),
        }
        for entry in comparisons if entry
    ]
    operation_rows = [
        {
            "operation": operation_id,
            "n": entry.get("n"),
            "accuracy": entry.get("full_call_accuracy"),
            "distinct_n": entry.get("lexically_distinct_n"),
        }
        for operation_id, entry in sorted((rendering.get("by_operation") or {}).items())
    ]
    return [
        "## Model-discovered rendering contrast", "",
        f"Model-discovered cells: {rendering.get('n_model_discovered_cells', 0)}; "
        f"lexically distinct from the canonical rendering: {rendering.get('n_lexically_distinct_cells', 0)}; "
        f"identical: {rendering.get('n_identical_to_canonical_cells', 0)}.", "",
        str(rendering.get("interpretation") or ""), "",
        _md_table(rows, [
            ("comparison", "Comparison"),
            ("delta", "Delta [95% CI]"),
            ("verdict", "Verdict"),
            ("n_pairs", "n pairs"),
        ]),
        "Operation coverage:", "",
        _md_table(operation_rows, [
            ("operation", "Operation"),
            ("n", "n"),
            ("accuracy", "Full-call accuracy"),
            ("distinct_n", "Lexically distinct n"),
        ]),
    ]


def _completion_section(metrics: dict) -> list[str]:
    completion = metrics.get("completion") or {}
    missing = metrics.get("missing_cells") or []
    return [
        "## Completion (§39.11)", "",
        f"Scored {completion.get('scored_cells', 0)} of {completion.get('matrix_cells', 0)} "
        f"matrix cells (completion rate {_fmt(completion.get('completion_rate'))}); "
        f"{len(missing)} cells are missing and reported, not silently dropped.", "",
    ]


def render_report(run_dir: Path, metrics: dict[str, Any], scores: list[dict],
                  run_manifest: dict[str, Any]) -> str:
    lines: list[str] = []
    lines += _header(metrics, run_manifest)
    lines += _executive_summary(metrics, scores, run_manifest)
    lines += _headline_section(metrics)
    lines += _comparison_section(metrics)
    lines += _transitions_section(metrics)
    lines += _persistence_section(metrics)
    lines += _elicitation_section(metrics)
    lines += _adequacy_section(metrics)
    lines += _robustness_section(metrics)
    lines += _failure_section(metrics, scores)
    lines += _measurement_validity_section(metrics)
    lines += _rendering_contrast_section(metrics)
    lines += _complexity_section(metrics)
    lines += _null_results_section(metrics)
    lines += _analysis_labels_section(metrics)
    lines += _charts_section(run_dir)
    lines += _completion_section(metrics)
    text = "\n".join(lines).rstrip() + "\n"
    (Path(run_dir) / "report.md").write_text(text, encoding="utf-8")
    return text
