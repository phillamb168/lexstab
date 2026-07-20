# Frozen analysis plan (spec §39.12)

This file is the pre-registered analysis plan. Its SHA-256 hash is recorded in every
run manifest; executing the held-out `test` split refuses to start when this file is
absent (spec §49.10 "the analysis-plan hash is recorded before held-out evaluation").
Change this file only before opening held-out results, and record the change in the
benchmark changelog.

## Primary hypotheses

H1 (controlled lexical non-equivalence), R1 (request inadequacy dominates),
H2 (boundary canonicalization), H3 (post-canonical rendering effect — load-bearing),
H8 (intent elicitation), H10 (overengineering null), H11 (progressive formalization),
H12 (natural-language persistence), R2 (procedure or interface dominates).

## Primary comparison families (spec §39.6)

1. A0_DIRECT vs A1_DIRECT_CLARIFY (full-call accuracy)
2. A1_DIRECT_CLARIFY vs B_RUNTIME (full-call accuracy)
3. B_GOLD vs C_GOLD (full-call and final-state accuracy, paired)
4. Model-discovered rendering vs definition-only (full-call accuracy)
5. Stable canonical propagation vs forced lexical drift (final state)
6. Adequate vs inadequate error attribution by lexical stratum
7. M0 vs M1 vs M2 memory conditions
8. P0→P1, P1→P2, P2→P3, P3→P4 as one prespecified family (final state, paired)
9. LP0G vs LP1 (gold-start persistence, primary); LP0 vs LP1 (practical, secondary)
10. Inline procedure vs packaged skill (paired)
11. Local typed tool vs MCP capability (when MCP is enabled)

The direct P0 to P4 ladder remains the prespecified progressive-formalization family. The
gold-injected P2 to P2F and P2F to P3 component controls separately estimate the effect of adding
unordered procedure facts and the incremental effect of procedure naming plus ordered structure.

## Metric definitions

As implemented in `lexstab.metrics.aggregate` and documented in
`docs/RESULTS_GUIDE.md`. Primary quality metric: final-state accuracy; primary safety
metric: false-action rate; primary robustness metric: operational invariance rate.

## Exclusion rules

- Transport failures stay in reliability denominators; excluded from behavioral
  accuracy only in a separately labeled analysis (spec §39.11).
- Invalid schema outputs count as incorrect.
- No cell is dropped silently; missing cells are enumerated in metrics.json.
- Primary H1 uses only frozen ADEQUATE / UNAMBIGUOUS / EXECUTE / lexical INVARIANT
  requests.

## Minimum practical effects and equivalence margins

- full-call / final-state success margin: 0.01
- operational invariance margin: 0.02
- false-action margin: 0.0
- progressive-formalization minimum practical final-state gain per transition: 0.02

## Statistical models

- Primary: case-clustered bootstrap (10,000 resamples, seed = run matrix seed).
- Secondary: exact McNemar on paired discordance.
- Exploratory families: Benjamini–Hochberg FDR at 0.05.
- Publication-grade hierarchical model (fit externally from analysis-table.parquet):
  `correct ~ architecture * model + rendering_category * model + procedure_condition
  + action_interface_condition + persistence_condition + variation_axis
  + (1 | operation_family/case_id)`

## Correction method

Benjamini–Hochberg within each exploratory family; primary families are reported with
intervals and prespecified margins, not p-value thresholds.

## Subgroup analyses

By operation family, variation axis, lexical distance band, and adequacy-matrix cell.
All subgroup analyses are labeled secondary unless listed above.
