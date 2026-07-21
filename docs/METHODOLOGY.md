# Methodology

Hypotheses, experimental tracks, statistical methodology, the confound register, and prior-art
positioning, condensed from spec §5, §9, §39, §46, and §47. Every hypothesis maps to a named
experiment, a prespecified primary metric, and a falsifying or confidence-reducing outcome.

## 1. Hypotheses (spec §5)

| ID | Claim (summary) | Primary metrics / comparisons |
|---|---|---|
| H1 | Meaning-preserving lexical variants produce repeatably different operational outcomes from a pinned model, even when every request is independently labeled adequate and unambiguous. | Full-call accuracy by lexical condition; operational invariance rate by case; worst-variant accuracy. |
| R1 (rival) | Apparent natural-language failures are primarily caused by missing, contradictory, or context-dependent information, not lexical variation; controlling adequacy/ambiguity leaves a small lexical effect. | Error attribution by adequacy/ambiguity stratum; false-action rate on inadequate requests; accuracy on adequate unambiguous noncanonical requests; inadequacy-associated vs lexical-variation-associated error. Treated as a genuine competitor to H1. |
| H2 | Mapping flexible language into canonical entities/operations/arguments before action improves end-to-end reliability over sending raw language to the acting model. | A1-Direct-Clarify vs B-Runtime (boundary track): final-state accuracy, false-action rate, clarification precision/recall. |
| H3 | After application meaning is fixed, a stable model-facing lexical rendering still changes execution relative to canonical IDs and canonical labels alone. **The load-bearing hinge.** | B-Gold vs C-Gold, F-Model-Discovered vs C-Gold, and F-Model-Discovered vs B-Gold. All-operation and genuinely distinct-rendering subsets are reported separately. |
| H4 | A small early lexical difference can amplify into a larger final-state difference in a multi-stage agent workflow. | First-divergence stage; conditional propagation rate; final-state delta vs single-stage delta. |
| H5 | Terms a pinned model converges on during blind operation naming may outperform equally valid canonical, human, or organization-selected alternatives downstream. | Fifty fresh samples for each of eight operations; convergence, entropy, definition-only rate, and post-canonical paired execution. Identical instantiated text is no lexical contrast. |
| H6 | Any lexical advantage is shared, family-specific, or version-specific; rendering rank order reveals which. | Cross-model rank correlation of renderings; model-by-rendering interaction. |
| H7 | Typed input, spoken input, human transcripts, and ASR transcripts produce different lexical artifacts from one intended concept; canonicalization recovers some but not all. | Stage of first lexical/canonical change; canonical resolution accuracy by modality artifact; clarification on plausible substitutions. Not evidence of shared mechanism. |
| H8 | For inadequate/ambiguous requests, an explicit clarification policy reduces false action; a separate adequacy gate must beat the integrated A1 baseline to justify itself. | Adequacy classification accuracy; clarification P/R; false-action rate; turns to resolved intent; unresolved rate. Comparisons: A0 vs A1; A1 vs B-External-Gate; gate vs gate-gold. |
| H9 | Glossaries, retrieved memory, canonical resolution, or personalized mappings may help boundary interpretation — or gain nothing over a strong direct baseline given the same information. | Canonical resolution and final-state accuracy; retrieval quality; false-action rate; incremental latency/cost/calls/dependencies. |
| H10 | Overengineering null: a strong direct baseline (A1) with full context performs within prespecified practical-equivalence margins of more complex architectures. | Decision rule: quality/safety differences inside equivalence margins; complex conditions materially costlier; no high-consequence subgroup overrides. |
| H11 | Reliability improves at different formalization transitions (clarification, canonical intent, procedure, typed interface); the largest practically meaningful marginal gain locates the useful boundary. | Paired final-state, false-action/policy, adherence, and parse/validation deltas per transition, plus marginal burden. A statement about where gains occur, not a universal boundary. |
| H12 | After intent is resolved, repeated free-form prose handoffs create more reinterpretation and divergence than typed canonical state; a frozen procedure may reduce variance further. | LP0B vs LP1 is the primary four-call final-state comparison. LP0B vs LP0BV tests a visible verbatim reminder, and LP0BV vs LP1 tests whether structure adds value beyond that reminder. LP0G vs LP1 remains the secondary extra-call comparison. |
| R2 (rival) | Most practical gains come from clarification, procedures, or typed interfaces rather than lexical normalization or canonical intent mapping. | Supported when direct→canonical is negligible under context parity while procedure/interface transitions produce larger paired improvements. Gains are attributed per layer; a cumulative ladder never credits an earlier layer. |

## 2. Experimental tracks (spec §9.1)

1. **Boundary track** — user request → optional canonicalizer → MUT → tool simulator → final
   state. Does boundary normalization improve the deployed system as a whole?
2. **Intent-elicitation track** — request + shared context → adequacy/ambiguity decision →
   targeted clarification → execute or clarify again. Reported separately from the H1 lexical
   score.
3. **Post-canonical track** — the gold canonical case is injected directly, bypassing
   interpretation; only the model-facing representation varies. Mandatory for H3.
4. **Semantic-memory track** — no memory / static glossary / retrieved memory / canonical
   resolver / personalized confirmed mappings, separating terminology information from its
   delivery mechanism (Experiment 9).
5. **Progressive-formalization and persistence track** — formalization layers added cumulatively
   (P0-P4) while natural-language persistence varies independently (LP0, LP0B, LP0BV, LP0G,
   LP1-LP3); the
   cumulative ladder and component ablations are reported separately (Experiment 10).

## 3. Request adequacy matrix (spec §9.2)

Every request occupies one cell of a first-class 2×2 matrix:

| Request state | Canonical/conventional wording | Noncanonical/varied wording |
|---|---|---|
| Adequate and unambiguous | Control stratum | **Primary H1 lexical stratum** |
| Inadequate or ambiguous | Clarification control | Clarification + lexical-stress stratum |

The top-right cell is the primary test of input-side lexical robustness; the bottom row tests
adequacy recognition and elicitation and must never count against lexical invariance. Cells are
derived from independent frozen labels rather than stored (D-017). Context adequacy is part of the
gold label: "Escalate this" is a clean test only when the frozen context artifact fixes whether
`this` is recoverable.

## 4. Role isolation (spec §9.4)

Authoring models propose candidates only; the human researcher approves gold; the frozen benchmark
feeds the execution model under test; a deterministic evaluator scores; a blinded judge sees only
unresolved subjective cases; a human reviewer resolves low-confidence judgments. Authoring models
never execute the benchmark, the MUT has no gold-label authority, and the judge cannot mutate
artifacts. Role isolation is enforced in configuration and validated before execution: a run fails
on a prohibited role combination unless an explicit `allow_role_overlap` research override is set
and recorded in the run manifest.

### Corrected canonical boundary contract

Runtime canonicalization returns a strict control-plane envelope with `mapping_outcome` set to
`MAPPED` or `NEEDS_CLARIFICATION`. A mapped envelope contains a nested `canonical_intent`; a
clarification envelope contains a question and no canonical intent. The typed parser validates the
whole response before any action stage. Only the nested intent crosses into planner, procedure,
rendering, or executor prompts. This prevents an outcome label such as `RESOLVED` from becoming
part of the model-facing task representation.

After parsing, deterministic grounding checks enforce three source classes: request text, frozen
shared context including visible context state, and explicitly registered state-derivation rules.
Hidden application state may validate an anchored entity, but a unique hidden record cannot
originate an entity reference. The only initial state-derived argument is
`REFUND_DUPLICATE_CHARGE.amount_usd`, and only when the order is anchored and the duplicate amount
is confirmed. Grounding provenance is stored per canonical field.

The legacy v1 envelope remains readable for historical verification. A standalone diagnostic
compares `status: RESOLVED`, `mapping_outcome: MAPPED`, and no outcome field while holding the flat
canonical payload fixed. That diagnostic is never headline-eligible.

### Cohort isolation and interpretation gates

Every aggregate cohort is keyed by `track`, `architecture`, `intent_mode`,
`procedure_selection`, and `procedure_packaging`. Runtime and gold injection therefore cannot
share a headline row. Paired comparisons select both exact cohorts. Gold-injected cells are scored
against case gold while the original request labels remain audit metadata.

Clarification and false-action metrics use direct or runtime user-request conditions only. The
evaluator reports raw failures from every cohort, but causal interpretation is withheld when a
paired cohort has no matched observations or falls below the configured schema-validity gate.

Independent-case and family gates apply after schema validation. The default v0.2.1 thresholds are
six independent canonical cases for causal interpretation and three operation families for broader
generalization. Additional request variants and repetitions do not satisfy either threshold.

### Argument preservation and divergence

Each operation argument has a preservation mode. `VERBATIM` requires exact protected content,
`CANONICAL` permits only the registered deterministic normalizer, and `SEMANTIC` is reserved for
tasks whose gold contract permits semantic equivalence. The primary v0.2.1 protected field is the
public RMI `message`.

The evaluator reports `first_operation_divergence`, `first_argument_divergence`, and
`first_verbatim_argument_divergence`. For prose handoffs, a case-sensitive word-and-punctuation
token sequence locates whether the protected literal survives within the larger handoff. Final
arguments use exact value comparison for `VERBATIM`. These diagnostics make no model call and do
not infer private reasoning.

## 5. Statistical methodology (spec §39)

- **Unit of analysis** (§39.1): the canonical case is the independent sampling unit; requests
  from one case are repeated measures. Calls nest repetition → request → rendering → procedure →
  interface → architecture → case → operation family.
- **Paired design** (§39.2): comparisons pair on case, request, model, repetition index, tool
  order, procedure version/selection, interface contract, prompt version, provider parameters,
  and run clock — making B-Gold vs C-Gold especially clean.
- **Primary intervals** (§39.3): a cluster bootstrap resampling canonical cases with replacement
  (retaining all variants/renderings/architectures/repetitions within a sampled case); default
  10,000 samples, 95% intervals, fixed recorded seed. Point estimate plus interval, never a bare
  p-value.
- **Secondary tests** (§39.4): McNemar's exact test on paired binary outcomes, never replacing
  the clustered primary analysis.
- **Hierarchical modeling** (§39.5; D-010): the mixed-effects specification (architecture,
  rendering, procedure, interface, persistence, axis, model fixed effects; interactions with
  model; random intercepts for case within operation family) is frozen in the analysis plan, and
  the harness exports the per-call `tables/analysis-table.parquet` for external fitting; the
  model is not fit inside the harness.
- **Multiple comparisons** (§39.6): a bounded declared set of primary comparison families;
  Benjamini–Hochberg FDR applied to exploratory families (`metrics.json → exploratory_fdr`).
- **Effect size and equivalence** (§39.7–39.8): absolute percentage-point differences, relative
  error reduction, invariance and false-action deltas; practical equivalence is declared only
  when the whole case-clustered interval lies inside prespecified margins — never inferred from
  non-significance. The P ladder is tested both against P1 and against each preceding condition.
- **Power, seeds, missing data** (§39.9–39.11): pilot before scaling; case count before request
  count; temperature zero is not assumed deterministic; fresh contexts per repetition; failed
  cells are never dropped silently and completion rates are reported per condition.
- **Analysis-plan freeze** (§39.12): hypotheses, primary comparisons, metric definitions,
  exclusion rules, minimum practical effects, models, correction method, and subgroup analyses
  are frozen before held-out test results are opened; the plan hash is stored in the run
  manifest.

## 6. Confound register (spec §46)

All 32 spec-mandated risks, with condensed mitigations. Section numbers give the full text.

| § | Risk | Core mitigation |
|---|---|---|
| 46.1 | Request inadequacy mistaken for lexical sensitivity | Independent adequacy/ambiguity labels before execution; frozen context; H1 restricted to adequate+unambiguous; intent results reported separately; all four matrix cells compared |
| 46.2 | Supposed synonyms are not equivalent | Synthetic domain defines meaning; component-level equivalence review; minimal contrasts; reject variants changing state/scope/commitment |
| 46.3 | Evaluator artifacts | Score final state; domain normalizers; preserve raw and normalized scores; human review of normalization disagreements |
| 46.4 | Judge sensitivity | Deterministic evaluation first; human calibration; judge-prompt paraphrases; blinding and randomized order; UNCERTAIN route |
| 46.5 | Ceiling effects | Related tools, policy reasoning, state-dependent preconditions, harder held-out cases; never manufacture ambiguity in invariant cases |
| 46.6 | Floor effects | Tune difficulty on the development split; keep definitions available; opaque IDs are a control, not the only baseline |
| 46.7 | Tool-schema wording overlap | Freeze tool schemas; balanced description experiment; opaque-ID and definition-only controls; record request/rendering/tool token overlap |
| 46.8 | Prompt length and position | Fixed prompt structure; length-matched control text; record token counts; balance placement in a dedicated control |
| 46.9 | Tokenization | Record token counts; length-matched synonyms; treat tokenization as a rival explanation, not excluded nuisance |
| 46.10 | Training-corpus frequency | Conventionality/frequency ratings where available; compare model-discovered, common, rare, organization terms; report frequency as rival explanation |
| 46.11 | Model-generated benchmark bias | Substantial human-authored coverage; multiple generator families; track and report by source; MUT excluded from primary generation |
| 46.12 | Data leakage | Keep held-out artifacts private; synthetic IDs and states; discover renderings on development definitions only; record release dates |
| 46.13 | Version drift | Pin exact IDs; record fingerprints and dates; preserve raw outputs; rerun a sentinel subset over time |
| 46.14 | Nonindependent repetitions | Disable caches; randomize order; record concurrency/timestamps; separate runs over time; analyze at case level |
| 46.15 | Tool ordering | Fixed order for the primary comparison; secondary balanced-order condition; never change order for one architecture only |
| 46.16 | Context contamination | Fresh context per independent cell; no conversation history unless multi-turn is the variable |
| 46.17 | Over-normalization | Contrast and clarification sets; preserve original language as metadata; report discrimination alongside invariance |
| 46.18 | Human reviewer bias | Fixed component-level rubrics; reviewers blinded to model results; independent review; report disagreement and edits |
| 46.19 | Model role contamination | Enforced role separation; cross-family critics; deterministic state as oracle; permitted overlap only as explicit ablation |
| 46.20 | State simulator bugs | Unit tests per operation; property tests of preconditions/transitions; hand-calculated fixtures; freeze-time state validation |
| 46.21 | Multiple valid trajectories | Prefer final state; required/forbidden tool scoring; set or partial-order constraints; calibrated trajectory judge only as last resort |
| 46.22 | Researcher degrees of freedom | Frozen primary hypotheses/comparisons; held-out test split; labeled exploratory analyses; publish null results and all planned metrics |
| 46.23 | Unequal context across architectures | Frozen shared context; A1 receives everything that is not the named variable; capability-addition and information-parity memory comparisons; per-cell context and token records |
| 46.24 | Semantic-memory leakage and staleness | Scope by org/team/user/date; confirmed status and provenance; stale/superseded/wrong-scope negative tests; mappings never supply missing instance arguments; measure false action |
| 46.25 | Complexity measurement subjectivity | Publish the raw bill of materials; report dimensions separately; freeze any weights before held-out results; Pareto before weighted utility |
| 46.26 | Weak direct baseline | Current high-capability model; same pinned MUT across A1/B/C; equivalent context for A1; clarification policy validated on development cases; smoke runs flagged as not baseline-eligible |
| 46.27 | Cumulative-ladder attribution error | Report every adjacent transition; gold-injected component ablations; paired intervals for marginal deltas; attribute gains only to the changed layer |
| 46.28 | Procedure information leakage | Validate required inputs; information-parity control without procedural sequencing; diff procedure content against domain context; reject procedures supplying case-specific facts |
| 46.29 | Procedure packaging confound | Inline vs packaged-skill comparison; record fully assembled messages/tools; hash byte-equivalent content; report packaging separately from content |
| 46.30 | Generic proposal vs typed-tool inequivalence | Both contracts generated from one registry; matched arguments/descriptions; measured lexical overlap and prompt length; identical procedure/state/facts; separate error categories |
| 46.31 | MCP implementation confound | Local typed-tool baseline before MCP; equivalent capability definitions; separate selection vs discovery/transport/protocol errors; never generalize one MCP server |
| 46.32 | Natural-language handoff contamination | Fixed handoff rubric excluding hidden chain-of-thought; representation hashes and fact coverage; same facts to canonical conditions; omissions/additions scored as intermediate-state errors; standard retention/redaction |

## 7. Prior-art positioning (spec §47)

**The broad claim that prompt wording can affect model behavior is already well studied and is not
presented as novel by this project** (spec §47).

- Multi-prompt evaluation:
  [State of What Art? A Call for Multi-Prompt LLM Evaluation](https://aclanthology.org/2024.tacl-1.52/)
  (instruction paraphrases at scale; motivates multi-prompt and worst-variant metrics);
  [SCORE: Systematic COnsistency and Robustness Evaluation for Large Language Models](https://aclanthology.org/2025.naacl-industry.39/)
  (robustness under nonadversarial setup changes; motivates repeated multi-condition runs);
  [What Did I Do Wrong? Quantifying LLMs' Sensitivity and Consistency to Prompt Engineering](https://aclanthology.org/2025.naacl-long.73/)
  (sensitivity/consistency metrics close to this harness's accuracy and invariance split).
- Agentic function calling:
  [On the Robustness of Agentic Function Calling](https://aclanthology.org/2025.trustnlp-main.20/)
  (naturalistic query variation on a BFCL-derived benchmark — Experiment 1 overlaps this work and
  must move beyond it);
  [RoTBench](https://aclanthology.org/2024.emnlp-main.19/) (stage-specific tool robustness);
  the [Berkeley Function Calling Leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html)
  (typed function-call evaluation discipline; this harness prefers executable final state).
- Evaluation artifacts:
  [Flaw or Artifact? Rethinking Prompt Sensitivity in Evaluating LLMs](https://aclanthology.org/2025.emnlp-main.1006/)
  — rigid answer matching can exaggerate prompt sensitivity; raw and normalized/final-state
  scores stay separate here.
- Code robustness:
  [ReCode](https://aclanthology.org/2023.acl-long.773/) and
  [Are Large Language Models Robust in Understanding Code Against Semantics-Preserving Mutations?](https://arxiv.org/abs/2505.10443)
  — identifier perturbation is not a new idea; Experiment 5 focuses on equally descriptive
  alternatives and model-original vs organization-specific naming.
- LLM judges:
  [All Prompts Are Created Equal? Evaluating Robustness of LLM Judges Against Non-Adversarial Prompt Variations](https://aclanthology.org/2026.findings-acl.1929/)
  — judge robustness is separate from judge accuracy; judges are calibrated across paraphrases
  and never the primary oracle for a paraphrase-sensitivity experiment.
- Frameworks: LangGraph's [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api),
  LangSmith [evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts) and
  [trajectory evals](https://docs.langchain.com/langsmith/trajectory-evals), and Ragas
  [metrics](https://docs.ragas.io/en/v0.2.2/concepts/metrics/available_metrics/) are established
  infrastructure; skills, typed function calling, and MCP-style interfaces are established
  agent-engineering patterns, not contributions of this project.

**The distinctive question is post-canonical** (spec §47.7): once flexible user language has been
resolved into a fixed canonical application representation, does the lexical rendering
subsequently presented to the reasoning or execution model still change operational reliability?
The load-bearing lexical comparison is **B-Gold versus C-Gold**; if there is no material
difference, the stable-ontology argument may survive but the separate model-facing vocabulary
claim gains no support. The load-bearing architectural comparison is A1 versus B and C under
practical-equivalence and complexity analysis. Reports use bracketed language ("behavioral
sensitivity to lexical rendering", "candidate stable handle") and avoid mechanistic claims ("the
model thinks in this word") per spec §47.8.
