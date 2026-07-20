"""Metric aggregation over score records (spec §38, §44).

Everything here is a pure function of the score records plus configuration.
Case-clustered intervals come from :mod:`lexstab.metrics.statistics`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from lexstab.metrics.statistics import (
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


def _ci(scores: list[dict], field: str, *, samples: int, seed: int) -> dict[str, Any]:
    return cluster_bootstrap_rate(_obs(scores, field), samples=samples, seed=seed).to_dict()


def _group(scores: list[dict], key_fn) -> dict[Any, list[dict]]:
    groups: dict[Any, list[dict]] = defaultdict(list)
    for score in scores:
        groups[key_fn(score)].append(score)
    return dict(groups)


def primary_h1_stratum(scores: list[dict]) -> list[dict]:
    """Only frozen ADEQUATE/UNAMBIGUOUS/EXECUTE/INVARIANT requests (§49.1)."""
    return [score for score in scores if score.get("metadata", {}).get("primary_h1")]


# ---------------------------------------------------------------- headline


def headline_metrics(scores: list[dict], *, samples: int = 2000, seed: int = 104729) -> list[dict]:
    rows = []
    for (track, arch), group in sorted(_group(
        scores, lambda s: (s["track"], s["architecture"])
    ).items()):
        h1 = primary_h1_stratum(group)
        clar = clarification_metrics(group)
        invariance = operational_invariance(h1)
        contrast_scores = [s for s in group if s.get("contrast_correct") is not None]
        row = {
            "track": track,
            "architecture": arch,
            "n_cells": len(group),
            "schema_validity": _ci(group, "schema_valid", samples=samples, seed=seed),
            "decision_accuracy": _ci(group, "decision_correct", samples=samples, seed=seed),
            "full_call_accuracy": _ci(h1 or group, "full_call_correct", samples=samples, seed=seed),
            "final_state_accuracy": _ci(
                [s for s in (h1 or group) if s.get("final_state_correct") is not None],
                "final_state_correct", samples=samples, seed=seed,
            ),
            "operational_invariance": invariance,
            "contrast_accuracy": _ci(contrast_scores, "contrast_correct", samples=samples, seed=seed),
            "false_action_rate": clar["false_action_rate"],
            "clarification": clar,
            "refusal_correctness": _ci(
                [s for s in group if s.get("refusal_correct") is not None],
                "refusal_correct", samples=samples, seed=seed,
            ),
            "usage": usage_metrics(group),
        }
        rows.append(row)
    return rows


# ---------------------------------------------------------------- robustness (§38.2)


def robustness_metrics(scores: list[dict]) -> dict[str, Any]:
    h1 = primary_h1_stratum(scores)
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
                request_decisions[request_id] = tuple(
                    sorted({(s.get("decision"), (s.get("tool_call") or {}).get("tool") if s.get("tool_call") else None) for s in reps})
                )
            accs = list(request_accs.values())
            base = [
                acc for request_id, acc in request_accs.items()
                if any(
                    s.get("metadata", {}).get("lexical_distance_band") == "LOW"
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


def operational_invariance(h1_scores: list[dict]) -> dict[str, Any]:
    by_case = _group(h1_scores, lambda s: s["case_id"])
    values = []
    for case_id, case_scores in by_case.items():
        values.append((case_id, 1.0 if all(
            s["full_call_correct"] and s.get("final_state_correct") is not False
            for s in case_scores
        ) else 0.0))
    if not values:
        return {"estimate": None, "n_cases": 0}
    return {
        "estimate": sum(v for _c, v in values) / len(values),
        "n_cases": len(values),
    }


# ---------------------------------------------------------------- clarification (§38.4)


def clarification_metrics(scores: list[dict]) -> dict[str, Any]:
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
        if intent_mode and score.get("metadata", {}).get("intent_mode") not in (intent_mode, "none", None):
            return False
        if score.get("metadata", {}).get("procedure_packaging") == "packaged":
            return False
        if score.get("metadata", {}).get("procedure_selection") == "runtime":
            return False
        return True

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
) -> dict[str, Any]:
    paired = _paired_values(scores, arch_a, arch_b, field, restrict_h1=restrict_h1, intent_mode=intent_mode)
    delta = cluster_bootstrap_delta(paired, samples=samples, seed=seed)
    decision = practical_equivalence(label or f"{arch_b} - {arch_a}", delta, margin)
    discordance = paired_discordance(paired)
    return {
        **decision.to_dict(),
        "field": field,
        "n_pairs": len(paired),
        "secondary_mcnemar": discordance,
    }


def primary_comparisons(scores: list[dict], equivalence: dict[str, float],
                        *, samples: int = 2000, seed: int = 104729) -> list[dict]:
    margin = float(equivalence.get("success_margin", 0.01))
    fs_margin = float(equivalence.get("final_state_margin", margin))
    comparisons = [
        ("A1_DIRECT_CLARIFY - A0_DIRECT", "A0_DIRECT", "A1_DIRECT_CLARIFY", "full_call_correct", margin, None),
        ("B_RUNTIME - A1_DIRECT_CLARIFY", "A1_DIRECT_CLARIFY", "B_RUNTIME", "full_call_correct", margin, None),
        ("C_RUNTIME - A1_DIRECT_CLARIFY", "A1_DIRECT_CLARIFY", "C_RUNTIME", "full_call_correct", margin, None),
        ("C_GOLD - B_GOLD", "B_GOLD", "C_GOLD", "full_call_correct", margin, None),
        ("C_GOLD - B_GOLD (final state)", "B_GOLD", "C_GOLD", "final_state_correct", fs_margin, None),
        ("P1 - P0 clarification transition", "P0_RAW_PROPOSAL", "P1_CLARIFY_PROPOSAL", "final_state_correct", fs_margin, None),
        ("P2 - P1 canonical-intent transition", "P1_CLARIFY_PROPOSAL", "P2_CANONICAL_PROPOSAL", "final_state_correct", fs_margin, "runtime"),
        ("P3 - P2 reusable-procedure transition", "P2_CANONICAL_PROPOSAL", "P3_CANONICAL_PROCEDURE_PROPOSAL", "final_state_correct", fs_margin, "runtime"),
        ("P4 - P3 typed-interface transition", "P3_CANONICAL_PROCEDURE_PROPOSAL", "P4_CANONICAL_PROCEDURE_TOOL", "final_state_correct", fs_margin, "runtime"),
        ("LP1 canonical once - LP0G gold-start prose", "LP0G_GOLD_START_LANGUAGE", "LP1_CANONICAL_ONCE", "final_state_correct", fs_margin, "gold"),
        ("LP1 - LP0 practical end-to-end", "LP0_LANGUAGE_THROUGHOUT", "LP1_CANONICAL_ONCE", "final_state_correct", fs_margin, "runtime"),
        ("LP2 - LP1 procedure", "LP1_CANONICAL_ONCE", "LP2_CANONICAL_PROCEDURE", "final_state_correct", fs_margin, "gold"),
        ("LP3 - LP2 typed action", "LP2_CANONICAL_PROCEDURE", "LP3_CANONICAL_PROCEDURE_TOOL", "final_state_correct", fs_margin, "gold"),
        ("Retrieved memory - Static glossary", "M1_STATIC_GLOSSARY", "M2_RETRIEVED_MEMORY", "full_call_correct", margin, None),
        ("Stable - Lexical drift", "AL_DRIFT", "AL_CANONICAL", "final_state_correct", fs_margin, None),
    ]
    out = []
    for label, arch_a, arch_b, field, cmp_margin, mode in comparisons:
        result = paired_comparison(
            scores, arch_a, arch_b, field, cmp_margin,
            samples=samples, seed=seed, intent_mode=mode, label=label,
        )
        if result["n_pairs"] > 0:
            out.append(result)
    return out


# ---------------------------------------------------------------- P ladder (§38.6, §33.11)


def formalization_transitions(scores: list[dict], *, samples: int = 2000, seed: int = 104729,
                              margin: float = 0.02) -> list[dict]:
    out = []
    ladder = [arch for arch in P_LADDER]
    for arch_a, arch_b in zip(ladder, ladder[1:]):
        quality = paired_comparison(
            scores, arch_a, arch_b, "final_state_correct", margin,
            samples=samples, seed=seed, intent_mode="runtime",
            label=f"{arch_b} - {arch_a} (final state)",
        )
        group_a = [s for s in scores if s["architecture"] == arch_a]
        group_b = [s for s in scores if s["architecture"] == arch_b]
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
                label=f"{arch} - P1_CLARIFY_PROPOSAL",
            ),
        })
    return out


def component_ablations(scores: list[dict], *, samples: int = 2000, seed: int = 104729,
                        margin: float = 0.02) -> list[dict]:
    """Gold-injected component ablations (§33.9)."""
    out = []
    specs = [
        ("canonical state (gold intent vs raw request)", "P1_CLARIFY_PROPOSAL", "P2_CANONICAL_PROPOSAL", "gold"),
        ("runtime canonicalization error (runtime vs gold P2)", None, None, None),
        ("procedure content (gold P2 vs gold P3)", "P2_CANONICAL_PROPOSAL", "P3_CANONICAL_PROCEDURE_PROPOSAL", "gold"),
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
            delta = cluster_bootstrap_delta(paired, samples=samples, seed=seed)
            out.append({"ablation": label,
                        **practical_equivalence("P2 gold - P2 runtime", delta, margin).to_dict(),
                        "n_pairs": len(paired)})
            continue
        result = paired_comparison(scores, arch_a, arch_b, "final_state_correct", margin,
                                   samples=samples, seed=seed, intent_mode=mode, label=label)
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
        delta = cluster_bootstrap_delta(paired, samples=samples, seed=seed)
        out.append({"ablation": "procedure packaging (inline vs packaged skill)",
                    **practical_equivalence("packaged - inline", delta, margin).to_dict(),
                    "n_pairs": len(paired)})
    # selection ablation
    runtime_selected = [s for s in scores if s.get("metadata", {}).get("procedure_selection") == "runtime"]
    if runtime_selected:
        correct = [s for s in scores if s.get("procedure_adherence")]
        selection_events = [
            1.0 if s.get("metadata", {}).get("procedure_selection_correct", True) else 0.0
            for s in runtime_selected
        ]
        out.append({
            "ablation": "procedure selection (gold registry vs runtime router)",
            "runtime_selected_n": len(runtime_selected),
            "note": "selection correctness is recorded per cell in procedure-events.jsonl",
        })
    return out


# ---------------------------------------------------------------- persistence (§38.11)


def persistence_metrics(scores: list[dict]) -> dict[str, Any]:
    lp_scores = [s for s in scores if s["architecture"].startswith("LP")]
    out = {}
    for arch, group in sorted(_group(lp_scores, lambda s: s["architecture"]).items()):
        persists = [s.get("persistence") or {} for s in group]
        depths = [p.get("nl_persistence_depth") for p in persists if p.get("nl_persistence_depth") is not None]
        reinterp = [p.get("reinterpretation_count") for p in persists if p.get("reinterpretation_count") is not None]
        changes = [p.get("representation_change_count") for p in persists if p.get("representation_change_count") is not None]
        divergences = [s.get("metadata", {}).get("first_divergence_stage") for s in group]
        final_states = [s for s in group if s.get("final_state_correct") is not None]
        out[arch] = {
            "n": len(group),
            "mean_nl_persistence_depth": sum(depths) / len(depths) if depths else None,
            "mean_reinterpretation_count": sum(reinterp) / len(reinterp) if reinterp else None,
            "mean_representation_changes": sum(changes) / len(changes) if changes else None,
            "first_divergence_distribution": {
                stage or "none": divergences.count(stage) for stage in set(divergences)
            },
            "final_state_accuracy": (
                sum(1 for s in final_states if s["final_state_correct"]) / len(final_states)
                if final_states else None
            ),
        }
    return out


# ---------------------------------------------------------------- elicitation (§38.5)


def elicitation_metrics(scores: list[dict]) -> dict[str, Any]:
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
    "P3_CANONICAL_PROCEDURE_PROPOSAL": {"mutable_model_stages": 2, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": ["procedure registry"], "nl_handoffs": 0},
    "P4_CANONICAL_PROCEDURE_TOOL": {"mutable_model_stages": 2, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": ["procedure registry", "typed tool registry"], "nl_handoffs": 0},
    "LP0_LANGUAGE_THROUGHOUT": {"mutable_model_stages": 7, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 4},
    "LP0G_GOLD_START_LANGUAGE": {"mutable_model_stages": 7, "external_services": ["execution provider"], "persisted_stores": [], "nl_handoffs": 4},
    "LP1_CANONICAL_ONCE": {"mutable_model_stages": 5, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": [], "nl_handoffs": 0},
    "LP2_CANONICAL_PROCEDURE": {"mutable_model_stages": 5, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": ["procedure registry"], "nl_handoffs": 0},
    "LP3_CANONICAL_PROCEDURE_TOOL": {"mutable_model_stages": 5, "external_services": ["execution provider", "canonicalizer provider"], "persisted_stores": ["procedure registry", "typed tool registry"], "nl_handoffs": 0},
}


def complexity_bill_of_materials(scores: list[dict]) -> dict[str, Any]:
    out = {}
    for arch, group in sorted(_group(scores, lambda s: s["architecture"]).items()):
        bom = dict(ARCHITECTURE_BOM.get(arch, {}))
        bom["measured"] = usage_metrics(group)
        out[arch] = bom
    return out
