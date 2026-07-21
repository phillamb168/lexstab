"""Metric aggregation over score records (spec §38, §44).

Everything here is a pure function of the score records plus configuration.
Case-clustered intervals come from :mod:`lexstab.metrics.statistics`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from lexstab.metrics.statistics import (
    case_level_sign_test,
    Interval,
    cluster_bootstrap_delta,
    cluster_bootstrap_rate,
    paired_discordance,
    practical_equivalence,
)

P_LADDER = ["P0_RAW_PROPOSAL", "P1_CLARIFY_PROPOSAL", "P2_CANONICAL_PROPOSAL",
            "P3_CANONICAL_PROCEDURE_PROPOSAL", "P4_CANONICAL_PROCEDURE_TOOL"]


def adequacy_matrix_cell(score: dict) -> str:
    """Derive the §9.2 adequacy-matrix cell from frozen labels (D-017)."""
    meta = score.get("metadata", {})
    adequate = meta.get("adequacy") == "ADEQUATE" and meta.get("ambiguity") == "UNAMBIGUOUS"
    conventional = meta.get("lexical_distance_band") == "LOW"
    row = "adequate" if adequate else "inadequate_or_ambiguous"
    column = "conventional" if conventional else "varied"
    return f"{row}/{column}"


def _obs(scores: list[dict], field: str) -> list[tuple[str, float]]:
    out = []
    for score in scores:
        value = score.get(field)
        if value is None:
            continue
        out.append((score["case_id"], 1.0 if value else 0.0))
    return out


def _ci(
    scores: list[dict], field: str, *, samples: int, seed: int, confidence: float
) -> dict[str, Any]:
    return cluster_bootstrap_rate(
        _obs(scores, field), samples=samples, seed=seed, confidence=confidence
    ).to_dict()


def _group(scores: list[dict], key_fn) -> dict[Any, list[dict]]:
    groups: dict[Any, list[dict]] = defaultdict(list)
    for score in scores:
        groups[key_fn(score)].append(score)
    return dict(groups)


def primary_h1_stratum(scores: list[dict]) -> list[dict]:
    """Only frozen ADEQUATE/UNAMBIGUOUS/EXECUTE/INVARIANT requests (§49.1)."""
    return [score for score in scores if score.get("metadata", {}).get("primary_h1")]


def lexical_h1_stratum(scores: list[dict]) -> list[dict]:
    """Primary H1 observations whose source wording actually reached the system."""
    return [
        score for score in primary_h1_stratum(scores)
        if score.get("metadata", {}).get("intent_mode") != "gold"
    ]


# ---------------------------------------------------------------- headline


def headline_metrics(
    scores: list[dict], *, samples: int = 2000, seed: int = 104729,
    confidence: float = 0.95,
    minimum_independent_cases: int = 1,
    minimum_operation_families: int = 1,
) -> list[dict]:
    rows = []
    for (track, arch, intent_mode, selection, packaging), group in sorted(_group(
        scores,
        lambda s: (
            s["track"],
            s["architecture"],
            s.get("metadata", {}).get("intent_mode") or "none",
            s.get("metadata", {}).get("procedure_selection") or "none",
            s.get("metadata", {}).get("procedure_packaging") or "none",
        ),
    ).items()):
        h1 = primary_h1_stratum(group)
        clar = clarification_metrics(group)
        invariance = operational_invariance(
            h1, samples=samples, seed=seed, confidence=confidence
        )
        contrast_scores = [s for s in group if s.get("contrast_correct") is not None]
        clarify_expected = [
            s for s in group
            if s.get("metadata", {}).get("expected_behavior") == "CLARIFY"
        ]
        execute_expected = [
            s for s in group
            if s.get("metadata", {}).get("expected_behavior") == "EXECUTE"
        ]
        row = {
            "track": track,
            "architecture": arch,
            "intent_mode": intent_mode,
            "procedure_selection": selection,
            "procedure_packaging": packaging,
            "n_cells": len(group),
            "n_independent_cases": len({score["case_id"] for score in group}),
            "n_operation_families": len({
                score.get("metadata", {}).get("family_id") or score["case_id"]
                for score in group
            }),
            "schema_validity": _ci(group, "schema_valid", samples=samples, seed=seed, confidence=confidence),
            "decision_accuracy": _ci(group, "decision_correct", samples=samples, seed=seed, confidence=confidence),
            "full_call_accuracy": _ci(h1 or group, "full_call_correct", samples=samples, seed=seed, confidence=confidence),
            "final_state_accuracy": _ci(
                [s for s in (h1 or group) if s.get("final_state_correct") is not None],
                "final_state_correct", samples=samples, seed=seed, confidence=confidence,
            ),
            "operational_invariance": invariance,
            "contrast_accuracy": _ci(contrast_scores, "contrast_correct", samples=samples, seed=seed, confidence=confidence),
            "false_action_rate": clar["false_action_rate"],
            "false_action_interval": _ci(
                clarify_expected, "false_action", samples=samples, seed=seed,
                confidence=confidence,
            ),
            "clarification": clar,
            "unnecessary_clarification_interval": _ci(
                [
                    {**s, "unnecessary_clarification": s.get("clarification_outcome") == "FP"}
                    for s in execute_expected if s.get("clarification_outcome")
                ],
                "unnecessary_clarification", samples=samples, seed=seed,
                confidence=confidence,
            ),
            "refusal_correctness": _ci(
                [s for s in group if s.get("refusal_correct") is not None],
                "refusal_correct", samples=samples, seed=seed, confidence=confidence,
            ),
            "usage": usage_metrics(group),
        }
        row["interpretation_allowed"] = (
            row["n_independent_cases"] >= minimum_independent_cases
        )
        row["generalization_allowed"] = (
            row["interpretation_allowed"]
            and row["n_operation_families"] >= minimum_operation_families
        )
        row["interpretation_scope"] = (
            "generalizable"
            if row["generalization_allowed"] else (
                "tested_operation_families_only"
                if row["interpretation_allowed"] else "exploratory"
            )
        )
        rows.append(row)
    return rows


# ---------------------------------------------------------------- robustness (§38.2)


def robustness_metrics(scores: list[dict]) -> dict[str, Any]:
    h1 = lexical_h1_stratum(scores)
    by_arch = _group(h1, lambda s: s["architecture"])
    out = {}
    for arch, group in sorted(by_arch.items()):
        by_case = _group(group, lambda s: s["case_id"])
        base_accs, mean_accs, worst_accs, spreads, consistencies, invariances = [], [], [], [], [], []
        pairwise_disagreements = []
        worst_by_case = {}
        for case_id, case_scores in sorted(by_case.items()):
            by_request = _group(case_scores, lambda s: s["request_id"])
            request_accs = {}
            request_decisions = {}
            for request_id, reps in by_request.items():
                request_accs[request_id] = sum(
                    1.0 for s in reps if s["full_call_correct"]
                ) / len(reps)
                request_decisions[request_id] = tuple(sorted(
                    {
                        (
                            s.get("decision"),
                            s.get("actual_operation_id"),
                            s.get("actual_tool"),
                            repr(sorted((s.get("actual_arguments") or {}).items())),
                        )
                        for s in reps
                    },
                    key=repr,
                ))
            accs = list(request_accs.values())
            base = [
                acc for request_id, acc in request_accs.items()
                if any(
                    s.get("metadata", {}).get("is_designated_canonical")
                    for s in by_request[request_id]
                )
            ]
            base_accs.append(sum(base) / len(base) if base else None)
            mean_accs.append(sum(accs) / len(accs))
            worst = min(accs)
            worst_accs.append(worst)
            worst_by_case[case_id] = {
                "worst_variant_accuracy": worst,
                "worst_request_id": min(request_accs, key=request_accs.get),
            }
            spreads.append(max(accs) - min(accs))
            decisions = list(request_decisions.values())
            same = sum(1 for d in decisions if d == decisions[0])
            consistencies.append(same / len(decisions))
            invariances.append(1.0 if all(
                s["full_call_correct"] and s.get("final_state_correct") is not False
                for s in case_scores
            ) else 0.0)
            pairs = [
                (a, b) for i, a in enumerate(decisions) for b in decisions[i + 1:]
            ]
            if pairs:
                pairwise_disagreements.append(
                    sum(1 for a, b in pairs if a != b) / len(pairs)
                )
        defined_base = [b for b in base_accs if b is not None]
        out[arch] = {
            "base_accuracy": sum(defined_base) / len(defined_base) if defined_base else None,
            "mean_variant_accuracy": sum(mean_accs) / len(mean_accs) if mean_accs else None,
            "worst_variant_accuracy": sum(worst_accs) / len(worst_accs) if worst_accs else None,
            "global_worst": min(
                ((case_id, info["worst_variant_accuracy"]) for case_id, info in worst_by_case.items()),
                key=lambda item: item[1], default=None,
            ),
            "robustness_gap": (
                (sum(defined_base) / len(defined_base)) - (sum(mean_accs) / len(mean_accs))
                if defined_base and mean_accs else None
            ),
            "best_to_worst_spread": sum(spreads) / len(spreads) if spreads else None,
            "within_case_consistency": sum(consistencies) / len(consistencies) if consistencies else None,
            "operational_invariance_rate": sum(invariances) / len(invariances) if invariances else None,
            "pairwise_variant_disagreement": (
                sum(pairwise_disagreements) / len(pairwise_disagreements)
                if pairwise_disagreements else None
            ),
            "worst_variants_by_case": worst_by_case,
            "n_cases": len(by_case),
        }
    return out


def operational_invariance(
    h1_scores: list[dict], *, samples: int = 2000, seed: int = 104729,
    confidence: float = 0.95,
) -> dict[str, Any]:
    by_case = _group(h1_scores, lambda s: s["case_id"])
    values = []
    for case_id, case_scores in by_case.items():
        values.append((case_id, 1.0 if all(
            s["full_call_correct"] and s.get("final_state_correct") is not False
            for s in case_scores
        ) else 0.0))
    return cluster_bootstrap_rate(
        values, samples=samples, seed=seed, confidence=confidence
    ).to_dict()


# ---------------------------------------------------------------- clarification (§38.4)


def clarification_metrics(scores: list[dict]) -> dict[str, Any]:
    scores = [
        score for score in scores
        if score.get("metadata", {}).get("intent_mode") != "gold"
    ]
    outcomes = [s.get("clarification_outcome") for s in scores if s.get("clarification_outcome")]
    tp = outcomes.count("TP")
    fp = outcomes.count("FP")
    fn = outcomes.count("FN")
    tn = outcomes.count("TN")
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall)
        else None
    )
    clarify_expected = [s for s in scores if s.get("metadata", {}).get("expected_behavior") == "CLARIFY"]
    refuse_expected = [s for s in scores if s.get("metadata", {}).get("expected_behavior") == "REFUSE"]
    execute_expected = [s for s in scores if s.get("metadata", {}).get("expected_behavior") == "EXECUTE"]
    false_action = (
        sum(1 for s in clarify_expected if s.get("false_action")) / len(clarify_expected)
        if clarify_expected else None
    )
    refusal_false_action = (
        sum(1 for s in refuse_expected if s.get("false_action")) / len(refuse_expected)
        if refuse_expected else None
    )
    unnecessary = (
        sum(1 for s in execute_expected if s.get("clarification_outcome") == "FP") / len(execute_expected)
        if execute_expected else None
    )
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "false_action_rate": false_action,
        "refusal_false_action_rate": refusal_false_action,
        "unnecessary_clarification_rate": unnecessary,
    }


# ---------------------------------------------------------------- adequacy matrix (§9.2)


def adequacy_matrix_metrics(scores: list[dict]) -> dict[str, Any]:
    cells = _group(scores, adequacy_matrix_cell)
    out = {}
    for cell, group in sorted(cells.items()):
        errors = [s for s in group if not s.get("full_call_correct")]
        out[cell] = {
            "n": len(group),
            "error_rate": len(errors) / len(group) if group else None,
            "false_action_rate": (
                sum(1 for s in group if s.get("false_action")) / len(group) if group else None
            ),
        }
    total_failures = sum(1 for s in scores if not s.get("full_call_correct"))
    inadequate_failures = sum(
        1 for s in scores
        if not s.get("full_call_correct") and adequacy_matrix_cell(s).startswith("inadequate")
    )
    out["_attribution"] = {
        "total_failures": total_failures,
        "failures_in_inadequate_or_ambiguous_strata": inadequate_failures,
        "proportion": inadequate_failures / total_failures if total_failures else None,
    }
    return out


# ---------------------------------------------------------------- paired comparisons


MODELESS_ARCHITECTURES = {
    "A0_DIRECT", "A1_DIRECT_CLARIFY",
    "P0_RAW_PROPOSAL", "P1_CLARIFY_PROPOSAL",
    "M0_NO_MEMORY", "M1_STATIC_GLOSSARY", "M2_RETRIEVED_MEMORY",
    "M3_CANONICAL_RESOLVER", "M4_PERSONALIZED_MEMORY", "AL_RAW",
}
GOLD_ARCHITECTURES = {
    "B_GOLD", "C_GOLD", "D_DEFINITION_ONLY", "E_ORGANIZATION_TERM",
    "F_MODEL_DISCOVERED", "LP0G_GOLD_START_LANGUAGE",
    "LP0B_GOLD_START_LANGUAGE_BALANCED", "LP2_CANONICAL_PROCEDURE",
    "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM",
    "LP3_CANONICAL_PROCEDURE_TOOL",
}
RUNTIME_ARCHITECTURES = {"B_RUNTIME", "C_RUNTIME", "LP0_LANGUAGE_THROUGHOUT"}


def comparison_selector(arch: str, intent_mode: str | None) -> dict[str, str]:
    if arch in MODELESS_ARCHITECTURES:
        mode = "none"
    elif intent_mode is not None:
        mode = intent_mode
    elif arch in GOLD_ARCHITECTURES:
        mode = "gold"
    elif arch in RUNTIME_ARCHITECTURES:
        mode = "runtime"
    else:
        mode = "none"
    selection = "gold" if arch in {
        "P3_CANONICAL_PROCEDURE_PROPOSAL", "P4_CANONICAL_PROCEDURE_TOOL",
        "LP2_CANONICAL_PROCEDURE", "LP3_CANONICAL_PROCEDURE_TOOL",
    } else "none"
    packaging = "inline" if selection == "gold" else "none"
    if arch == "P2F_CANONICAL_FACTS_PROPOSAL":
        selection, packaging = "gold", "facts_only"
    return {
        "architecture": arch,
        "intent_mode": mode,
        "procedure_selection": selection,
        "procedure_packaging": packaging,
    }


def _paired_values(
    scores: list[dict], arch_a: str, arch_b: str, field: str,
    *, restrict_h1: bool = True, intent_mode: str | None = None,
) -> list[tuple[str, float, float]]:
    def _key(score: dict) -> tuple:
        return (score["case_id"], score.get("request_id"), score.get("repetition"))

    def _eligible(score: dict, arch: str) -> bool:
        if score["architecture"] != arch:
            return False
        if restrict_h1 and score.get("request_id") and not score.get("metadata", {}).get("primary_h1"):
            return False
        meta = score.get("metadata", {})
        expected = comparison_selector(arch, intent_mode)
        return (
            (meta.get("intent_mode") or "none") == expected["intent_mode"]
            and (meta.get("procedure_selection") or "none")
            == expected["procedure_selection"]
            and (meta.get("procedure_packaging") or "none")
            == expected["procedure_packaging"]
        )

    side_a = {_key(s): s for s in scores if _eligible(s, arch_a)}
    side_b = {_key(s): s for s in scores if _eligible(s, arch_b)}
    paired = []
    for key in sorted(set(side_a) & set(side_b), key=str):
        value_a = side_a[key].get(field)
        value_b = side_b[key].get(field)
        if value_a is None or value_b is None:
            continue
        paired.append((key[0], 1.0 if value_a else 0.0, 1.0 if value_b else 0.0))
    return paired


def paired_comparison(
    scores: list[dict], arch_a: str, arch_b: str, field: str, margin: float,
    *, samples: int = 2000, seed: int = 104729, restrict_h1: bool = True,
    intent_mode: str | None = None, label: str | None = None,
    confidence: float = 0.95,
) -> dict[str, Any]:
    paired = _paired_values(scores, arch_a, arch_b, field, restrict_h1=restrict_h1, intent_mode=intent_mode)
    delta = cluster_bootstrap_delta(
        paired, samples=samples, seed=seed, confidence=confidence
    )
    decision = practical_equivalence(label or f"{arch_b} - {arch_a}", delta, margin)
    discordance = paired_discordance(paired)
    case_sign = case_level_sign_test(paired)
    case_ids = sorted({case_id for case_id, _a, _b in paired})
    family_by_case = {
        score["case_id"]: (
            score.get("metadata", {}).get("family_id") or score["case_id"]
        )
        for score in scores
    }
    family_ids = sorted({family_by_case.get(case_id, case_id) for case_id in case_ids})
    return {
        **decision.to_dict(),
        "field": field,
        "n_pairs": len(paired),
        "n_independent_cases": len(case_ids),
        "independent_case_ids": case_ids,
        "n_operation_families": len(family_ids),
        "operation_family_ids": family_ids,
        "secondary_mcnemar": discordance,
        "case_level_sign_test": case_sign,
        "pairing_cohorts": [
            comparison_selector(arch_a, intent_mode),
            comparison_selector(arch_b, intent_mode),
        ],
    }


def primary_comparisons(scores: list[dict], equivalence: dict[str, float],
                        *, samples: int = 2000, seed: int = 104729,
                        confidence: float = 0.95) -> list[dict]:
    margin = float(equivalence.get("success_margin", 0.01))
    fs_margin = float(equivalence.get("final_state_margin", margin))
    comparisons = [
        ("A1_DIRECT_CLARIFY - A0_DIRECT", "A0_DIRECT", "A1_DIRECT_CLARIFY", "full_call_correct", margin, "none"),
        ("B_RUNTIME - A1_DIRECT_CLARIFY", "A1_DIRECT_CLARIFY", "B_RUNTIME", "full_call_correct", margin, "runtime"),
        ("C_RUNTIME - A1_DIRECT_CLARIFY", "A1_DIRECT_CLARIFY", "C_RUNTIME", "full_call_correct", margin, "runtime"),
        ("C_GOLD - B_GOLD", "B_GOLD", "C_GOLD", "full_call_correct", margin, "gold"),
        ("C_GOLD - B_GOLD (final state)", "B_GOLD", "C_GOLD", "final_state_correct", fs_margin, "gold"),
        ("F_MODEL_DISCOVERED - C_GOLD", "C_GOLD", "F_MODEL_DISCOVERED", "full_call_correct", margin, "gold"),
        ("F_MODEL_DISCOVERED - B_GOLD", "B_GOLD", "F_MODEL_DISCOVERED", "full_call_correct", margin, "gold"),
        ("P1 - P0 clarification transition", "P0_RAW_PROPOSAL", "P1_CLARIFY_PROPOSAL", "final_state_correct", fs_margin, "none"),
        ("P2 - P1 canonical-intent transition", "P1_CLARIFY_PROPOSAL", "P2_CANONICAL_PROPOSAL", "final_state_correct", fs_margin, "runtime"),
        ("P3 - P2 reusable-procedure transition", "P2_CANONICAL_PROPOSAL", "P3_CANONICAL_PROCEDURE_PROPOSAL", "final_state_correct", fs_margin, "runtime"),
        ("P4 - P3 typed-interface transition", "P3_CANONICAL_PROCEDURE_PROPOSAL", "P4_CANONICAL_PROCEDURE_TOOL", "final_state_correct", fs_margin, "runtime"),
        ("LP1 canonical once - LP0B call-balanced prose", "LP0B_GOLD_START_LANGUAGE_BALANCED", "LP1_CANONICAL_ONCE", "final_state_correct", fs_margin, "gold"),
        ("LP0BV visible verbatim contract - LP0B call-balanced prose", "LP0B_GOLD_START_LANGUAGE_BALANCED", "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM", "verbatim_arguments_correct", fs_margin, "gold"),
        ("LP1 canonical once - LP0BV visible verbatim contract", "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM", "LP1_CANONICAL_ONCE", "verbatim_arguments_correct", fs_margin, "gold"),
        ("LP1 canonical once - LP0G gold-start prose (secondary)", "LP0G_GOLD_START_LANGUAGE", "LP1_CANONICAL_ONCE", "final_state_correct", fs_margin, "gold"),
        ("LP1 - LP0 practical end-to-end", "LP0_LANGUAGE_THROUGHOUT", "LP1_CANONICAL_ONCE", "final_state_correct", fs_margin, "runtime"),
        ("LP2 - LP1 procedure", "LP1_CANONICAL_ONCE", "LP2_CANONICAL_PROCEDURE", "final_state_correct", fs_margin, "gold"),
        ("LP3 - LP2 typed action", "LP2_CANONICAL_PROCEDURE", "LP3_CANONICAL_PROCEDURE_TOOL", "final_state_correct", fs_margin, "gold"),
        ("Retrieved memory - Static glossary", "M1_STATIC_GLOSSARY", "M2_RETRIEVED_MEMORY", "full_call_correct", margin, "none"),
        ("Stable - Lexical drift", "AL_DRIFT", "AL_CANONICAL", "final_state_correct", fs_margin, "gold"),
    ]
    out = []
    for label, arch_a, arch_b, field, cmp_margin, mode in comparisons:
        result = paired_comparison(
            scores, arch_a, arch_b, field, cmp_margin,
            samples=samples, seed=seed, intent_mode=mode, label=label,
            confidence=confidence,
        )
        if result["n_pairs"] > 0:
            out.append(result)
    return out


# ---------------------------------------------------------------- P ladder (§38.6, §33.11)


def formalization_transitions(scores: list[dict], *, samples: int = 2000, seed: int = 104729,
                              margin: float = 0.02, confidence: float = 0.95) -> list[dict]:
    expected_cohort = {
        "P0_RAW_PROPOSAL": ("none", "none", "none"),
        "P1_CLARIFY_PROPOSAL": ("none", "none", "none"),
        "P2_CANONICAL_PROPOSAL": ("runtime", "none", "none"),
        "P3_CANONICAL_PROCEDURE_PROPOSAL": ("runtime", "gold", "inline"),
        "P4_CANONICAL_PROCEDURE_TOOL": ("runtime", "gold", "inline"),
    }

    def runtime_cohort(architecture: str) -> list[dict]:
        mode, selection, packaging = expected_cohort[architecture]
        return [
            score for score in scores
            if score["architecture"] == architecture
            and (score.get("metadata", {}).get("intent_mode") or "none") == mode
            and (score.get("metadata", {}).get("procedure_selection") or "none") == selection
            and (score.get("metadata", {}).get("procedure_packaging") or "none") == packaging
        ]

    out = []
    ladder = [arch for arch in P_LADDER]
    for arch_a, arch_b in zip(ladder, ladder[1:]):
        quality = paired_comparison(
            scores, arch_a, arch_b, "final_state_correct", margin,
            samples=samples, seed=seed, intent_mode="runtime",
            label=f"{arch_b} - {arch_a} (final state)", confidence=confidence,
        )
        group_a = runtime_cohort(arch_a)
        group_b = runtime_cohort(arch_b)
        fa_a = clarification_metrics(group_a)["false_action_rate"]
        fa_b = clarification_metrics(group_b)["false_action_rate"]
        cost_a = usage_metrics(group_a)
        cost_b = usage_metrics(group_b)
        out.append({
            "transition": f"{arch_a} -> {arch_b}",
            "marginal_quality": quality,
            "marginal_safety": {
                "false_action_before": fa_a,
                "false_action_after": fa_b,
                "delta": (fa_a - fa_b) if fa_a is not None and fa_b is not None else None,
            },
            "marginal_cost": {
                "calls_delta": cost_b["mean_model_calls"] - cost_a["mean_model_calls"]
                if cost_a["mean_model_calls"] is not None and cost_b["mean_model_calls"] is not None else None,
                "tokens_delta": cost_b["mean_total_tokens"] - cost_a["mean_total_tokens"]
                if cost_a["mean_total_tokens"] is not None and cost_b["mean_total_tokens"] is not None else None,
                "latency_ms_delta": cost_b["mean_latency_ms"] - cost_a["mean_latency_ms"]
                if cost_a["mean_latency_ms"] is not None and cost_b["mean_latency_ms"] is not None else None,
            },
        })
    # equivalence against P1 as the strong NL baseline (§39.8)
    for arch in ladder[2:]:
        out.append({
            "transition": f"P1_CLARIFY_PROPOSAL -> {arch} (vs strong baseline)",
            "marginal_quality": paired_comparison(
                scores, "P1_CLARIFY_PROPOSAL", arch, "final_state_correct", margin,
                samples=samples, seed=seed, intent_mode="runtime",
                label=f"{arch} - P1_CLARIFY_PROPOSAL", confidence=confidence,
            ),
        })
    return out


def component_ablations(scores: list[dict], *, samples: int = 2000, seed: int = 104729,
                        margin: float = 0.02, confidence: float = 0.95) -> list[dict]:
    """Gold-injected component ablations (§33.9)."""
    out = []
    specs = [
        ("canonical state (gold intent vs raw request)", "P1_CLARIFY_PROPOSAL", "P2_CANONICAL_PROPOSAL", "gold"),
        ("runtime canonicalization error (runtime vs gold P2)", None, None, None),
        ("procedure information (gold P2 vs unordered fact control)", "P2_CANONICAL_PROPOSAL", "P2F_CANONICAL_FACTS_PROPOSAL", "gold"),
        ("procedure structure and named handle (fact control vs gold P3)", "P2F_CANONICAL_FACTS_PROPOSAL", "P3_CANONICAL_PROCEDURE_PROPOSAL", "gold"),
        ("action interface (gold P3 vs gold P4)", "P3_CANONICAL_PROCEDURE_PROPOSAL", "P4_CANONICAL_PROCEDURE_TOOL", "gold"),
    ]
    for label, arch_a, arch_b, mode in specs:
        if arch_a is None:
            runtime = [s for s in scores if s["architecture"] == "P2_CANONICAL_PROPOSAL"
                       and s.get("metadata", {}).get("intent_mode") == "runtime"
                       and s.get("metadata", {}).get("primary_h1")]
            gold = [s for s in scores if s["architecture"] == "P2_CANONICAL_PROPOSAL"
                    and s.get("metadata", {}).get("intent_mode") == "gold"
                    and s.get("metadata", {}).get("primary_h1")]
            paired: list[tuple[str, float, float]] = []
            gold_map = {(s["case_id"], s.get("request_id"), s.get("repetition")): s for s in gold}
            for s in runtime:
                key = (s["case_id"], s.get("request_id"), s.get("repetition"))
                other = gold_map.get(key)
                if other and s.get("final_state_correct") is not None and other.get("final_state_correct") is not None:
                    paired.append((s["case_id"], 1.0 if s["final_state_correct"] else 0.0,
                                   1.0 if other["final_state_correct"] else 0.0))
            delta = cluster_bootstrap_delta(
                paired, samples=samples, seed=seed, confidence=confidence
            )
            case_ids = sorted({case_id for case_id, _a, _b in paired})
            family_by_case = {
                score["case_id"]: (
                    score.get("metadata", {}).get("family_id") or score["case_id"]
                )
                for score in scores
            }
            family_ids = sorted({family_by_case.get(case_id, case_id) for case_id in case_ids})
            out.append({"ablation": label,
                        **practical_equivalence("P2 gold - P2 runtime", delta, margin).to_dict(),
                        "n_pairs": len(paired),
                        "n_independent_cases": len(case_ids),
                        "independent_case_ids": case_ids,
                        "n_operation_families": len(family_ids),
                        "operation_family_ids": family_ids,
                        "pairing_cohorts": [
                            comparison_selector("P2_CANONICAL_PROPOSAL", "runtime"),
                            comparison_selector("P2_CANONICAL_PROPOSAL", "gold"),
                        ]})
            continue
        result = paired_comparison(scores, arch_a, arch_b, "final_state_correct", margin,
                                   samples=samples, seed=seed, intent_mode=mode, label=label,
                                   confidence=confidence)
        result["ablation"] = label
        out.append(result)
    # packaging ablation
    inline = [s for s in scores if s["architecture"] == "P3_CANONICAL_PROCEDURE_PROPOSAL"
              and s.get("metadata", {}).get("procedure_packaging") == "inline"
              and s.get("metadata", {}).get("intent_mode") == "gold"
              and s.get("metadata", {}).get("procedure_selection") == "gold"
              and s.get("metadata", {}).get("primary_h1")]
    packaged = [s for s in scores if s["architecture"] == "P3_CANONICAL_PROCEDURE_PROPOSAL"
                and s.get("metadata", {}).get("procedure_packaging") == "packaged"
                and s.get("metadata", {}).get("primary_h1")]
    packaged_map = {(s["case_id"], s.get("request_id"), s.get("repetition")): s for s in packaged}
    paired = []
    for s in inline:
        key = (s["case_id"], s.get("request_id"), s.get("repetition"))
        other = packaged_map.get(key)
        if other and s.get("final_state_correct") is not None and other.get("final_state_correct") is not None:
            paired.append((s["case_id"], 1.0 if s["final_state_correct"] else 0.0,
                           1.0 if other["final_state_correct"] else 0.0))
    if paired:
        delta = cluster_bootstrap_delta(
            paired, samples=samples, seed=seed, confidence=confidence
        )
        case_ids = sorted({case_id for case_id, _a, _b in paired})
        family_by_case = {
            score["case_id"]: (
                score.get("metadata", {}).get("family_id") or score["case_id"]
            )
            for score in scores
        }
        family_ids = sorted({family_by_case.get(case_id, case_id) for case_id in case_ids})
        out.append({"ablation": "procedure packaging (inline vs packaged skill)",
                    **practical_equivalence("packaged - inline", delta, margin).to_dict(),
                    "n_pairs": len(paired),
                    "n_independent_cases": len(case_ids),
                    "independent_case_ids": case_ids,
                    "n_operation_families": len(family_ids),
                    "operation_family_ids": family_ids,
                    "pairing_cohorts": [
                        comparison_selector(
                            "P3_CANONICAL_PROCEDURE_PROPOSAL", "gold"
                        ),
                        {
                            **comparison_selector(
                                "P3_CANONICAL_PROCEDURE_PROPOSAL", "gold"
                            ),
                            "procedure_packaging": "packaged",
                        },
                    ]})
    # selection ablation
    runtime_selected = [s for s in scores if s.get("metadata", {}).get("procedure_selection") == "runtime"]
    if runtime_selected:
        selection_events = [
            s.get("metadata", {}).get("procedure_selection_correct")
            for s in runtime_selected
            if s.get("metadata", {}).get("procedure_selection_correct") is not None
        ]
        out.append({
            "ablation": "procedure selection (gold registry vs runtime router)",
            "runtime_selected_n": len(runtime_selected),
            "procedure_selection_accuracy": (
                sum(1 for value in selection_events if value) / len(selection_events)
                if selection_events else None
            ),
            "note": "selection correctness is recorded per cell in procedure-events.jsonl",
        })
    return out


# ---------------------------------------------------------------- persistence (§38.11)


def persistence_metrics(
    scores: list[dict], *, minimum_independent_cases: int = 1,
    minimum_operation_families: int = 1,
) -> dict[str, Any]:
    lp_scores = [s for s in scores if s["architecture"].startswith("LP")]
    out = {}
    grouped = _group(
        lp_scores,
        lambda s: (
            s["architecture"],
            s.get("metadata", {}).get("intent_mode") or "none",
            s.get("metadata", {}).get("procedure_selection") or "none",
            s.get("metadata", {}).get("procedure_packaging") or "none",
        ),
    )
    for (arch, mode, selection, packaging), group in sorted(grouped.items()):
        persists = [s.get("persistence") or {} for s in group]
        depths = [p.get("nl_persistence_depth") for p in persists if p.get("nl_persistence_depth") is not None]
        reinterp = [p.get("reinterpretation_count") for p in persists if p.get("reinterpretation_count") is not None]
        changes = [p.get("representation_change_count") for p in persists if p.get("representation_change_count") is not None]
        divergences = [s.get("metadata", {}).get("first_divergence_stage") for s in group]
        operation_divergences = [
            s.get("metadata", {}).get("first_operation_divergence") for s in group
        ]
        argument_divergences = [
            s.get("metadata", {}).get("first_argument_divergence") for s in group
        ]
        verbatim_divergences = [
            s.get("metadata", {}).get("first_verbatim_argument_divergence")
            for s in group
        ]
        verbatim_observed = [
            score for score in group
            if score.get("verbatim_arguments_correct") is not None
        ]
        divergence_then_recovery = [
            score for score in verbatim_observed
            if score.get("metadata", {}).get(
                "first_verbatim_argument_divergence"
            ) is not None
            and score.get("verbatim_arguments_correct") is True
        ]
        divergence_without_recovery = [
            score for score in verbatim_observed
            if score.get("metadata", {}).get(
                "first_verbatim_argument_divergence"
            ) is not None
            and score.get("verbatim_arguments_correct") is False
        ]
        pristine_final_success = [
            score for score in verbatim_observed
            if score.get("metadata", {}).get(
                "first_verbatim_argument_divergence"
            ) is None
            and score.get("verbatim_arguments_correct") is True
        ]
        divergence_observed = (
            len(divergence_then_recovery) + len(divergence_without_recovery)
        )
        final_states = [s for s in group if s.get("final_state_correct") is not None]
        cohort_id = f"{arch}|{mode}|{selection}|{packaging}"
        case_ids = {score["case_id"] for score in group}
        family_ids = {
            score.get("metadata", {}).get("family_id") or score["case_id"]
            for score in group
        }
        interpretation_allowed = len(case_ids) >= minimum_independent_cases
        generalization_allowed = (
            interpretation_allowed
            and len(family_ids) >= minimum_operation_families
        )
        out[cohort_id] = {
            "architecture": arch,
            "intent_mode": mode,
            "procedure_selection": selection,
            "procedure_packaging": packaging,
            "n": len(group),
            "n_independent_cases": len(case_ids),
            "n_operation_families": len(family_ids),
            "interpretation_allowed": interpretation_allowed,
            "generalization_allowed": generalization_allowed,
            "interpretation_scope": (
                "generalizable" if generalization_allowed else (
                    "tested_operation_families_only"
                    if interpretation_allowed else "exploratory"
                )
            ),
            "interpretation_warning": (
                f"Causal interpretation withheld: {len(case_ids)} independent "
                f"canonical case(s) were available; at least "
                f"{minimum_independent_cases} are required."
                if not interpretation_allowed else (
                    f"Interpretation is limited to {len(family_ids)} tested "
                    "operation family or families."
                    if not generalization_allowed else None
                )
            ),
            "mean_nl_persistence_depth": sum(depths) / len(depths) if depths else None,
            "mean_reinterpretation_count": sum(reinterp) / len(reinterp) if reinterp else None,
            "mean_representation_changes": sum(changes) / len(changes) if changes else None,
            "first_divergence_distribution": {
                stage or "none": divergences.count(stage) for stage in set(divergences)
            },
            "first_operation_divergence_distribution": {
                stage or "none": operation_divergences.count(stage)
                for stage in set(operation_divergences)
            },
            "first_argument_divergence_distribution": {
                stage or "none": argument_divergences.count(stage)
                for stage in set(argument_divergences)
            },
            "first_verbatim_argument_divergence_distribution": {
                stage or "none": verbatim_divergences.count(stage)
                for stage in set(verbatim_divergences)
            },
            "verbatim_preservation_accuracy": (
                sum(
                    1 for score in group
                    if (score.get("argument_preservation") or {}).get(
                        "verbatim_all_correct"
                    ) is True
                )
                / sum(
                    1 for score in group
                    if (score.get("argument_preservation") or {}).get(
                        "verbatim_all_correct"
                    ) is not None
                )
                if any(
                    (score.get("argument_preservation") or {}).get(
                        "verbatim_all_correct"
                    ) is not None
                    for score in group
                ) else None
            ),
            "intermediate_divergence_then_final_recovery_count": len(
                divergence_then_recovery
            ),
            "intermediate_divergence_without_final_recovery_count": len(
                divergence_without_recovery
            ),
            "pristine_final_success_count": len(pristine_final_success),
            "recovery_rate_after_intermediate_verbatim_divergence": (
                len(divergence_then_recovery) / divergence_observed
                if divergence_observed else None
            ),
            "recovery_note": (
                "First divergence is an earliest-stage diagnostic, not a monotonic "
                "failure label. A later stage may restore the exact value."
            ),
            "final_state_accuracy": (
                sum(1 for s in final_states if s["final_state_correct"]) / len(final_states)
                if final_states else None
            ),
        }
    return out


# ---------------------------------------------------------------- measurement validity / rendering contrast


def measurement_warnings(
    scores: list[dict], *, minimum_schema_validity: float = 0.99
) -> list[dict[str, Any]]:
    warnings = []
    grouped = _group(
        scores,
        lambda s: (
            s["track"],
            s["architecture"],
            s.get("metadata", {}).get("intent_mode") or "none",
            s.get("metadata", {}).get("procedure_selection") or "none",
            s.get("metadata", {}).get("procedure_packaging") or "none",
        ),
    )
    for cohort, group in sorted(grouped.items()):
        rate = sum(1 for score in group if score.get("schema_valid")) / len(group)
        if rate < minimum_schema_validity:
            warnings.append({
                "kind": "schema_contract_degraded",
                "track": cohort[0],
                "architecture": cohort[1],
                "intent_mode": cohort[2],
                "procedure_selection": cohort[3],
                "procedure_packaging": cohort[4],
                "schema_validity": rate,
                "minimum": minimum_schema_validity,
                "n": len(group),
                "interpretation": "Report outcomes, but do not attribute a causal gain to this condition.",
            })
    return warnings


def apply_interpretation_gate(
    comparison: dict[str, Any], warnings: list[dict[str, Any]],
    *, minimum_independent_cases: int = 1,
    minimum_operation_families: int = 1,
) -> dict[str, Any]:
    """Mark a paired result as descriptive-only when either exact cohort failed.

    The observations and calculated interval remain unchanged. Only causal
    interpretation is withheld, which preserves raw failures for audit.
    """
    warning_keys = {
        (
            warning.get("architecture"),
            warning.get("intent_mode"),
            warning.get("procedure_selection"),
            warning.get("procedure_packaging"),
        )
        for warning in warnings
    }
    cohorts = comparison.get("pairing_cohorts") or []
    failed = [
        cohort for cohort in cohorts
        if (
            cohort.get("architecture"),
            cohort.get("intent_mode"),
            cohort.get("procedure_selection"),
            cohort.get("procedure_packaging"),
        ) in warning_keys
    ]
    n_cases = int(comparison.get("n_independent_cases") or 0)
    n_families = int(comparison.get("n_operation_families") or 0)
    insufficient_cases = n_cases < minimum_independent_cases
    insufficient_families = n_families < minimum_operation_families
    reasons = []
    if failed:
        reasons.append(
            "an exact comparison cohort failed the schema-validity gate"
        )
    if not comparison.get("n_pairs"):
        reasons.append("no paired observations were available")
    if insufficient_cases:
        reasons.append(
            f"{n_cases} independent canonical case(s) were available; "
            f"at least {minimum_independent_cases} are required"
        )
    return {
        **comparison,
        "minimum_independent_cases_for_interpretation": minimum_independent_cases,
        "minimum_operation_families_for_generalization": minimum_operation_families,
        "interpretation_allowed": (
            bool(comparison.get("n_pairs")) and not failed and not insufficient_cases
        ),
        "generalization_allowed": (
            bool(comparison.get("n_pairs")) and not failed
            and not insufficient_cases and not insufficient_families
        ),
        "interpretation_scope": (
            "exploratory" if insufficient_cases else (
                "tested_operation_families_only" if insufficient_families
                else "generalizable"
            )
        ),
        "interpretation_warning": (
            "Causal interpretation withheld because " + "; ".join(reasons) + "."
            if reasons else (
                f"Interpretation is limited to the tested operation families because "
                f"{n_families} family or families were available; at least "
                f"{minimum_operation_families} are required for generalization."
                if insufficient_families else None
            )
        ),
        "failed_interpretation_cohorts": failed,
    }


def rendering_contrast_metrics(
    scores: list[dict], *, samples: int = 2000, seed: int = 104729,
    confidence: float = 0.95, margin: float = 0.01,
) -> dict[str, Any]:
    discovered = [s for s in scores if s["architecture"] == "F_MODEL_DISCOVERED"]
    distinct = [
        s for s in discovered
        if s.get("metadata", {}).get("rendering_lexically_distinct") is True
    ]
    distinct_cases = {s["case_id"] for s in distinct}
    distinct_pool = [s for s in scores if s["case_id"] in distinct_cases]
    by_operation = {}
    for operation_id, group in sorted(_group(
        discovered,
        lambda score: score.get("metadata", {}).get("expected_operation_id") or "UNKNOWN",
    ).items()):
        by_operation[operation_id] = {
            "n": len(group),
            "full_call_accuracy": (
                sum(1 for score in group if score.get("full_call_correct")) / len(group)
                if group else None
            ),
            "lexically_distinct_n": sum(
                1 for score in group
                if score.get("metadata", {}).get("rendering_lexically_distinct") is True
            ),
        }
    return {
        "n_model_discovered_cells": len(discovered),
        "n_lexically_distinct_cells": len(distinct),
        "n_identical_to_canonical_cells": len(discovered) - len(distinct),
        "distinct_case_ids": sorted(distinct_cases),
        "by_operation": by_operation,
        "all_cases_comparison": paired_comparison(
            scores,
            "C_GOLD",
            "F_MODEL_DISCOVERED",
            "full_call_correct",
            margin,
            samples=samples,
            seed=seed,
            restrict_h1=False,
            intent_mode="gold",
            label="F_MODEL_DISCOVERED - C_GOLD (all renderings)",
            confidence=confidence,
        ),
        "lexically_distinct_comparison": paired_comparison(
            distinct_pool,
            "C_GOLD",
            "F_MODEL_DISCOVERED",
            "full_call_correct",
            margin,
            samples=samples,
            seed=seed,
            restrict_h1=False,
            intent_mode="gold",
            label="F_MODEL_DISCOVERED - C_GOLD (lexically distinct only)",
            confidence=confidence,
        ),
        "interpretation": (
            "Identical instantiated renderings are recorded as no lexical contrast and are not evidence of lexical equivalence."
        ),
    }


# ---------------------------------------------------------------- elicitation (§38.5)


def elicitation_metrics(
    scores: list[dict], *, samples: int = 2000, seed: int = 104729,
    confidence: float = 0.95,
) -> dict[str, Any]:
    intent_scores = [s for s in scores if s["track"] == "intent_elicitation"]
    out = {}
    for arch, group in sorted(_group(intent_scores, lambda s: s["architecture"]).items()):
        resolved = [s for s in group if s.get("metadata", {}).get("resolved")]
        turns = [s.get("metadata", {}).get("turns_used") for s in group if s.get("metadata", {}).get("turns_used")]
        false_actions = [s for s in group if s.get("false_action")]
        unresolved_without_action = [
            s for s in group
            if not s.get("metadata", {}).get("resolved") and not s.get("false_action")
        ]
        unresolved_rows = [
            {
                **s,
                "unresolved_without_action": (
                    not s.get("metadata", {}).get("resolved")
                    and not s.get("false_action")
                ),
            }
            for s in group
        ]
        resolution_correct = [
            s for s in resolved
            if s.get("full_call_correct") and s.get("final_state_correct") is not False
        ]
        out[arch] = {
            "n": len(group),
            "resolution_rate": len(resolved) / len(group) if group else None,
            "final_resolution_accuracy": (
                len(resolution_correct) / len(resolved) if resolved else None
            ),
            "false_action_rate": len(false_actions) / len(group) if group else None,
            "unresolved_without_action_rate": (
                len(unresolved_without_action) / len(group) if group else None
            ),
            "unresolved_without_action_interval": _ci(
                unresolved_rows, "unresolved_without_action", samples=samples,
                seed=seed, confidence=confidence,
            ),
            "mean_turns_to_resolution": (
                sum(s.get("metadata", {}).get("turns_used", 0) for s in resolved) / len(resolved)
                if resolved else None
            ),
            "mean_model_calls": (
                sum(s.get("usage", {}).get("model_calls", 0) for s in group) / len(group)
                if group else None
            ),
        }
    return out


def adequacy_assessment_metrics(
    scores: list[dict], *, samples: int = 2000, seed: int = 104729,
    confidence: float = 0.95,
) -> dict[str, Any]:
    eligible = [
        {**score, "adequacy_assessment_correct": score.get("metadata", {}).get("adequacy_assessment_correct")}
        for score in scores
        if score.get("metadata", {}).get("adequacy_assessment_correct") is not None
    ]
    return {
        architecture: _ci(
            group, "adequacy_assessment_correct", samples=samples, seed=seed,
            confidence=confidence,
        )
        for architecture, group in sorted(
            _group(eligible, lambda score: score["architecture"]).items()
        )
    }


def procedure_selection_metrics(
    scores: list[dict], *, samples: int = 2000, seed: int = 104729,
    confidence: float = 0.95,
) -> dict[str, Any]:
    eligible = [
        {**score, "procedure_selection_correct": score.get("metadata", {}).get("procedure_selection_correct")}
        for score in scores
        if score.get("metadata", {}).get("procedure_selection_correct") is not None
    ]
    return {
        architecture: _ci(
            group, "procedure_selection_correct", samples=samples, seed=seed,
            confidence=confidence,
        )
        for architecture, group in sorted(
            _group(eligible, lambda score: score["architecture"]).items()
        )
    }


def typed_interface_metrics(
    scores: list[dict], *, samples: int = 2000, seed: int = 104729,
    confidence: float = 0.95,
) -> dict[str, Any]:
    eligible = [
        {**score, "typed_interface_valid": not bool(score.get("interface_errors"))}
        for score in scores
        if score.get("architecture") == "P4_CANONICAL_PROCEDURE_TOOL"
    ]
    if not eligible:
        return {}
    grouped = _group(
        eligible,
        lambda score: (
            score.get("metadata", {}).get("intent_mode") or "none",
            score.get("metadata", {}).get("procedure_selection") or "none",
            score.get("metadata", {}).get("procedure_packaging") or "none",
        ),
    )
    return {
        f"P4_CANONICAL_PROCEDURE_TOOL|{mode}|{selection}|{packaging}": {
            "architecture": "P4_CANONICAL_PROCEDURE_TOOL",
            "intent_mode": mode,
            "procedure_selection": selection,
            "procedure_packaging": packaging,
            **_ci(
                group, "typed_interface_valid", samples=samples, seed=seed,
                confidence=confidence,
            ),
        }
        for (mode, selection, packaging), group in sorted(grouped.items())
    }


# ---------------------------------------------------------------- usage / complexity


def usage_metrics(scores: list[dict]) -> dict[str, Any]:
    if not scores:
        return {"mean_model_calls": None, "mean_total_tokens": None, "mean_latency_ms": None}
    calls = [s.get("usage", {}).get("model_calls", 0) for s in scores]
    tokens = [
        (s.get("usage", {}).get("prompt_tokens", 0) or 0)
        + (s.get("usage", {}).get("completion_tokens", 0) or 0)
        for s in scores
    ]
    latencies = sorted(s.get("latency_ms") or 0.0 for s in scores)
    def _pct(p: float) -> float:
        index = min(int(p * len(latencies)), len(latencies) - 1)
        return latencies[index]
    return {
        "mean_model_calls": sum(calls) / len(calls),
        "mean_total_tokens": sum(tokens) / len(tokens),
        "mean_latency_ms": sum(latencies) / len(latencies),
        "latency_p50_ms": _pct(0.50),
        "latency_p95_ms": _pct(0.95),
        "transport_error_cells": sum(
            1 for s in scores if (s.get("error_category") or "").startswith("transport")
        ),
    }


ARCHITECTURE_BOM: dict[str, dict[str, Any]] = {
    "A0_DIRECT": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 0},
    "A1_DIRECT_CLARIFY": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 0},
    "B_RUNTIME": {"mutable_model_stages": 2, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": [], "nl_handoffs": 0},
    "C_RUNTIME": {"mutable_model_stages": 2, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": ["rendering registry"], "nl_handoffs": 0},
    "B_GOLD": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 0},
    "C_GOLD": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": ["rendering registry"], "nl_handoffs": 0},
    "D_DEFINITION_ONLY": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": ["rendering registry"], "nl_handoffs": 0},
    "E_ORGANIZATION_TERM": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": ["rendering registry"], "nl_handoffs": 0},
    "F_MODEL_DISCOVERED": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": ["rendering registry"], "nl_handoffs": 0},
    "B_EXTERNAL_GATE": {"mutable_model_stages": 3, "external_services": ["execution provider", "assessor provider", "canonicalizer provider"], "persisted_stores": [], "nl_handoffs": 1},
    "B_EXTERNAL_GATE_GOLD": {"mutable_model_stages": 2, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": [], "nl_handoffs": 1},
    "M0_NO_MEMORY": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 0},
    "M1_STATIC_GLOSSARY": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": ["organization glossary"], "nl_handoffs": 0},
    "M2_RETRIEVED_MEMORY": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": ["organization glossary", "retrieval index"], "nl_handoffs": 0},
    "M3_CANONICAL_RESOLVER": {"mutable_model_stages": 2, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": [], "nl_handoffs": 0},
    "M4_PERSONALIZED_MEMORY": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": ["organization glossary", "retrieval index", "personal mapping store"], "nl_handoffs": 0},
    "P0_RAW_PROPOSAL": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 0},
    "P1_CLARIFY_PROPOSAL": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 0},
    "P2_CANONICAL_PROPOSAL": {"mutable_model_stages": 2, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": [], "nl_handoffs": 0},
    "P2F_CANONICAL_FACTS_PROPOSAL": {"mutable_model_stages": 1, "external_services": ["execution provider"], "persisted_stores": ["procedure fact control"], "nl_handoffs": 0},
    "P3_CANONICAL_PROCEDURE_PROPOSAL": {"mutable_model_stages": 2, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": ["procedure registry"], "nl_handoffs": 0},
    "P4_CANONICAL_PROCEDURE_TOOL": {"mutable_model_stages": 2, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": ["procedure registry", "typed tool registry"], "nl_handoffs": 0},
    "LP0_LANGUAGE_THROUGHOUT": {"mutable_model_stages": 7, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 4},
    "LP0G_GOLD_START_LANGUAGE": {"mutable_model_stages": 7, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 4},
    "LP0B_GOLD_START_LANGUAGE_BALANCED": {"mutable_model_stages": 4, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 4},
    "LP0BV_GOLD_START_LANGUAGE_BALANCED_VERBATIM": {"mutable_model_stages": 4, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 4},
    "LP1_CANONICAL_ONCE": {"mutable_model_stages": 4, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": [], "nl_handoffs": 0},
    "LP2_CANONICAL_PROCEDURE": {"mutable_model_stages": 4, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": ["procedure registry"], "nl_handoffs": 0},
    "LP3_CANONICAL_PROCEDURE_TOOL": {"mutable_model_stages": 4, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": ["procedure registry", "typed tool registry"], "nl_handoffs": 0},
}


def complexity_bill_of_materials(scores: list[dict]) -> dict[str, Any]:
    out = {}
    grouped = _group(
        scores,
        lambda s: (
            s["architecture"],
            s.get("metadata", {}).get("intent_mode") or "none",
            s.get("metadata", {}).get("procedure_selection") or "none",
            s.get("metadata", {}).get("procedure_packaging") or "none",
        ),
    )
    for (arch, mode, selection, packaging), group in sorted(grouped.items()):
        bom = dict(ARCHITECTURE_BOM.get(arch, {}))
        measured = usage_metrics(group)
        configured_stages = bom.get("mutable_model_stages")
        configured_handoffs = bom.get("nl_handoffs")
        persistence_depths = [
            (score.get("persistence") or {}).get("nl_persistence_depth")
            for score in group
            if (score.get("persistence") or {}).get("nl_persistence_depth") is not None
        ]
        services = list(bom.get("external_services") or [])
        if mode == "gold":
            services = [service for service in services if service != "canonicalizer provider"]
        bom.update({
            "architecture": arch,
            "intent_mode": mode,
            "procedure_selection": selection,
            "procedure_packaging": packaging,
            "configured_mutable_model_stages": configured_stages,
            "mutable_model_stages": measured.get("mean_model_calls"),
            "configured_nl_handoffs": configured_handoffs,
            "nl_handoffs": (
                sum(persistence_depths) / len(persistence_depths)
                if persistence_depths else 0
            ),
            "external_services": services,
        })
        bom["measured"] = measured
        out[f"{arch}|{mode}|{selection}|{packaging}"] = bom
    return out
