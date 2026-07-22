# Next Research Program

Status: Proposed research and implementation sequence  
Date: 2026-07-22  
Starting point: Phase One and the Opus versus Sonnet v0.3.0 comparison are complete

## 1. Decision summary

Do not run another broad paid benchmark yet.

The current evidence answers one narrow question well enough to justify the next controlled
experiment. The most valuable immediate step is to determine whether the benefit attributed to
canonical state comes from the full canonical representation or from the simpler fact that an
exact literal remains available as an authoritative field.

The recommended sequence is:

1. Finish repository and analysis housekeeping without provider calls.
2. Add a call-balanced protected-literal sidecar condition.
3. Validate it provider-free and run one focused repetition on both models from one code revision.
4. Expand exact-argument persistence to at least two additional operation families.
5. Freeze the representation result and article interpretation.
6. Design the human-training versus middleware study as a separate runtime-language protocol.
7. Add economical models only after the architecture and analysis plan are frozen.
8. Treat speech and transcription as a later adjacent experiment.

## 2. Immediate provider-free closeout

### 2.1 Preserve the current record

Review and commit:

- `comparison-results/`
- `docs/FUTURE_ARTICLE_IDEAS.md`
- `docs/NEW_PROJECT_HANDOFF.md`
- `docs/CROSS_MODEL_PERSISTENCE_FINDINGS.md`
- `docs/NEXT_RESEARCH_PROGRAM.md`
- any currently uncommitted cross-model comparison implementation and tests

Do not edit or regenerate historical run outputs merely to remove warnings. Historical artifacts
must continue to describe the environment in which they were created.

### 2.2 Correct analysis packaging

Provider-free housekeeping should address two issues:

1. Rename `comparison-results/case-level-cross-model-v0.3.json` to a `.tsv` filename or regenerate
   it as actual JSON.
2. Rename the generic first-divergence summary so it does not imply final failures only, or add a
   separate final-failure table keyed by `first_verbatim_argument_divergence`.

Recommended generated tables:

```text
all-first-divergences-by-stage.csv
final-verbatim-failures-by-first-stage.csv
recovered-verbatim-divergences.csv
planner-exact-final-lost.csv
```

### 2.3 Freeze an analysis note

The cross-model analytical addendum is `docs/CROSS_MODEL_PERSISTENCE_FINDINGS.md`. If later
analysis changes an interpretation, add a dated change log rather than silently rewriting the
historical result.

## 3. Priority experiment: protected-literal sidecar

### 3.1 Why this is the next experiment

The v0.3.0 reminder condition said which field must remain exact but did not carry the original
literal independently. Once a free-form handoff paraphrased the message, later stages had no
authoritative copy from which to recover it.

In 15 of 96 language-persistence cells, the planner's structured result still contained the exact
message and the final output did not. This suggests a smaller architectural intervention may be
sufficient:

> Keep protected literals in a typed sidecar while allowing the rest of the workflow to use prose.

This condition distinguishes the value of full canonical intent from the value of protecting only
opaque fields.

### 3.2 Proposed condition

Working architecture ID:

```text
LP0BL_GOLD_START_LANGUAGE_PROTECTED_LITERALS
```

Working representation:

```json
{
  "handoff_text": "Natural-language description of the task and current reasoning state.",
  "protected_literals": {
    "message": "Please attach the application.log and launcher.log files from the affected device."
  }
}
```

Rules:

- `handoff_text` remains model-authored prose.
- `protected_literals` is created from gold canonical intent for this experiment.
- Models may read the sidecar but may not rewrite it.
- The harness, not a model, carries the sidecar unchanged between calls.
- The final executor must source `VERBATIM` arguments from the sidecar.
- A model may propose an operation or nonprotected arguments, but it cannot replace the protected
  value with text extracted from its own handoff.
- The sidecar is included in every stage input in the same stable position.
- Call count remains four in every compared condition.
- The sidecar contains only fields whose registered preservation mode is `VERBATIM`.

### 3.3 Comparison matrix

Use four primary conditions:

| Condition | Prose handoffs | Names preservation rule | Carries exact literal | Full canonical state |
|---|---:|---:|---:|---:|
| LP0B | yes | general instruction | no | no |
| LP0BV | yes | yes | no | no |
| LP0BL | yes | yes | yes | no |
| LP1 | no authoritative prose | encoded | yes | yes |

Primary paired comparisons:

1. `LP0BL - LP0B`: protected-literal middleware versus ordinary prose.
2. `LP0BL - LP0BV`: carrying the value versus merely naming the preservation requirement.
3. `LP1 - LP0BL`: full canonical state versus the minimal protected-literal intervention.
4. `LP1 - LP0B`: retain the established benchmark comparison.

### 3.4 Hypotheses

#### PL-H1

> Carrying exact protected literals in an authoritative sidecar improves exact argument
> preservation over free-form prose with or without a field-name reminder.

#### PL-H2

> If LP0BL reaches practical equivalence with LP1, the v0.3.0 benefit can be explained by
> authoritative literal retention without requiring the full canonical representation for this
> operation family.

#### PL-H3

> If LP1 materially outperforms LP0BL, other elements of canonical state contribute beyond literal
> retention.

### 3.5 Falsifying or confidence-reducing outcomes

- LP0BL performs no better than LP0BV.
- The sidecar introduces schema or plumbing failures that erase any benefit.
- The executor ignores the sidecar and continues sourcing values from prose.
- LP0BL changes call count, prompt information, or model roles relative to the other conditions.
- Results depend on one sentence form or one case.

### 3.6 Implementation requirements

Create a new benchmark version. Do not add LP0BL to frozen `v0.3.0`.

Recommended version:

```text
benchmark-v0.4.0.json
```

Implementation work:

1. Add a typed `protected-literals.v1` schema.
2. Add `LP0BL_GOLD_START_LANGUAGE_PROTECTED_LITERALS` to the architecture registry.
3. Add prompt versions that explain how models may reference but not rewrite the sidecar.
4. Carry the sidecar deterministically between stages.
5. Make the final proposal builder source `VERBATIM` arguments from the sidecar.
6. Record sidecar hashes and field provenance in the representation ledger.
7. Add measured invocation counts to complexity accounting.
8. Add exact matrix compatibility fields to cross-run comparison.
9. Add a deterministic integrity check that protected values do not change between calls.
10. Add a report row and primary paired comparisons.
11. Add a failure table showing any attempt to override a protected literal.
12. Add tests before freezing the benchmark.

### 3.7 Required automated tests

- Only arguments registered as `VERBATIM` enter the sidecar.
- Sidecar values are byte-for-byte or token-for-token unchanged across every stage.
- Model-authored output cannot overwrite a protected literal.
- Nonprotected arguments still come from the registered planner or canonical state.
- LP0BL and the other primary conditions each make four execution calls.
- LP0BL begins with the same gold intent and known state as LP0B, LP0BV, and LP1.
- Procedural and LangGraph runners produce equivalent LP0BL outputs.
- Representation-ledger hashes expose any sidecar mutation.
- Historical v0.3.0 manifests and runs remain readable.
- Reports keep runtime and gold cohorts separated.
- Cross-model compatibility blocks a sidecar prompt, schema, or parameter mismatch.

### 3.8 Provider-free validation sequence

After implementation:

```bash
uv run pytest -q

uv run lexstab benchmark verify \
  --manifest dataset/manifests/benchmark-v0.4.0.json

uv run lexstab doctor \
  --models config/models.local.yaml \
  --run config/run.v0.4.0-protected-literal-health.yaml

uv run lexstab run \
  --config config/run.v0.4.0-protected-literal-1x.yaml \
  --dry-run
```

The dry run must show exact call balance and no skipped primary combinations. Do not proceed to a
provider run until the matrix and first-call inputs have been inspected.

### 3.9 Paid validation sequence

Run a small targeted health matrix for each execution model. Continue only with:

- zero provider errors;
- zero length terminations;
- zero aborted cells;
- 100 percent schema validity;
- exact expected invocation counts.

Then run one full focused repetition for Opus and Sonnet from the same committed code revision.
Evaluate both using the same evaluator source hash and run the formal comparison.

Do not run five repetitions until the one-repetition result is interpretable.

### 3.10 Decision rule

After one repetition:

- If LP0BL is at ceiling and practically equivalent to LP1, describe the minimum intervention as
  protected-field persistence, not full canonical ontology.
- If LP1 materially exceeds LP0BL, inspect which nonliteral canonical fields account for the
  remaining difference.
- If both LP0BL and LP1 are at ceiling, expand operation families before adding repetitions.
- If LP0BL fails for implementation reasons, fix the contract before interpreting model behavior.

## 4. Expand to additional operation families

### 4.1 Why case count is not enough

The current persistence result has eight independent cases but only one operation family. More
repetitions reduce stochastic uncertainty inside those cases but do not establish that the effect
generalizes to other kinds of protected values.

The existing interpretation gate requires at least three operation families for broader
generalization. The next benchmark should add at least two.

### 4.2 Suitable protected arguments

Choose fields whose application contract genuinely requires exact preservation. Good candidates
include:

- exact public comments approved by a human;
- filenames or file paths;
- opaque external identifiers;
- customer-approved notification text;
- exact quoted error messages;
- commands or configuration fragments that are passed as data;
- change-control references;
- regulatory or legal language that must be reproduced exactly.

Avoid creating a verbatim requirement merely to force failures. If semantic rewriting is acceptable
in the real application, mark the field `SEMANTIC` and score it accordingly.

### 4.3 Candidate synthetic operation families

#### Family A: Send approved notification

```text
SEND_APPROVED_NOTIFICATION(
  recipient_id: CANONICAL,
  subject: VERBATIM,
  body: VERBATIM
)
```

Potential drift:

- greeting insertion;
- tone improvement;
- shortening;
- explanation added;
- policy wording softened.

#### Family B: Attach or retrieve named artifacts

```text
REQUEST_DIAGNOSTIC_ARTIFACTS(
  incident_id: CANONICAL,
  filenames: VERBATIM
)
```

Potential drift:

- punctuation removed from filenames;
- file extensions normalized;
- singular or plural changed;
- paths shortened;
- a familiar neighboring filename substituted.

#### Family C: Record approved change note

```text
POST_APPROVED_CHANGE_NOTE(
  change_id: CANONICAL,
  note: VERBATIM
)
```

Potential drift:

- tense and actor changed;
- ticket number substituted for artifact identity;
- implementation detail added;
- exact approval caveat removed.

Select two families that are operationally distinct from RMI and can be simulated deterministically.

### 4.4 Minimum dataset

Recommended minimum:

- three operation families total, including RMI;
- at least six independent cases per family;
- one designated literal plus two meaningfully different literal forms per family where the literal
  itself remains gold, not lexical variants of one intent;
- three stochastic executions per case for the first screen;
- four call-balanced persistence conditions: LP0B, LP0BV, LP0BL, LP1.

With 18 independent cases, three repeated executions, and four conditions:

```text
18 cases x 3 repeated rows x 4 conditions = 216 cells
216 cells x 4 calls = 864 execution calls per model
```

Dry-run the exact matrix and calculate current provider cost before authorizing calls.

### 4.5 Human review

A human reviewer must approve:

- whether each field genuinely requires exact preservation;
- whether the expected operation and state transition are correct;
- whether each message or literal is realistic;
- whether a supposed failure could actually be accepted by the application;
- whether cases accidentally differ in adequacy, scope, or difficulty.

## 5. Add a secondary semantic-severity diagnostic

The deterministic `VERBATIM` metric remains primary. Do not rescore fluent rewrites as correct.

Add a separate diagnostic taxonomy to understand operational severity:

1. **Formatting-only change**: whitespace or punctuation with no identifier effect.
2. **Politeness or discourse framing**: greeting, thanks, or explanatory sentence.
3. **Meaning-preserving paraphrase**: same requested information under the reviewer rubric.
4. **Specificity change**: strengthens or weakens what must be supplied.
5. **Actor or commitment change**: changes who may act, who is responsible, or how strongly.
6. **Referential change**: alters an identifier, filename, version, or named artifact.
7. **Conditionality or scope change**: adds `if`, changes conjunction, drops a required branch.
8. **Workflow leakage**: adds internal state, policy, or process to public text.
9. **Material operational change**: a reasonable user or tool could take a different action.

Use two blinded human reviewers on a calibration sample. An optional LLM judge may propose labels,
but it cannot replace deterministic gold or human adjudication.

Report exact-preservation accuracy and severity distribution separately.

## 6. Same-revision model comparison

The current Opus and Sonnet comparison passed the formal compatibility gate but contains a
code-revision warning. Before quoting cross-model numbers as publication-grade evidence:

1. Commit the final v0.4.0 architecture and analysis plan.
2. Run both models from that same commit.
3. Hold prompts, schemas, procedures, interfaces, run clock, seed, model parameters, and all
   nonexecution roles fixed.
4. Evaluate both runs with the same evaluator source hash.
5. Run `compare-runs` and archive the compatibility record.

Rerunning only Opus does not eliminate the warning. Both models must use the same final revision.

## 7. Economical-model research

### 7.1 Question

The commercially useful question is not whether a cheaper model has lower raw accuracy:

> Can an economical model with canonical or protected-field middleware match a frontier model's
> successful-task rate at lower cost per successful task?

### 7.2 Sequence

1. Freeze the architecture and dataset.
2. Run Opus and Sonnet from one revision.
3. Select one additional economical model with reliable structured output and tool support.
4. Change only `execution_primary` for the first comparison.
5. Keep the canonicalizer and all other roles fixed.
6. Compare raw condition accuracy and architecture benefit within each model.
7. Calculate cost per successful task, not token price alone.
8. Only later test a fully economical stack where canonicalizer and other roles also change.

### 7.3 Metrics

- exact protected-argument success;
- operation and entity accuracy;
- schema validity;
- provider errors and length terminations;
- model calls;
- prompt, completion, and total tokens;
- latency;
- provider cost;
- cost per correct final state;
- cost per 1,000 tasks under an assumed error-cost model.

### 7.4 Model-tier non-claims

Do not infer from one family that:

- a cheaper model generally needs more middleware;
- a frontier model can safely use prose;
- a reminder discovered for one model transfers to another;
- a lower raw score implies a larger middleware return.

Middleware return is the within-model structured-minus-direct difference. Model-tier comparison is
the difference between those differences.

## 8. Human training versus middleware

### 8.1 Why this is a separate experiment

The current v0.3.0 persistence matrix removes user wording before the first model call. It cannot
measure formal versus informal prompting or the return on training people.

Human-language research must use runtime boundary inputs and preserve each participant's actual
words.

### 8.2 Factorial design

Use a 2 by 2 design:

| User condition | Direct model | Canonical intent middleware |
|---|---:|---:|
| Natural or untrained language | A | B |
| Trained structured language | C | D |

Primary estimands:

- training benefit without middleware: `C - A`;
- middleware benefit for natural users: `B - A`;
- training benefit after middleware: `D - B`;
- interaction: whether middleware substitutes for training or adds to it.

### 8.3 Participant design

Do not label existing people trained or untrained and treat that as causal. Prior role, education,
technical experience, writing ability, and AI use would be confounded.

Prefer a randomized intervention:

1. Recruit users with varied roles and prior AI experience.
2. Collect baseline requests before training.
3. Randomize participants to structured-prompt training or a control activity.
4. Assign matched but different post-training tasks.
5. Repeat later to measure retention and adherence.
6. Preserve raw prompts, composition time, edits, and abandoned attempts.

### 8.4 Separate two training mechanisms

Training may:

1. change the representation of already-present information;
2. cause users to provide information that would otherwise be missing.

Both have business value, but only the first isolates language representation. Score adequacy and
wording separately.

### 8.5 Outcomes

- operational success;
- false-action rate;
- clarification precision and recall;
- turns to resolution;
- exact argument preservation;
- prompt composition time;
- prompt length and structure;
- training adherence;
- delayed retention;
- calls, tokens, latency, and cost;
- participant workload and preference.

### 8.6 ROI model

Estimate cost per 1,000 tasks:

```text
model and middleware runtime cost
+ amortized middleware engineering cost
+ amortized training cost
+ user composition time
+ expected cost of operational errors
```

Report:

```text
Training ROI = avoided error value - training cost - added user effort

Middleware ROI = avoided error value - runtime cost - engineering cost
```

Training adherence decay must be included. Middleware runs on every request; human behavior may not
persist.

### 8.7 Collaboration opportunity

The harness now provides useful experimental infrastructure but lacks a real participant population.
A credible article ending and call to action can invite:

- enterprise workflow vendors;
- service-desk organizations;
- research groups studying human-AI interaction;
- employers with novice, occasional, and expert AI users;
- organizations able to provide de-identified task scenarios and error-cost estimates.

The collaboration offer should be a mutual research deliverable, not a request for private prompts.
It can support networking, consulting, or employment discussions while remaining methodologically
legitimate.

## 9. Human-authored language corpus

Human-written variants remain valuable, but their role must be explicit.

### For runtime lexical testing

Author variants along controlled axes:

- canonical and explicit;
- natural and concise;
- colloquial and indirect;
- organization-specific jargon;
- high lexical distance;
- provisional or conversational;
- structurally trained prompt;
- under-specified clarification target;
- minimal semantic contrast.

Every invariant variant requires human adequacy and equivalence review before freezing.

### For gold-start persistence

Do not count several user-language variants as independent lexical evidence when they are replaced by
the same gold input before the first model call. They remain repeated executions only.

## 10. Input modality and speech-to-text

Keep modality adjacent to, but separate from, the core persistence experiment.

Proposed artifact chain:

```text
intended concept
  -> typed expression
  -> spoken expression
  -> human transcript
  -> STT transcript
  -> canonical resolution
  -> action
```

Compare human transcripts with STT transcripts to distinguish human lexical production from speech
recognition errors. Preserve audio, transcription confidence, timestamps, punctuation choices, and
domain-term alternatives.

Measure:

- first point where lexical identity changes;
- canonical resolution accuracy;
- clarification behavior;
- domain-term mutation;
- commitment and uncertainty preservation;
- whether plausible substitutions pass silently.

Do not infer a shared mechanism between humans, STT models, and LLMs from similar-looking errors.

## 11. Statistical plan for the next benchmark

### Independent unit

The canonical case remains the independent unit. Request rows and repeated calls are nested
observations.

### Primary analysis

- paired condition differences;
- cluster bootstrap by canonical case;
- fixed seed and recorded bootstrap sample count;
- point estimate with 95 percent interval;
- exact case-level sign test as secondary evidence.

### Interpretation gates

- at least six independent cases for a within-family causal interpretation;
- at least three operation families for broader generalization;
- required schema-validity gate met;
- no mixed runtime and gold cohort;
- exact matched pairs for both compared conditions;
- zero unexplained provider or truncation failures.

### Repetitions

Add independent cases and families before increasing repeated executions. Repetition estimates
stochastic stability but does not create new semantic coverage.

### Multiple comparisons

Declare LP0BL comparisons primary before opening held-out results. Treat model-by-condition and
severity-taxonomy analyses as secondary unless preregistered.

## 12. Reproducibility and versioning

- Never edit frozen artifacts in place.
- Use a new manifest for every new architecture, prompt contract, case, or corrected label.
- Store prompt, procedure, interface, schema, code, lockfile, and evaluator hashes.
- Record exact provider and model IDs.
- Keep authoring, review, freeze, execution, evaluation, and reporting separate.
- Preserve raw provider responses and normalized outputs.
- Retain unhealthy runs for diagnosis.
- Never splice individual successful cells into a benchmark result.
- Whole-track repair requires exact provenance and a compatible replacement artifact.
- Cross-model publication comparisons should use the same code revision.

## 13. Article integration

The current article should lead with the narrow result rather than the original mechanistic
hypothesis.

### Strong article spine

1. A plausible substitution looks harmless.
2. Models receive linguistic artifacts, not intentions.
3. Applications sometimes need exact values, not equivalent prose.
4. Repeated agent handoffs invite helpful rewriting.
5. The harness shows correct intent and incorrect literal can coexist.
6. Canonical authoritative state prevents the tested drift.
7. Reminder behavior differs by model and is not a stable substitute for architecture.
8. The open question is where language should end inside an agent system.
9. The next research question is whether organizations should train users or absorb variation at the
   boundary.

### Safe conclusion

> Linguistic flexibility can remain at the interface. Values that determine formal action need an
> explicit point at which interpretation ends.

### Research hook

> The harness can now measure the architecture. What it lacks is real language from people with
> different jobs, prompting habits, and training. That is the next collaboration.

## 14. Work explicitly deferred

Do not begin these until the preceding gates are met:

- a broad economical-model matrix;
- a five-repetition broad Opus run;
- a model-native vocabulary claim;
- mechanistic interpretability work;
- a human study without consent, privacy, and analysis protocols;
- production integration with proprietary records;
- a speech study without audio and transcript provenance;
- an ROI claim without error-cost and user-time data.

## 15. Definition of Done for the next milestone

The next milestone is complete when:

- the current v0.3.0 cross-model artifacts and handoff documents are committed;
- the misleading analysis filenames or labels are corrected without mutating historical runs;
- a frozen protected-literal sidecar hypothesis and analysis plan exist;
- LP0BL is implemented with a typed, immutable sidecar;
- all automated tests pass;
- historical v0.1.0 through v0.3.0 artifacts remain verifiable;
- a new benchmark version is frozen and verified;
- dry-run output proves four-call balance and exact input parity;
- one healthy Opus run and one healthy Sonnet run execute from the same commit;
- both runs have zero provider errors, length terminations, and aborted cells;
- both are evaluated by the same evaluator source hash;
- the comparison reports LP0BL versus LP0B, LP0BV, and LP1;
- trajectory analysis identifies first literal divergence, recovery, and sidecar integrity;
- interpretation remains limited to tested families;
- the project records whether protected-field persistence is sufficient or full canonical state adds
  further value;
- no five-repetition or broad paid run begins before this result is reviewed.

## 16. Immediate choice for the operator

The next operator decision should be one of these:

1. **Research closeout only**: commit and archive the current evidence, then draft the article.
2. **Minimal architecture isolation**: implement the protected-literal sidecar first. This is the
   recommended option.
3. **Generalization first**: add two operation families before testing the sidecar. This costs more
   and leaves the current causal ambiguity unresolved.
4. **Human collaboration first**: pause synthetic benchmark work and recruit a participant partner.

Recommended choice: option 2, followed by operation-family expansion. It asks the cleanest next
question and may reveal that the minimum useful middleware is smaller than a full canonical
ontology for exact payloads.
