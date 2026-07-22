# Phase One Evidence Summary

Status: Frozen interpretation record for the Opus baseline  
Date: 2026-07-21  
Execution model: `claude-opus-4-8`  
Primary deterministic benchmark: `dataset/manifests/benchmark-v0.2.1.json`  
Focused persistence benchmark: `dataset/manifests/benchmark-v0.3.0.json`

## 1. Decision

Phase One is complete for its intended purpose. It established a reproducible persistence result,
completed one broad frontier-model pass, exposed useful null findings and confounds, and left the
original model-native-vocabulary hypothesis unsupported rather than forcing the data to fit it.

No five-repetition broad Opus run is required. The one-repetition broad run is sufficient to choose
the next targeted experiments. Repeating all 814 cells would spend heavily on many ceiling-bound or
structurally uninformative conditions.

The first recommended Phase Two provider experiment is the frozen v0.3.0 persistence matrix with a
less expensive execution model and every other experimental input held fixed. A human-language
training study remains a separate later experiment because the v0.3.0 gold-start design deliberately
removes user wording before the first model call.

## 2. Evidence artifacts

### 2.1 Focused independent-case replication

```text
runs/run-v0.3.0-rmi-replication-1x-20260721
```

This is a healthy, single-run, 72-cell real-provider artifact over eight independent
request-more-information cases.

### 2.2 Broad Phase One artifact

```text
runs/run-v0.2.1-phase-one-composite-20260721
```

The broad artifact is a provider-free, provenance-linked composition of:

```text
base:        runs/run-v0.2.1-frozen-1x-20260721
replacement: runs/run-v0.2.1-elicitation-repair-20260721
```

The base run completed all 814 scheduled cells but was globally unhealthy because three
`intent_elicitation` invocations reached their response limits. Its other 806 cells and their
invocations were retained. The repair reran the complete eight-cell `intent_elicitation` track with
larger response budgets and completed healthy.

The composite replaces that complete track, not selected failed rows. It contains:

- 814 matrix cells and 814 scored results;
- 806 result cells from the base run;
- eight result cells from the healthy repair run;
- 1,731 retained base invocations and 35 replacement invocations;
- zero provider errors, zero length terminations, zero aborted cells, and zero missing scores.

The benchmark hash, code revision, lockfile, prompts, procedures, interfaces, run clock, random seed,
provider identities, and model identities match between source runs. The only recorded parameter
differences are response-budget increases:

- adequacy assessor: 768 to 4,096 maximum tokens;
- boundary canonicalizer: 4,096 to 8,192 maximum tokens.

`composition-provenance.json` records source hashes, all replacement cell IDs, row counts, and the
parameter differences. The generated report visibly labels itself a provenance-linked composite.
Neither source run was edited or rescored in place.

This artifact is valid for track-specific and cohort-specific interpretation. It must never be
described as one uniform provider execution with one uniform response-budget configuration.

## 3. Questions Phase One could answer

Phase One tested whether:

1. adequate, unambiguous user-language variants changed operational behavior;
2. a formal boundary changed clarification and false-action behavior;
3. model-facing renderings changed behavior after canonical meaning was fixed;
4. repeated prose handoffs changed state or arguments after intent resolution;
5. procedures and typed interfaces added measurable benefit in this small domain;
6. inadequacy and ambiguity explained more failures than controlled lexical variation.

It did not test model internals, general human prompting skill, speech input, model-version
stability, or organizational return on investment.

## 4. Finding 1: direct Opus was robust to the adequate lexical variants

The boundary track presented distinct source wording to the first model call. For the primary H1
stratum, both direct Opus conditions completed all 20 adequate, unambiguous, executable requests
correctly across five canonical cases and three operation families.

For `A0_DIRECT` and `A1_DIRECT_CLARIFY`:

- designated canonical wording: 5 of 5 correct;
- other low-distance wording: 2 of 2 correct;
- medium-distance wording: 5 of 5 correct;
- high-distance wording: 8 of 8 correct;
- operational invariance: 5 of 5 cases;
- semantic contrast accuracy: 100 percent in the boundary headline cohort.

This is evidence against a useful Phase One H1 effect for this model and these tasks. It does not
show that wording never matters. It shows that the current adequate requests were too easy for Opus
to reveal such an effect, even when their lexical distance was high.

It also means the aggregate adequacy table must not be read as a causal user-language result. Across
all architectures, `adequate/varied` rows had a higher descriptive error rate than
`adequate/conventional` rows, but the direct architecture had no such failures. The aggregate mixes
different architectures, intent modes, cases, and repeated transformations.

## 5. Finding 2: the formal boundary changed unsafe action behavior

Among the 12 boundary requests whose gold behavior was clarification:

| Condition | False actions | Correct clarifications | Schema-invalid non-actions |
| --- | ---: | ---: | ---: |
| A0 direct | 8/12 | 0/12 | 4/12 |
| A1 direct with clarification policy | 5/12 | 7/12 | 0/12 |
| B runtime canonicalization | 0/12 | 12/12 | 0/12 |
| C runtime canonicalization plus rendering | 0/12 | 12/12 | 0/12 |

The canonicalized conditions also unnecessarily clarified one adequate request, producing
clarification precision of 0.923 and recall of 1.0. This is a real tradeoff, not a free gain.

The A0 output contract was schema-valid in 33 of 39 cells, or 84.6 percent, below the prespecified
99 percent interpretation gate. Its six invalid outputs were safe non-actions expressed outside the
required boundary schema, including four clarification targets and two refusal targets. Those raw
failures remain visible, but comparisons touching A0 cannot support causal attribution.

The bounded result is therefore architectural and behavioral: in this corpus, external grounding
and canonical resolution eliminated false action on clarification targets. It is not evidence that
a lexical adapter caused the improvement.

## 6. Finding 3: one canonicalizer defect looked superficially lexical

`B_RUNTIME` failed one of 20 adequate executable requests:

```text
Transfer INC-1047 to the Billing team; keep the tier where it is.
```

The canonicalizer selected the correct `REASSIGN_INCIDENT` operation and entity but emitted the
argument value `Billing team` instead of the registered enum `BILLING`. The bare canonical executor
correctly refused to violate its typed tool contract. `C_RUNTIME` received a canonical rendering and
normalized the same value to `BILLING`, so it acted successfully.

This is not clean evidence that stable terminology helps the model. It is primarily a mismatch
between the canonical-resolution contract and the typed operation schema. The rendering acted as a
second normalization opportunity and repaired it. Future work should either enforce enum-valid
canonical arguments at the boundary or explicitly define where that normalization is supposed to
occur.

The rendering itself also exposed a template-quality defect, producing `Billing team team`. Opus
still selected `BILLING`, but the malformed text reinforces why this cell should remain a diagnostic
rather than a headline lexical result.

## 7. Finding 4: the post-canonical lexical comparison was a null result

The model-discovered rendering was genuinely different from the canonical rendering in all five
tested cells, covering three operations: escalation, reassignment, and duplicate-charge refund.

All of the following were correct in every applicable cell:

- bare canonical structure, 5 of 5;
- canonical rendering, 5 of 5;
- model-discovered rendering, 5 of 5;
- definition-only control, 3 of 3 in one operation family;
- organization-term control, 3 of 3 in one operation family.

Model-discovered minus canonical rendering was exactly zero over the five matched cases. The same
was true for model-discovered minus bare canonical structure. These conditions were at ceiling and
below the six-independent-case interpretation gate.

The proper conclusion is not lexical equivalence. It is that this test supplied no evidence of a
model-discovered rendering advantage. A stronger lexical-adapter test needs more cases and a task
where post-canonical wording can plausibly affect nontrivial reasoning rather than a straightforward
tool mapping.

## 8. Finding 5: free-form persistence produced exploratory cross-operation failures

In the broad runtime persistence condition, `LP0_LANGUAGE_THROUGHOUT` achieved correct final state
on 13 of 20 adequate executable primary-H1 rows, or 65 percent. The matched runtime
`LP1_CANONICAL_ONCE` condition achieved 17 of 20, or 85 percent. The paired estimated difference was
0.20 with a case-clustered interval from -0.133 to 0.550. Two cases favored canonical-once, one
favored language-throughout, and two tied. With five independent cases, this is exploratory and
inconclusive.

Several prose-path failures are still diagnostically valuable. The multi-stage chain invented
requirements not present in the ontology or operation contract, including:

- an escalation reason that the operation did not require;
- a sequential-tier rule that the domain did not define;
- a need for the user to supply a canonical team identifier for the ordinary phrase `Billing`.

These invented uncertainties propagated through later handoffs and produced clarification instead
of action. The result is consistent with the hypothesis that repeated natural-language
reinterpretation creates opportunities for drift, but the broad comparison is confounded by the
runtime canonicalizer's enum defect and has only five independent cases.

The call-balanced gold-start comparison was 20 of 20 for both `LP0B` and `LP1` in these five
non-RMI cases. That null matters: when no argument had a meaningful verbatim preservation contract,
four prose calls did not underperform four canonical-state calls. The seven-call gold-start prose
condition scored 16 of 20 versus 20 of 20 for canonical-once, a descriptive 0.20 difference, but
call count and representation both changed.

## 9. Finding 6: the focused RMI replication produced the strongest signal

The v0.3.0 replication tested eight independent RMI cases. Every case contained a public message
whose preservation contract was `VERBATIM`. The primary conditions used four Opus calls each and
began from the same gold canonical intent.

Exact message preservation and final-state success were:

- free-form persistence: 6 of 24, or 25 percent;
- free-form persistence with a visible verbatim reminder: 5 of 24, or 20.8 percent;
- canonicalize-once: 24 of 24, or 100 percent.

Canonicalize-once minus free-form persistence had an estimated delta of 0.75 with a case-clustered
95 percent interval from 0.50 to 0.917. Seven independent cases favored canonicalize-once, none
favored prose, and one tied. The exact case-level sign-test result was `p = 0.015625`.

Canonicalize-once minus the visible-reminder condition had a delta of 0.792, interval 0.542 to 1.0,
the same seven-to-zero case direction, and `p = 0.015625`. The reminder did not improve over
unreminded prose: delta -0.042, interval -0.208 to 0.208, case-level `p = 0.625`.

This supports one bounded claim:

> For these eight RMI cases and this pinned Opus version, repeatedly authorizing free-form language
> handoffs caused frequent drift in an exact public message. Preserving canonical authoritative
> state prevented that drift. A short visible reminder did not show improvement over unreminded
> prose.

It does not establish a model-native vocabulary, a general paraphrase penalty, or a user-language
effect. The gold-start design intentionally made the three human-authored source variants identical
before the first model call.

## 10. Finding 7: procedures and typed interfaces worked, but did not show a marginal gain

The procedure router selected the expected procedure in all 37 observed events across six cases.
The typed interface validated correctly in all 39 gold cells and all 39 runtime cells across seven
cases. The corrected P3 and LP3 contracts were operational.

Gold-injected procedure facts, named structure, packaging, and the typed interface were all at
ceiling in the five primary cases. Their paired deltas were zero and below the independent-case
gate. This shows that the implementation works, not that procedures and typed tools are generally
unnecessary.

## 11. Effective-input audit

Claims about wording require proof that different wording actually reached the tested model.

- Boundary: 156 source requests produced 156 distinct first model inputs. This track genuinely
  stimulated user-language variation.
- Post-canonical: each condition intentionally supplied one system-constructed representation per
  case. It did not test source-request wording.
- Progressive formalization: 45 cohort-case groups preserved distinct source inputs; 66 groups
  collapsed several source requests into one identical gold-start input. Collapsed groups are
  stochastic repetitions, not lexical-distance evidence.
- Intent elicitation: eight cells used their own runtime conversational inputs, but only two
  independent elicitation cases were present.

Any article claim about formal versus informal human wording must use a runtime input design. It
cannot be inferred from gold-injected rows that removed those words.

## 12. What Phase One supports

Supported within stated scope:

- exact operational arguments can drift across repeated free-form handoffs;
- preserving canonical authoritative state can prevent that drift for the tested RMI protocol;
- a short visible verbatim reminder was not sufficient in that protocol;
- deterministic grounding and canonical resolution can prevent action on inadequate or ambiguous
  requests;
- a strong frontier model can be completely robust to the current adequate lexical variants;
- post-canonical model-discovered terminology showed no advantage in the current ceiling-bound set.

Not supported:

- that Opus needs a model-native vocabulary;
- that the model has a private ontology or stable internal lexical handles;
- that user training has a known return on investment;
- that middleware generally beats a strong direct model on adequate requests;
- that the results generalize to cheaper models, other model versions, or other domains;
- that a model-facing lexical adapter has earned its engineering cost.

## 13. Phase Two sequence

The recommended sequence is:

1. Commit the composition feature, reports, and this evidence record.
2. Pin one economical execution model.
3. Dry-run the frozen v0.3.0 persistence configuration with only `execution_primary` changed.
4. Run one repetition and compare the same eight independent cases with the same deterministic
   evaluator.
5. Decide from that focused result whether a broader economical-model run is worth its cost.
6. Design the human-training versus middleware study separately with runtime user wording and real
   participants or partner-provided de-identified prompts.

Do not edit v0.2.1 or v0.3.0 to make the economical model look better. Model-specific output-budget
changes, if required for provider health, must be recorded as a new run configuration and reviewed
before execution.

## 14. Article consequence

The article should lead with the investigation rather than a claim that the initial intuition was
confirmed. The interesting result is sharper:

> A frontier model handled the controlled user-language variants without error, and a
> model-discovered lexicon did not beat canonical terminology. The real failure appeared when an
> already resolved intent was repeatedly converted back into prose. In the focused test, the model
> preserved the operation while frequently rewriting the exact public argument. Flexible language
> was not the problem at the edge. Uncontrolled language persistence was the problem inside the
> loop.

That finding supports `Flexible language. Stable ontology. Formal action.` while keeping the
model-native-vocabulary claim open for future research.
