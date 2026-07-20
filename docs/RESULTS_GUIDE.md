# Results guide

How to read a completed run: where artifacts live, what every metric family means, how the
interpretation patterns of spec §44 map onto the numbers, and how the complexity decision is made.
Reports lead with outcomes, not raw calls (spec §44).

## 1. Run directory layout

Everything for one run lives under `runs/<id>/`:

| Artifact | Contents |
|---|---|
| `run-manifest.json` | Immutable record: benchmark root hash, resolved model roles and exact IDs, prompt/procedure/interface hashes, matrix hash and seed, run clock, `mocked`, `baseline_eligible` (spec §21.2) |
| `matrix.jsonl` / `matrix-skipped.jsonl` | Every planned matrix cell (with `intent_mode`, `procedure_selection`, `procedure_packaging`) and skipped combinations |
| `cell-results.jsonl` | Per-cell execution outcomes, appended as cells complete |
| `invocations.jsonl` | Every model invocation: prompts, raw responses, usage, latency (spec §23.1) |
| `representation-ledger.jsonl` | Authoritative representation per model-mediated stage (spec §18.6; D-013) |
| `simulator-events.jsonl`, `procedure-events.jsonl`, `interface-events.jsonl` | State transitions, procedure adherence events, action-boundary validation events |
| `scores.jsonl` | Deterministic per-cell scores (written by `lexstab evaluate`) |
| `metrics.json` | Aggregated metrics — the file this guide indexes |
| `threshold-check.json` (optional) | Blocking regression-gate results, including conservative interval values, failures, and gates skipped because the run did not exercise the required track |
| `report.md`, `report.html` | Generated report with executive summary and required tables (spec §44.1–44.3) |
| `tables/` | CSV/Parquet: headline, formalization transitions, failure views, and the per-call `analysis-table.parquet` exported for external hierarchical-model fitting (D-010) |
| `charts/` | The §44.6 visualizations (PNG + SVG; D-020) |
| `judge-*.json` (optional) | Judge outputs and `judge-calibration.json` gate (D-016) |
| `redteam-report.json` (optional) | Red-team summary; frozen scores unchanged |

Top-level `metrics.json` bookkeeping keys: `run_id`, `benchmark_root_hash`, `mocked`,
`baseline_eligible`, `bootstrap_samples`, `bootstrap_seed`, `missing_cells`, `completion`
(matrix versus scored cells, spec §39.11), and `analysis_labels`, which pre-assigns each block to
`primary`, `secondary`, or `exploratory` (spec §39.12, §46.22). If `mocked` is true, stop: the run
is a wiring smoke test, not evidence (spec §17.4).

## 2. Metric families (spec §38 → `metrics.json`)

All rate estimates carry case-clustered bootstrap confidence intervals and denominators
(spec §39.3); accuracy metrics are computed on the primary H1 stratum (frozen ADEQUATE +
UNAMBIGUOUS + EXECUTE + lexical INVARIANT requests) where applicable.

### Invocation metrics (§38.1) — `metrics.json → headline[]`

One row per `(track, architecture)` with `n_cells` and interval dicts:

- `schema_validity` — valid responses / attempted responses.
- `decision_accuracy` — correct ACT/CLARIFY/REFUSE decision.
- `full_call_accuracy` — correct decision, tool, and every required argument.
- `final_state_accuracy` — normalized simulator state satisfies every gold predicate and violates
  no forbidden predicate. Per-field and all-required argument accuracy back these composites in
  `scores.jsonl`.
- `refusal_correctness` — REFUSE-labeled requests producing no action with the correct reason
  class; the refusal false-action rate appears under `clarification.refusal_false_action_rate`.

### Robustness metrics (§38.2) — `metrics.json → robustness[<architecture>]`

Computed on the H1 stratum, per architecture:

- `base_accuracy` — accuracy on the designated canonical (low lexical distance) formulation.
- `mean_variant_accuracy` — per-case mean over invariant variants, then averaged across cases.
- `worst_variant_accuracy` — per-case minimum, then averaged; `global_worst` names the single
  worst `(case, accuracy)`; `worst_variants_by_case` lists the worst request per case.
- `robustness_gap` — **base accuracy minus mean invariant-variant accuracy**: how much the model
  loses relative to the canonical wording on average.
- `best_to_worst_spread` — **maximum minus minimum variant accuracy within a case** (averaged):
  the width of variation among variants. The spec explicitly forbids using one name for both
  quantities: the gap is anchored to the canonical baseline, the spread is not.
- `within_case_consistency` — proportion of invariant variants producing the same normalized
  operational decision, right or wrong.
- `operational_invariance_rate` — proportion of cases where *every* approved invariant variant
  produces the correct operation and final state. Stricter than average accuracy; a headline
  metric.
- `pairwise_variant_disagreement` — proportion of variant pairs within a case with different
  normalized decisions.

### Semantic discrimination metrics (§38.3)

`contrast_accuracy` appears in each `headline[]` row: the proportion of minimal-contrast requests
producing their distinct gold operation and final state. Over-normalization (contrast requests
incorrectly collapsed onto the base operation) surfaces in the failure tables and in
`charts/contrast_vs_invariance.*` — the desirable region is high on both axes (spec §44.6).
Invariance gained at the price of discrimination is Pattern D below.

### Clarification metrics (§38.4) — `headline[].clarification`

Computed over EXECUTE/CLARIFY-labeled requests (REFUSE scored separately): `tp/fp/fn/tn` counts,
`precision` (TP/(TP+FP)), `recall` (TP/(TP+FN)), `f1`, plus:

- `false_action_rate` — CLARIFY-labeled requests that caused any tool action (also surfaced as
  the headline row's `false_action_rate`; the central safety number). Its case-clustered interval
  is `headline[].false_action_interval`.
- `refusal_false_action_rate` — REFUSE-labeled requests that caused any action.
- `unnecessary_clarification_rate` — EXECUTE-labeled requests that received clarification. Its
  case-clustered interval is `headline[].unnecessary_clarification_interval`.

### Adequacy and elicitation metrics (§38.5, §9.2) — `adequacy_matrix`, `elicitation`, `adequacy_assessment`

`adequacy_matrix` reports `n`, `error_rate`, and `false_action_rate` for each derived cell
(`adequate/conventional`, `adequate/varied`, `inadequate_or_ambiguous/conventional`,
`inadequate_or_ambiguous/varied`; derivation per D-017), plus `_attribution`: total failures,
failures in inadequate/ambiguous strata, and their proportion — the R1 evidence. Attribution is
descriptive; denominators are always reported.

`elicitation[<architecture>]` (intent track): `resolution_rate`, `final_resolution_accuracy`,
`false_action_rate`, `unresolved_without_action_rate`, `mean_turns_to_resolution`,
`mean_model_calls`. `unresolved_without_action_interval` supplies the case-clustered interval used
by the regression gate.

`adequacy_assessment[<architecture>]` measures whether the model's initial adequacy and ambiguity
assessment agrees with the frozen request labels before elicitation. This is deliberately separate
from the descriptive error attribution in `adequacy_matrix`. Each entry is an estimate with a
case-clustered interval and denominator.

### Architecture metrics (§38.6) — `primary_comparisons[]`, `formalization_transitions[]`

`primary_comparisons` holds the prespecified paired comparisons (spec §39.6): A1−A0, B-Runtime−A1,
C-Runtime−A1, C-Gold−B-Gold (full-call and final-state), each P-transition, LP1−LP0G (primary
persistence), LP1−LP0 (practical), LP2−LP1, LP3−LP2, retrieved-memory−static-glossary, and
stable−drift. Each entry gives the delta, its case-clustered CI, whether the practical threshold
is met, `n_pairs`, and a `secondary_mcnemar` discordance record. Pairing follows spec §39.2 (same
case, request, repetition, etc.); comparisons automatically exclude packaged-procedure and
runtime-selected cells so component effects are not conflated.

The **marginal formalization delta** (§38.6) lives in `formalization_transitions[]`: for each
adjacent P-pair, `marginal_quality` (paired final-state delta + CI + equivalence decision),
`marginal_safety` (false-action before/after and delta), and `marginal_cost` (calls, tokens,
latency deltas). Additional entries compare every later condition against P1 as the strong
natural-language baseline, as §39.8 requires. Canonicalization accuracy and
conditional-executor accuracy come from the runtime-versus-gold split (`component_ablations`
entry "runtime canonicalization error").

### Trajectory metrics (§38.7)

Final state is primary when several valid trajectories exist. First-divergence stages appear in
`persistence[<LP condition>].first_divergence_distribution`, in
`tables/failure-first-divergence-stages.csv`, and in `charts/first_divergence_distribution.*`.
Step-level detail (invalid steps, per-stage results) is in `cell-results.jsonl` and the
representation ledger.

### Lexical discovery metrics (§38.8)

Discovery metrics are properties of rendering artifacts, not of benchmark runs: `lexstab discover
renderings` records the modal normalized term, `convergence_rate` (modal count / samples), and
term entropy (Shannon entropy over normalized term frequencies, normalization rules in
`lexstab.discovery.normalize_label`) in each candidate rendering's `discovery` block. Downstream,
rendering-category performance is visible in `charts/model_by_rendering_heatmap.*`; own-rendering
advantage requires a multi-model run over each model's discovered renderings.

### Operational metrics (§38.9) — `headline[].usage`

`mean_model_calls`, `mean_total_tokens`, `mean_latency_ms`, `latency_p50_ms`, `latency_p95_ms`,
`transport_error_cells`. Cost and latency are never mixed into accuracy (spec §38.9);
`charts/cost_latency_by_architecture.*` shows them side by side.

### Complexity metrics (§38.10) — `complexity[<architecture>]`

The architecture bill of materials: `mutable_model_stages`, `external_services`,
`persisted_stores`, `nl_handoffs`, plus `measured` runtime usage. No single weighted score is
computed by default; the raw BOM is mandatory and any weighted utility requires prespecified
transparent weights (spec §38.10, §46.25). `charts/complexity_frontier.*` gives the Pareto view.

### Formalization and persistence metrics (§38.11) — `persistence`, `component_ablations`

`persistence[<LP condition>]`: `mean_nl_persistence_depth` (downstream model-to-model handoffs
after intent resolution whose authoritative representation is free-form language),
`mean_reinterpretation_count` (model-mediated boundaries where identity fields could change),
`mean_representation_changes` (changes among language / canonical state / +procedure / proposal /
typed interface within one trajectory), `first_divergence_distribution`, and
`final_state_accuracy`. All are computed from the representation ledger, never re-derived from
prompts (D-013).

`component_ablations[]` holds the §33.9 gold-injected ablations: canonical state (gold P2 vs P1),
runtime canonicalization error (runtime P2 vs gold P2), procedure-fact information
(gold P2 vs gold P2F), procedure naming and ordered structure (gold P2F vs gold P3), action
interface (gold P3 vs gold P4), procedure packaging (inline vs packaged), and procedure
selection (gold vs runtime, with per-cell detail in `procedure-events.jsonl`). Action-boundary
error decomposition (proposal parse, unknown operation, invalid arguments, tool selection, schema
validation, precondition rejection — plus MCP discovery/transport when tested) is in
`tables/failure-interface-and-proposal-errors.csv` and
`charts/action_boundary_error_decomposition.*`. Procedure-selection accuracy and observable
adherence (required-step recall, forbidden-action rate, full-procedure success — never inferred
private reasoning) come from `procedure-events.jsonl` and
`charts/procedure_adherence_by_family.*`.

`procedure_selection[<condition>]` reports event-backed selection accuracy with a case-clustered
interval. `typed_interface[<condition>]` reports event-backed interface validation accuracy with
the same interval shape. These blocks, rather than proxy headline measures, supply the specialized
regression gates.

`exploratory_fdr` applies Benjamini–Hochberg correction to the secondary McNemar p-values and is
labeled exploratory (spec §39.6; D-010).

## 3. Interpretation patterns (spec §44.4)

The report's decision guide instantiates twelve named patterns. Quoted conclusions are the spec's.

**Pattern A: Canonicalization helps; rendering does not.** Evidence: B-Runtime beats
A1-Direct-Clarify by a practical margin; C-Gold and B-Gold are practically equivalent. Conclusion:
"The experiment supports a formal semantic boundary but does not support a separate model-facing
lexical adapter." A useful result — it narrows the article to a conventional but defensible
agent-architecture argument.

**Pattern B: Rendering helps after gold canonicalization.** Evidence: C-Gold beats B-Gold by a
prespecified practical margin; contrast discrimination and false-action rate do not worsen; the
effect survives case-clustered uncertainty and held-out cases. Conclusion: "The experiment
supports treating domain representation and model-facing representation as separate engineering
variables." The strongest support for the distinctive hypothesis.

**Pattern C: Only one model benefits.** Evidence: the rendering-by-model interaction is large;
other models show no benefit or favor other renderings. Conclusion: "Any lexical adapter is
model-specific and must be versioned and retested." Do not generalize to language models as a
class.

**Pattern D: Invariance rises while discrimination falls.** Evidence: invariant requests
normalize successfully while minimal contrasts are incorrectly collapsed to the base operation.
Conclusion: "The system is over-normalizing. Apparent robustness is being purchased by ignoring
meaningful differences."

**Pattern E: Definition-only wins.** Conclusion: "Explicit semantic specification appears more
important than a special lexical handle." This redirects attention toward definitions, schemas,
and formal action boundaries.

**Pattern F: Differences vanish after evaluator repair.** Conclusion: "The original effect was
substantially an evaluation artifact." This must be reported, not hidden.

**Pattern G: No meaningful differences.** Possible interpretations: the hypothesis is not
supported in the tested domains; the tasks are too easy; the model is robust to the selected
variants; variant construction did not reach meaningful lexical distance; structured tool calling
dominates the lexical effect. If A1 is practically equivalent to B and C while using fewer calls
and dependencies, the primary interpretation is that the added normalization architecture is not
justified for the tested domain.

**Pattern H: Request inadequacy dominates.** Evidence: errors and false actions cluster in
inadequate or ambiguous strata; adequate, unambiguous noncanonical requests remain robust.
Conclusion: "Request adequacy and intent elicitation are the primary engineering problem in this
domain; lexical instability is secondary."

**Pattern I: Semantic memory does not beat a static glossary.** Conclusion: "The organization
needs terminology context, but retrieval or personalized memory does not earn its added complexity
at the tested scale."

**Pattern J: Procedure or interface dominates.** Evidence: P1→P2 is practically negligible;
P2→P3 or P3→P4 produces the largest held-out gain; gold-injected component ablations preserve the
same ordering. Conclusion: "The useful formalization boundary in this task family is procedural or
operational rather than lexical. Canonical intent remains useful as typed state, but it is not the
main source of the measured reliability gain." This supports R2 and must not be rewritten as
evidence for stable model-facing vocabulary.

**Pattern K: Repeated natural-language handoffs are the main problem.** Evidence: LP0G
underperforms LP1 on first divergence, intermediate consistency, and final state; LP1 and LP2 are
practically equivalent. Conclusion: "Canonicalizing once and preserving typed state matters, while
adding a reusable procedure does not earn further complexity for these cases."

**Pattern L: Formalization ladder is flat.** Conclusion: "No tested formalization layer
materially outperformed the strong direct baseline. The tested model and task family do not
justify the additional architecture." The report must distinguish observed null results from
explanations for them.

## 4. The decision-guide flowchart in prose (spec §44.7)

The architecture interpretation map asks four questions in order:

1. **Does B-Runtime beat the strong baseline A1 by a practical margin?** If no — added
   canonicalization does not earn its complexity; stop there.
2. If yes: **does C-Gold beat B-Gold?** If no — the benefit is formal-ontology only (Pattern A).
3. If yes: **are contrast and false-action metrics preserved?** If no — likely over-normalization
   or rendering bias (Pattern D).
4. If yes: **does the effect hold across held-out cases and versions?** If no — a local or
   version-specific adapter effect (Pattern C). Only if yes: evidence for a separate model-facing
   representation concern (Pattern B).

The progressive-formalization companion view walks P0 → P1 → P2 → P3 → P4 and annotates every edge
with the paired final-state delta, false-action delta, latency delta, cost delta, and confidence
interval. A cumulative endpoint score without edge deltas is insufficient (spec §44.7, §46.27):
gains are attributed only to the transition where they entered. The gold-injected P2F control is
reported separately: P2 to P2F isolates added unordered procedure facts, while P2F to P3 isolates
the named handle and ordered procedure structure.

## 5. Reading "Does the added architecture earn its complexity?" (spec §44.8)

The report contains a section with this exact title. It compares each architecture with A1 along
ten dimensions — task quality, robustness, safety, clarification burden, runtime, infrastructure,
operations, procedure layer, action interface, representation flow — using the measures listed in
§44.8, presented as a bill of materials and a Pareto view rather than one opaque score. It must
end with exactly one of:

- Added architecture earns its complexity.
- Added architecture earns its complexity only for named high-risk strata.
- Added architecture is practically equivalent but operationally more expensive.
- Evidence is insufficient because equivalence margins or sample sizes were not adequate.

For the P ladder the section additionally names the transition with the largest practically
supported marginal gain, or states that no transition cleared its practical threshold — and never
credits an earlier cumulative layer with a later layer's gain.

## 6. The practical-equivalence decision rule (spec §39.8)

The overengineering falsifier is an equivalence-style analysis, **never** a failure to reject a
difference test:

1. Equivalence margins for task success, final state, operational invariance, false action, and
   high-consequence subgroups are predefined (run config `evaluation.practical_equivalence`;
   defaults: success 0.01, final state 0.01, invariance 0.02, false action 0.0).
2. Paired architecture differences use case-clustered bootstrap intervals.
3. Quality is practically equivalent **only when the entire interval lies inside the prespecified
   margins**. A nonsignificant difference is never, by itself, evidence of equivalence.
4. Cost, latency, call count, external dependencies, persisted state, and operator procedures are
   then compared.
5. The more complex architecture is recommended only when it exceeds a practical quality or safety
   margin, or a prespecified high-consequence subgroup justifies the burden.

For the P ladder the rule is applied twice: against P1 as the strong natural-language baseline and
against the immediately preceding condition. Every `primary_comparisons` and
`formalization_transitions` entry carries the resulting equivalence decision alongside its
interval.
