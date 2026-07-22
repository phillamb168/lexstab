# Lexical Harness New-Project Handoff

Status: Current project entry point  
Date: 2026-07-22  
Repository: `/Users/phil/Work/lexical-harness`  
Current phase: Phase One complete; cross-model persistence analysis complete; next research design not yet implemented

## 1. Purpose

This document is the starting point for a new Codex or Claude Code project devoted to the lexical
stability harness. It consolidates the research question, the way the hypothesis changed under
adversarial review, the current evidence, the important artifacts, the remaining uncertainties,
and the correct next reading order.

The repository began as an attempt to test whether language models have stable lexical or
conceptual handles that work more reliably than human-equivalent alternatives. The strongest
Phase One result is narrower and more architectural:

> In a multi-call agent workflow, a model can continue to select the correct operation, tool, and
> entity while repeatedly rewriting an exact operational argument. Keeping that argument in
> authoritative canonical state prevented the rewriting in both tested models.

This result does not prove model-native vocabulary. It does show that ordinary prose is not always
a safe serialization format for values an application requires to remain exact.

## 2. Recommended reading order

A new project should read these documents in order:

1. `docs/NEW_PROJECT_HANDOFF.md`
2. `docs/CROSS_MODEL_PERSISTENCE_FINDINGS.md`
3. `docs/NEXT_RESEARCH_PROGRAM.md`
4. `docs/PHASE_ONE_EVIDENCE_SUMMARY.md`
5. `docs/METHODOLOGY.md`
6. `docs/ANALYSIS_PLAN.md`
7. `docs/ARTICLE_OUTLINE_AND_EVIDENCE_TRACKER.md`
8. `docs/STATUS_AND_ROADMAP.md`
9. `docs/MODEL_TIER_COMPARISON_PROTOCOL.md`
10. `docs/RUNBOOK.md`

The first three files are the new-project handoff package. The remaining documents preserve the
detailed historical methodology, Opus baseline, article structure, and operational commands.

## 3. Executive state of the project

### Completed

- The harness implements versioned datasets, frozen manifests, model-role isolation, deterministic
  scoring, canonicalization, grounding, clarification, procedures, typed tools, persistence
  architectures, tracing, reporting, and cross-model comparison.
- Historical benchmark versions `v0.1.0`, `v0.2.0`, `v0.2.1`, and `v0.3.0` remain preserved.
- The broad corrected Opus Phase One matrix completed through a provenance-linked whole-track
  repair and has a frozen interpretation record.
- The focused `v0.3.0` request-more-information replication completed for Opus 4.8 and Sonnet 5.
- Both focused runs are healthy, baseline-eligible, and evaluated with the same deterministic
  evaluator source hash.
- A formal provider-free cross-model comparison is complete.
- Failure and trajectory analysis is complete and recorded in
  `docs/CROSS_MODEL_PERSISTENCE_FINDINGS.md`.

### Not completed

- No protected-literal sidecar condition exists yet.
- The exact-argument persistence result covers only one operation family.
- The cross-model runs were not executed from the same code revision, although their frozen
  execution inputs and execution path match.
- No real human-participant prompt-training study has been designed or run.
- No input-modality or speech-to-text experiment has been run.
- No experiment has established a model-facing lexical-rendering advantage after canonical meaning
  is fixed.
- No broad Sonnet matrix or five-repetition broad model run is warranted yet.

## 4. Intellectual history

### 4.1 Initial practitioner observation

The project began from a recurring practitioner observation:

> Models sometimes appear to use one lexical or conceptual formulation more consistently than a
> human-equivalent alternative. Replacing that formulation with organizational terminology may
> change downstream behavior or introduce another opportunity for reinterpretation.

Examples included grammatical labels, code identifiers, business entities, and operation names.
The original architectural intuition was to preserve model-consistent terminology inside the
agent loop and translate into organizational terminology only at the boundary.

This was always an observation, not a mechanistic claim. It did not establish that models literally
possess preferred words, internal dictionaries, private ontologies, or discrete conceptual
handles.

### 4.2 Concept identity versus lexical identity

A central distinction emerged:

> Concept identity and lexical identity are not the same thing, but the transformation between
> them is not neutral.

A human can hold the correct concept and still produce a neighboring phrase. The motivating example
was accidentally saying `resource augmented generation` while intending `retrieval-augmented
generation`. The phrase remained plausible because resources are conceptually adjacent to the
retrieved material used by RAG.

This example is evidence about human language production, not LLM internals. Its value is
illustrative: a plausible substitution can preserve enough local coherence to avoid detection while
changing the literal object that crosses a system boundary.

### 4.3 Plausible substitution

The project adopted `plausible substitution` as a behavioral description:

> A transformation replaces an intended lexical object with a neighboring, fluent, locally
> coherent alternative that may survive validation because it still sounds reasonable.

Plausible substitutions are often more dangerous than nonsense. Nonsense tends to fail loudly.
Fluent substitutions can pass through people, speech recognition, model calls, and agent handoffs
without triggering clarification.

The mountweazel analogy was discussed but remains optional. A mountweazel is intentionally false,
whereas the project studies accidental transformations. The useful shared feature is that
plausibility helps the false object survive inside a system containing real ones.

### 4.4 Input modality

Typing and speaking were identified as different prompt-production processes:

```text
typed path:
thought -> written composition -> model input

spoken path:
thought -> spoken production -> acoustic signal -> STT interpretation
       -> transcript normalization -> model input
```

Speech can provide more context while producing more lexical variation, provisional statements,
deictic references, self-correction, and transcription opportunities. The transcript is a lossy
intermediate representation rather than a neutral copy of intention.

This led to a broader interface claim:

> Voice does not remove the interface between thought and machine action. It replaces an explicit
> interface with an inferential one.

Input modality remains outside the tested Phase One result and should stay a separate later
experiment or article unless evidence connects it directly.

### 4.5 Three vocabularies, not one

The discussion separated three representational concerns:

1. **User vocabulary**: local, conversational, flexible, contextual, and sometimes ambiguous.
2. **Organizational domain ontology**: engineered entities, operations, arguments, relationships,
   state, and valid transitions.
3. **Model-facing representation**: the words, definitions, schemas, and procedures presented to a
   particular model implementation.

The organizational ontology and model-facing language need not be identical. A business may call
an operation `Promote Service Matter`, store it as `OP_07`, and present it to a model as `escalate
incident`. If a tested model-facing representation matters, it is an adapter layer, not the domain
model itself.

The application-level architecture became:

```text
user language
  -> semantic normalization
  -> canonical entity, operation, arguments, provenance, and uncertainty
  -> optional model-facing rendering
  -> agent reasoning
  -> typed action boundary
  -> deterministic domain state
```

This produced the reusable phrase:

> Flexible language. Stable ontology. Formal action.

### 4.6 World model versus linguistic interface

The chess analogy sharpened the role division. A model can interpret "move my knight over there"
and propose a move. Another component should maintain the board, determine which piece exists,
validate whether the move is legal, and update state.

The corresponding agent principle is:

> Use the LLM as a linguistic interface to the world model, not as the authoritative world model.

This moved the project beyond prompt style. The canonical layer is not merely a synonym dictionary.
It represents what exists, how objects relate, which state is current, what arguments are required,
and which transitions are valid.

### 4.7 Adversarial narrowing

Steelman and adversarial review separated the claims into testable layers:

1. **Controlled lexical non-equivalence**: application-equivalent wording may produce different
   operational behavior.
2. **Boundary canonicalization**: mapping user language into canonical entities and operations may
   improve reliability and clarification behavior.
3. **Post-canonical rendering**: model-facing wording may still matter after application meaning is
   fixed.
4. **Persistence**: repeated free-form handoffs may change exact arguments even after intent is
   resolved.
5. **Human training versus middleware**: structured prompting education may substitute for, or add
   to, boundary normalization.

The load-bearing question for the original lexical idea became:

> Once the application-level entity and operation are fixed, does the representation presented to
> the reasoning model still produce repeatable, operationally significant differences?

### 4.8 Phase One changed the center of gravity

Phase One did not find a useful direct lexical-variant effect for Opus in the adequate,
unambiguous boundary cases. Direct Opus completed all 20 primary variants, including all eight
high-distance variants.

It also did not find a model-discovered rendering advantage after canonicalization. Bare canonical
state, canonical rendering, and model-discovered rendering were all at ceiling in the small tested
set.

The strongest result came from a different layer: exact argument persistence. Repeated prose
handoffs often changed a public message even though the model continued to identify the correct
operation, tool, and incident. Canonical authoritative state prevented the change.

The evidence therefore supports a representation-boundary article more strongly than a
model-native-vocabulary article.

## 5. Current strongest defensible claim

The current claim should be stated narrowly:

> In the tested request-more-information workflow, repeated model-authored prose handoffs frequently
> rewrote a public message whose application contract required exact preservation. Both Opus 4.8
> and Sonnet 5 preserved the correct operation, tool, and entity, but neither reliably preserved the
> literal message through prose. Keeping canonical state authoritative preserved the message in
> every tested cell for both models.

This is a behavioral and architectural claim. It does not depend on a theory of model internals.

## 6. Current terminology

### Canonical ontology

The registered domain representation of entity types, operations, arguments, relationships,
states, preconditions, and valid transitions.

### Canonical intent

A particular resolved request expressed through canonical entity, entity ID, operation ID,
arguments, provenance, uncertainty, and clarification status.

### Semantic normalization layer

The reader-friendly name for the boundary component that maps flexible language into canonical
intent and asks for clarification when more than one mapping remains plausible.

### Canonical intent middleware

The deployable runtime architecture containing normalization, grounding, provenance, validation,
and formal action preparation.

### Model-facing rendering

A textual presentation of already-resolved canonical intent to an acting or reasoning model.

### Lexical adapter

An optional component selecting or generating tested model-facing terminology. Current evidence
does not show that this component improves performance.

### Argument preservation mode

The application contract governing how an argument may change:

- `VERBATIM`: exact protected content must remain unchanged.
- `CANONICAL`: only registered deterministic normalization is permitted.
- `SEMANTIC`: meaning-equivalent transformations may be accepted under an explicit scoring rule.

### Plausible substitution

A fluent, neighboring lexical transformation that remains coherent enough to avoid obvious error
detection.

### Formal action

An action expressed through a registered operation, typed arguments, validated preconditions, and a
deterministic state transition rather than unconstrained prose.

## 7. Evidence map

### Frozen benchmarks

- `dataset/manifests/benchmark-v0.1.0.json`
- `dataset/manifests/benchmark-v0.2.0.json`
- `dataset/manifests/benchmark-v0.2.1.json`
- `dataset/manifests/benchmark-v0.3.0.json`

Never mutate these manifests or their frozen artifacts in place. New conditions or corrected
artifacts require a new benchmark version.

### Broad Opus Phase One

```text
runs/run-v0.2.1-phase-one-composite-20260721
```

This is a provenance-linked composition of a broad base run and a complete-track elicitation
repair. Read `docs/PHASE_ONE_EVIDENCE_SUMMARY.md` before interpreting it.

### Focused Opus persistence run

```text
runs/run-v0.3.0-rmi-replication-1x-20260721
```

### Focused Sonnet persistence run

```text
runs/run-v0.3.0-sonnet5-rmi-replication-1x-20260722
```

### Formal model comparison

```text
runs/model-comparison-opus48-sonnet5-v0.3.0.json
```

### Additional analysis artifacts

```text
comparison-results/compact-model-level-v0.3.json
comparison-results/case-level-cross-model-v0.3.json
comparison-results/opus-generated-failure-by-architecture.txt
comparison-results/opus-generated-failure-first-divergence-stages.txt
comparison-results/sonnet-generated-failure-by-architecture.txt
comparison-results/sonnet-generated-failure-first-divergence-stages.txt
```

Each focused run also contains:

```text
verbatim-failures.tsv
failed-trajectories.json
scores.jsonl
cell-results.jsonl
metrics.json
report.md
report.html
```

The file `comparison-results/case-level-cross-model-v0.3.json` currently contains tab-separated
text rather than JSON. Treat it as TSV until it is renamed or regenerated.

## 8. What the evidence supports

Within the tested scope:

- Exact operational arguments can drift across repeated model-authored prose handoffs.
- Correct action selection does not guarantee correct literal preservation.
- A canonical authoritative representation can prevent this drift.
- A compact verbal reminder can behave very differently across model versions.
- Formal boundary resolution eliminated false action on the tested clarification targets.
- Adequacy and ambiguity are genuine rivals to lexical explanations and must remain first-class
  labels.
- A strong frontier model was robust to the current adequate direct user-language variants.
- Model-discovered terminology showed no advantage in the current ceiling-bound post-canonical set.
- Architecture can dominate model tier for a protected-argument outcome.

## 9. What remains unsupported

Do not claim from the current evidence:

- that a model has a private ontology;
- that a model internally translates organizational words into preferred words;
- that stable lexical handles exist as discrete internal objects;
- that semantic attractors have been established in latent geometry;
- that model-discovered terminology improves agent reliability;
- that ordinary user synonyms generally cause failures;
- that Opus or Sonnet requires a special working vocabulary;
- that training users has a known return on investment;
- that middleware generally replaces user training;
- that the persistence result generalizes beyond request-more-information messages;
- that spoken input and typed input have been experimentally compared;
- that every meaning-preserving rewrite is harmful.

The public-message field was deliberately marked `VERBATIM`. If an application permits semantic
rewriting, it needs a different preservation mode and evaluator.

## 10. Bracketed ideas

The following ideas remain separate unless a future experiment makes them necessary:

- `Intelligence as a Stack of Preferences`
- the full voice-interface thesis
- tacit ontology and institutional semantics
- mountweazels as a primary conceptual frame
- claims about model personality or intelligence as preference

See `docs/FUTURE_ARTICLE_IDEAS.md` and the bracketed sections of
`docs/ARTICLE_OUTLINE_AND_EVIDENCE_TRACKER.md`.

## 11. Repository state at handoff

At the time this handoff was written, the working tree included untracked analysis material:

```text
comparison-results/
docs/FUTURE_ARTICLE_IDEAS.md
```

The operator should review and commit those artifacts together with this handoff package if they
belong in the permanent research record. Do not assume they have already been pushed.

## 12. Suggested initial prompt for the new project

```text
Continue work on /Users/phil/Work/lexical-harness.

Read these files completely, in order:
1. docs/NEW_PROJECT_HANDOFF.md
2. docs/CROSS_MODEL_PERSISTENCE_FINDINGS.md
3. docs/NEXT_RESEARCH_PROGRAM.md
4. docs/PHASE_ONE_EVIDENCE_SUMMARY.md
5. docs/METHODOLOGY.md
6. docs/ARTICLE_OUTLINE_AND_EVIDENCE_TRACKER.md
7. docs/STATUS_AND_ROADMAP.md

Inspect the current git status and preserve all frozen v0.1.0, v0.2.0, v0.2.1, and v0.3.0
artifacts. Do not run paid providers, mutate frozen manifests, begin a human-participant study, or
implement a new benchmark condition until I explicitly choose the next step. Start by summarizing
the current evidence, the strongest supported claim, the main non-claims, and the recommended next
experiment.
```

## 13. Next document

Read `docs/CROSS_MODEL_PERSISTENCE_FINDINGS.md` for the full Opus versus Sonnet results and the
failure-trajectory analysis. Then read `docs/NEXT_RESEARCH_PROGRAM.md` for the implementation and
research sequence.
