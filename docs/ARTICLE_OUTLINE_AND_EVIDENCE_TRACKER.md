# Model Vocabulary and Stability: Article Outline and Evidence Tracker

Status: Active editorial plan, not a draft  
Last updated: 2026-07-21  
Working article: Model Vocabulary and Stability  
Research repository: `/Users/phil/Work/lexical-harness`  
Harness roadmap: `docs/STATUS_AND_ROADMAP.md`  
Harness specification: `llm-lexical-stability-harness-implementation-spec.md`
Phase One evidence: `docs/PHASE_ONE_EVIDENCE_SUMMARY.md`

## 1. Purpose of this file

This is the durable editorial record for the article that began in the ChatGPT conversation
"Model Vocabulary and Stability." It preserves the argument as it has changed through the harness
design, implementation, corrective work, and early real-provider runs.

This file is deliberately not an article draft. It separates:

- the motivating practitioner observations;
- the strongest defensible hypothesis;
- the architecture that follows if the hypothesis is supported;
- what the harness currently shows;
- what the harness has not shown;
- the strongest technical objections;
- the evidence still needed;
- the proposed article structure;
- adjacent ideas that should not expand this article indefinitely.

Use this document as the source of truth when beginning a new editorial thread, commissioning
research, deciding whether the evidence is mature enough to draft, or checking whether a future
paragraph outruns the experiments.

### Authorial posture

Phillip is writing as a technically serious practitioner, not presenting himself as a data scientist
or ML researcher and not claiming academic novelty. That distinction should govern the article's
epistemic posture without becoming an apology or a recurring disclaimer.

The meta-story is part of the value of the piece. Heavy practical use produced an observation. That
observation became a hypothesis. Phillip separated the behavior he had seen from the mechanism he
could not support, built an eval harness, added rival hypotheses and falsifiers, sought prior art,
and discovered that adjacent versions of the problem are active areas of serious research and
product work. The interesting signal is independent convergence through disciplined investigation,
not priority of discovery.

The professional subtext should remain implicit. The article should demonstrate, rather than
announce: "This is what I do when I find something I don't understand." Do not turn the piece into a
job application. Let the quality of the observation, experimental design, course corrections, and
reporting carry that signal.

## 2. Source history

This plan consolidates three strands of work.

### 2.1 Model Vocabulary and Stability

- The original observation that some lexical or conceptual formulations appear more reliable for a
  model than application-equivalent alternatives.
- The distinction between user vocabulary, organizational ontology, and model-facing language.
- Plausible lexical substitution, including the spontaneous phrase "resource augmented generation"
  when retrieval-augmented generation was intended.
- Input-modality effects and the idea that speech-to-text produces a lossy intermediate
  representation.
- The architecture maxim "Flexible language. Stable ontology. Formal action."

### 2.2 The lexical-stability harness specification

- The conversion of the observation into falsifiable behavioral and architectural hypotheses.
- The separation of request adequacy, ambiguity, lexical variation, canonical meaning,
  model-facing rendering, procedures, and typed action boundaries.
- The experimental, statistical, and evaluation methodology.
- The requirement that the system be able to produce evidence against the original idea.

### 2.3 The implementation and Phase One results

- The discovery that the strongest early signal is not yet a model-native vocabulary effect.
- Evidence that repeated natural-language persistence can alter an exact operational argument.
- Evidence that a formal grounding boundary can prevent action based on hidden-state guesses.
- No current evidence that model-discovered renderings outperform canonical terminology.
- The v0.3.0 independent-case replication and broad v0.2.1 Opus analysis.
- The focused Opus 4.8 versus Sonnet 5 persistence comparison on the same v0.3.0 matrix.
- The finding that direct Opus handled every adequate boundary variant correctly.
- The resulting separation between user-language robustness, boundary safety, and internal
  representation persistence.

## 3. Current editorial verdict

There is an article here, but it is not yet the article implied by the earliest formulation.

The original formulation was approximately:

> Models have stable conceptual handles. Preserve their native vocabulary inside the agent loop and
> translate organizational language at the boundary.

That remains a useful hypothesis, but current evidence does not establish it.

The strongest article presently available is about a broader and more defensible engineering
problem:

> Natural-language agent systems accept linguistic artifacts, not intentions. Those artifacts can
> remain plausible while losing entity grounding, operational specificity, or exact argument
> content. Consequential systems should therefore allow flexible language at the interface, resolve
> it into grounded canonical intent, preserve operationally significant values through the agent
> loop, and cross a typed action boundary before changing state.

This is a behavioral and architectural claim. It does not require a theory of model cognition.

The lexical-handle hypothesis remains the load-bearing question for a more distinctive sequel or a
stronger version of this article:

> After application-level meaning has already been fixed, does the lexical representation supplied
> to the model still change downstream reliability?

The current answer is: not demonstrated.

Phase One instead produced a narrower positive result. Opus was robust to the current adequate
user-language variants, but it frequently changed an exact public message when already resolved
intent was repeatedly handed forward as free-form prose. Canonical authoritative state prevented
that drift in the eight-case RMI replication. The article should treat this course correction as a
result, not as a failure to confirm the opening intuition.

The first model-tier replication then found that canonical-state persistence preserved all 24
messages for both Opus 4.8 and Sonnet 5. Ordinary prose preserved 6 of 24 for Opus and 2 of 24 for
Sonnet. A visible exactness reminder had little effect for Opus but raised Sonnet to 12 of 24. This
is evidence that representation controls can interact with model tier, but it remains one
operation family and does not establish model-native lexical preferences.

## 4. Purpose, audience, and intended reader change

### Purpose

Show that terminology and representation in agent systems are operational design variables, while
carefully distinguishing lexical sensitivity from request inadequacy, ambiguity, state grounding,
and repeated natural-language reinterpretation.

### Primary audience

- Applied-AI engineers and agent architects.
- Technical leaders building natural-language interfaces to stateful business systems.
- Enterprise architects responsible for domain models, schemas, workflows, and systems of record.
- Researchers interested in prompt robustness, function calling, and agent evaluation.
- Practitioners deciding whether to invest in user prompting training or semantic middleware.

### Starting view

A technically informed reader will probably already accept that wording can change LLM output and
that production agents should use schemas and tool validation. The reader may therefore initially
see the idea as either prompt-engineering folklore or a rediscovery of ordinary domain modeling.

### Pressure

The difficult cases are not obviously malformed prompts or nonsensical outputs. They are plausible
substitutions and fluent transformations that preserve the shape of the request while changing an
entity, operation, referent, or exact argument. In a stateful loop, a small change can become an
external action.

### Reframing

Natural language is not a neutral serialization of intent. It is an inferential representation.
The system must decide where interpretation ends and formal state begins.

### Intended reader change

The reader should leave seeing linguistic flexibility, canonical intent, representation
persistence, procedures, and typed action as separate architectural layers that should be tested
rather than collapsed into one prompt.

### Landing

The practical question is not simply which words a model "likes." It is where an agent system should
stop asking language to carry distinctions that the application must preserve exactly.

## 5. Strongest defensible hypotheses

### H1: Controlled lexical non-equivalence

> For some agentic tasks, natural-language formulations that domain reviewers judge to have the
> same adequate and unambiguous application-level meaning may produce repeatably different
> operational behavior from a pinned model under otherwise identical conditions.

This is a behavioral hypothesis. It says nothing about why the effect occurs.

### H2: Boundary canonicalization

> Resolving flexible external language into grounded canonical entities, operations, and arguments
> before action may improve reliability and clarification behavior relative to direct execution.

### H3: Post-canonical lexical representation

> After application-level meaning is fixed, a stable model-facing lexical rendering may improve
> reasoning or execution relative to canonical IDs and definitions alone.

This is the distinctive lexical-adapter hypothesis. It is currently unsupported by the early run.

### H4: Natural-language persistence

> Repeatedly transforming an already resolved intent through free-form natural-language handoffs
> creates additional opportunities for operational arguments to drift, even when the high-level
> operation remains recognizable.

### H5: Human training versus middleware

> Structured prompting training and canonical intent middleware may both improve task outcomes,
> but they impose different costs and may substitute for one another. Their value should be
> measured as cost per successful task rather than assumed from prompt quality or token price.

## 6. Rival hypotheses

The article must treat these as genuine competitors rather than cleanup categories.

### R1: Request inadequacy dominates

Many supposed lexical failures may be caused by missing entity identities, arguments, referents,
constraints, or contextual facts. Once adequacy and ambiguity are controlled, the lexical effect
may be small.

### R2: Ordinary distributional sensitivity is sufficient

LLMs condition on token sequences. Different wording changes the conditional distribution. There
may be no stable or architecturally useful "handle" beyond ordinary prompt sensitivity, corpus
frequency, tokenization, and domain convention.

### R3: Canonicalization does all the useful work

Once the application fixes the entity, operation, and arguments, model-facing lexical rendering may
add nothing. The useful architecture may be a formal domain boundary, not a lexical adapter.

### R4: Procedure or typed interface dominates

Reliability gains may come from reusable procedural guidance, constrained output, schema
validation, or typed tools rather than canonical vocabulary.

### R5: A strong direct frontier model is already sufficient

A strong model with complete context and an explicit clarification policy may perform inside a
practical-equivalence margin of a more complex pipeline. If so, middleware may not earn its cost for
the tested task family.

### R6: The evaluator manufactures the effect

Exact matching may reject semantically equivalent values. LLM judges may themselves be sensitive to
prompt phrasing. A supposed lexical effect may be an evaluation artifact.

### R7: Added calls create the failure

A pipeline with more model invocations has more opportunities to fail. A result attributed to
language persistence or canonicalization may actually be caused by unequal call count, context
length, or packaging.

## 7. Epistemic ledger

### 7.1 What Phillip knows directly from practice

- Terminology changes have sometimes appeared to affect editing, code-generation, and agentic
  outcomes.
- Models sometimes repeatedly supply a label different from the user's preferred terminology.
- Organizations use local jargon, overloaded terms, tacit distinctions, and vocabulary that varies
  across teams.
- Humans can retain the intended concept while producing a nearby but incorrect phrase.
- Spoken requests tend to contain more lexical variation, provisional language, repair, and implicit
  context than carefully typed requests.

These observations generate hypotheses. They are not controlled evidence.

### 7.2 Direct harness findings so far

The v0.2 and v0.2.1 real-provider checks established that the corrected harness can execute,
validate, trace, and score the relevant conditions without provider errors, length terminations,
aborted cells, or schema-invalid target outputs.

The frozen v0.3.0 Opus replication expanded the request-more-information persistence test to eight
independent canonical cases. Every case contained an exact public message that the operation would
persist externally. The three call-balanced conditions each used four execution-model calls:

- Free-form persistence preserved the exact message in 6 of 24 executions, or 25 percent.
- Free-form persistence plus a visible verbatim reminder preserved it in 5 of 24, or 20.8 percent.
- Canonicalize-once preserved it in 24 of 24, or 100 percent.

For canonicalize-once minus free-form persistence, the paired delta was 0.75 with a case-clustered
95 percent interval from 0.50 to 0.917. Seven cases favored canonicalize-once, none favored prose,
and one tied. The canonical-case exact sign-test result was `p = 0.015625`. Canonicalize-once also
beat the visible-reminder condition in seven cases with one tie and `p = 0.015625`. The reminder
did not improve over unreminded prose: delta -0.042, interval -0.208 to 0.208, `p = 0.625`.

The source corpus included canonical, natural, and high-distance request wording, but the gold-start
conditions removed that wording before the first model call. The effective-input audit found one
identical first model input for the three source requests inside every condition and case. Those
rows are stochastic executions, not evidence about user-language distance.

This supports a bounded finding for exact public-message preservation under one operation family
and one pinned frontier model. It does not establish a model-native lexicon, user-language effect,
or cross-operation generalization.

Boundary-grounding checks also produced two clear observations:

1. For "Refund the duplicate charge," direct execution inferred a hidden singleton order and acted,
   while the canonicalized path requested the order identity.
2. For "Request more information for incident INC-3120," direct execution attempted an action with
   no message, while the canonicalized path asked what message should be sent.

These support further study of grounding and clarification. They do not prove lexical instability.

The broad v0.2.1 boundary track then supplied distinct user wording to Opus. Across five adequate
canonical cases and three operation families, direct Opus completed all 20 executable variants
correctly, including all eight high-distance variants. This is evidence against a useful lexical
effect in the current Phase One corpus. It also means aggregate errors in `adequate/varied` rows
cannot be attributed to wording without conditioning on architecture.

On the 12 clarification-target boundary requests, A0 direct execution acted eight times, A1 with an
explicit clarification policy acted five times, and both runtime canonicalization conditions acted
zero times. The canonicalized paths clarified all 12. This supports a bounded boundary-safety
finding while leaving one unnecessary clarification as a measured tradeoff.

The broad post-canonical comparison contained five genuinely distinct model-discovered renderings
across three operations. Bare canonical structure, canonical rendering, and model-discovered
rendering all scored five of five. The lexical-adapter hypothesis therefore remained a null result
under a small ceiling-bound test.

One apparent rendering benefit was traced to a contract mismatch. The canonicalizer produced
`Billing team` where the typed interface required enum `BILLING`; the bare executor refused while a
rendered executor normalized the value and acted. This is a useful architecture diagnostic, but it
is not clean evidence for a preferred lexical handle.

### 7.3 What current results do not show

- Model-discovered terminology did not outperform canonical terminology on the small
  post-canonical set.
- No stable model-native lexicon has been demonstrated.
- No general percentage benefit for a lexical adapter can be reported.
- No cross-model or cross-version lexical preference has been established. The completed
  cross-model result concerns representation persistence, not preferred terminology.
- No cross-operation article-wide estimate is available.
- No causal mechanism inside the model has been identified.

### 7.4 Inferences that remain testable

- Exact operational arguments may be especially vulnerable to repeated prose transformations.
- Grounding rules may prevent plausible but unsafe inference from hidden state.
- Canonicalization may be more valuable for preserving state than for improving vocabulary.
- A compact preservation instruction may eliminate some drift without requiring full canonical
  middleware.
- The value of middleware may be larger for economical models or naturally phrased requests than
  for a frontier model receiving clean instructions.

### 7.5 Claims that must remain bracketed

- A model literally has a private vocabulary.
- A model maintains one internal canonical ontology.
- The model translates organizational words into preferred internal words before reasoning.
- Particular terms are semantic attractors in a known latent-space geometry.
- Concept identity and lexical identity correspond to known separable internal structures.
- The human substitution example and LLM behavior share a mechanism.
- Voice input is inherently less precise than typing.
- A model-facing lexical adapter is generally necessary.

## 8. Terminology and conceptual layers

### User language

The words supplied by the user. They may be local, colloquial, formal, provisional, spoken,
organization-specific, or incomplete.

### Linguistic artifact

The actual text received by a model. It is shaped by composition, interface, transcription,
normalization, context assembly, and prior agent transformations. It is not identical to the user's
intention.

### Application-level meaning

The entity, operation, arguments, constraints, and expected state transition the application should
recognize.

### Canonical ontology

The registered entities, operations, arguments, relationships, state, and permissible transitions
of the application domain.

### Canonical intent

The grounded entity, operation, arguments, constraints, and provenance resolved for one request.

### Semantic normalization layer

The reader-friendly name for the boundary component that maps user language into canonical intent,
preserves uncertainty, and requests clarification when one mapping is not justified.

### Canonical intent middleware

The architectural name for the runtime layer implementing semantic normalization, grounding,
provenance, and validation.

### Model-facing rendering

The language used to present already canonical meaning to a reasoning or execution model.

### Lexical adapter

An optional component that renders canonical intent using empirically tested model-facing
terminology. Current evidence does not show that this component improves performance.

### Plausible substitution

A nearby expression that remains locally coherent enough to avoid an obvious error signal while
changing or obscuring the canonical referent, operation, or argument.

### Formal action

A validated state transition or typed tool invocation whose permitted entity, operation, and
arguments are defined outside free-form prose.

### Argument preservation

The contract governing whether a value must remain `VERBATIM`, may be normalized into a
`CANONICAL` value, or may be preserved only `SEMANTICALLY`.

## 9. The argument spine

### Primary reasoning engine

Inference to the best architectural explanation from controlled behavioral comparisons.

### Secondary engines

- Induction from multiple canonical cases and operation families.
- Elimination among lexical sensitivity, inadequacy, ambiguity, persistence, procedure, and
  interface explanations.
- Analogy to canonical data models and typed interfaces, used carefully and not as evidence.

### Cratylus movement

1. **Thing:** A knowledgeable speaker says "resource augmented generation" while intending
   retrieval-augmented generation. Everyone understands. Nothing appears broken.
2. **Mechanism:** Conceptual identity survives while lexical identity mutates. A plausible phrase
   passes through because it remains coherent.
3. **Abstraction:** Agent systems receive linguistic artifacts that may be repeatedly reinterpreted.
4. **Pressure test:** Prompt wording effects are already known, synonyms are rarely exact, and the
   current harness has not shown a model-native vocabulary advantage.
5. **Consequence:** Move consequential decisions across a grounded formalization boundary, preserve
   protected arguments, and test whether any separate lexical adapter earns its cost.
6. **Return:** The original verbal mistake was harmless because knowledgeable humans repaired it.
   An autonomous action boundary may contain no such repair. Plausibility is not correctness.

## 10. Detailed article outline

### Section 1: The harmless mistake

Open with Phillip saying "resource augmented generation" while intending retrieval-augmented
generation. The substitution is wrong but intelligible. The listeners repair it without interrupting
the conversation.

The scene establishes that conceptual identity and lexical identity are not the same, and the path
between them is not neutral. It is an illustration, not evidence that humans and LLMs share a
mechanism.

Possible line:

> The most dangerous translation errors in natural-language systems are not nonsense. They are
> plausible substitutions.

Open tension: What happens when no informed person notices that the wrong phrase has survived?

### Section 2: Models receive artifacts, not intentions

Generalize from the scene to the interface chain.

```text
thought -> written composition -> model input
```

```text
thought -> spoken production -> acoustic signal -> transcription -> normalized text -> model input
```

```text
user artifact -> interpretation -> handoff -> plan -> procedure -> action proposal -> tool
```

Speech may be richer in context while being less formally specified. Typing may be more structured
while omitting tacit concerns. Modality changes the distribution of language and the transformations
applied to it; it does not determine quality absolutely.

Possible line:

> Voice does not remove the interface between human thought and machine action. It replaces an
> explicit interface with a more inferential one.

Keep modality concise unless it becomes necessary to explain the artifact chain. A full treatment
may deserve a separate essay.

### Section 3: Synonyms are not necessarily operational synonyms

State the bounded behavioral hypothesis: application-equivalent formulations may not be
behaviorally interchangeable for a language model.

Possible non-cognitive explanations include training-data frequency, tokenization, technical corpus
conventions, post-training examples, pragmatic differences, syntax, and context interactions.

Do not say models "think in" preferred words. Say wording is an experimental variable and may provide
a more or less reliable access path to learned behavior.

Possible line:

> In deterministic software, changing a symbol's name should not change the operation it denotes.
> In a language model, the name is part of the input that helps determine which operation is
> recognized in the first place.

End with the skeptical question: Wording effects are already known, so what is new here?

### Section 4: The ordinary software answer, and why it is only part of the answer

Grant the strongest skeptical point. Production systems already use schemas, domain models, entity
resolution, typed APIs, validation, state machines, and systems of record.

The article is not proposing that the LLM become the world model. The LLM interprets and proposes;
the formal application decides what exists, what state it is in, and which actions are valid.

Use the chess analogy carefully. The model may interpret "move my knight over there," but formal
state determines where the knight is and whether the move is legal. Business domains, unlike chess,
can be incomplete, contested, and mutable.

Possible line:

> Use the model as a linguistic interface to the world model, not as the world model itself.

### Section 5: Three vocabularies, not one

Distinguish:

1. User vocabulary: local and flexible.
2. Organizational ontology: the formal domain representation.
3. Model-facing rendering: an implementation choice for communicating resolved meaning to a model.

These layers may coincide, but the architecture should not assume that they do. The model-facing
vocabulary should not become the enterprise domain model. If it proves useful, it is an adapter layer
and a versioned implementation dependency.

The key question is whether the third layer adds value once the second has fixed the meaning.

### Section 6: Building a harness capable of saying no

Explain how the observation became a falsifiable engineering investigation. Separate:

- request adequacy from lexical variation;
- ambiguity from paraphrase;
- runtime canonicalization from gold canonical intent;
- canonical representation from model-facing rendering;
- natural-language persistence from canonicalize-once;
- inline procedure from reusable procedure;
- free-form proposal from typed tool;
- deterministic evaluation from optional model judgment.

Creative models may generate candidate tests, but frozen canonical artifacts and deterministic
final state define correctness.

This section should also make the practitioner method visible without becoming autobiographical.
Phillip noticed a behavior through use, proposed an explanation, backed away from unsupported claims
about model internals, invited stronger rival explanations, and built the harness so that a null
result could defeat the original idea. The authority of the section comes from that process, not from
presenting Phillip as an ML researcher.

Do not turn the article into the complete harness runbook. Select only the comparisons necessary for
the argument and link to the implementation separately.

### Section 7: What Phase One actually found

Report four findings with their limitations.

1. Direct Opus handled all 20 adequate executable boundary variants correctly across five cases,
   including every high-distance variant. The current corpus did not produce a user-language
   lexical effect.
2. In the eight-case call-balanced RMI replication, canonicalize-once preserved the exact public
   message in 24 of 24 executions. Free-form persistence preserved it in 6 of 24. Seven independent
   cases favored canonical-once, none favored prose, one tied, and the exact case-level sign-test
   result was `p = 0.015625`.
3. A formal boundary eliminated false action on the 12 clarification-target boundary requests,
   while direct Opus still acted on eight and the direct clarification-policy condition acted on
   five. The canonicalized conditions also produced one unnecessary clarification.
4. Model-discovered renderings did not beat canonical or bare structured representations. All were
   at ceiling in the five-case post-canonical comparison.
5. In the same eight-case RMI matrix, both Opus 4.8 and Sonnet 5 scored 24 of 24 under LP1.
   Ordinary prose scored 6 of 24 for Opus and 2 of 24 for Sonnet. The LP1-minus-prose benefit was
   0.75 for Opus and 0.917 for Sonnet; the cross-model difference was 0.167 with a 95 percent
   interval of [-0.042, 0.458]. The exactness reminder produced a secondary cross-model difference
   of 0.458 [0.208, 0.750], favoring Sonnet in five cases and Opus in none.

The first and fourth points are important non-findings. The experiment narrowed the original thesis.
The supported signal concerns grounding and persistence, not a model-native vocabulary.

### Section 8: Where should language end?

Present the progressive ladder:

```text
user language
  -> explicit clarification policy
  -> grounded canonical intent
  -> optional reusable procedure
  -> typed action boundary
```

Each transition should be evaluated for marginal reliability, cost, latency, and operational
complexity. Not every field requires the same preservation rule:

- `VERBATIM`: exact user-authored text must survive.
- `CANONICAL`: normalize into a registered identifier or typed value.
- `SEMANTIC`: equivalent wording is acceptable.

Possible line:

> The question is not whether natural language belongs in the system. It is which distinctions we
> are still willing to entrust to natural language at the moment of action.

### Section 9: The strongest case against middleware

State the countercase at full strength:

- A frontier model with complete context may already be good enough.
- Middleware adds calls, latency, token cost, failure surfaces, schemas, deployment dependencies,
  and maintenance.
- Canonicalization can discard useful uncertainty, register, or organizational nuance.
- A compact instruction such as `message: string [VERBATIM]` may solve the observed problem more
  cheaply.
- A lexical adapter may become brittle across model upgrades.

Added architecture must improve cost per successful and safe task, not merely one accuracy column.
If a strong direct model remains inside a practical-equivalence margin and middleware costs more,
the correct conclusion for that domain may be not to build the middleware.

### Section 10: Training the humans or absorbing human variation

Introduce the Phase Two factorial design:

| User condition | Direct execution | Canonical intent middleware |
|---|---:|---:|
| Natural or untrained interaction | A | B |
| Trained, formal interaction | C | D |

Ask:

- What is the benefit of prompting training without middleware?
- What is the benefit of middleware for natural users?
- Does middleware reduce the marginal benefit of training?
- Does training improve wording, or does it cause users to supply missing information?
- How quickly does training adherence decay?
- Can an economical execution model plus middleware match frontier-model task success at lower cost?

Use cost per successful task, including model cost, engineering cost, user composition time, training
cost, and expected error cost.

Describe participants by AI experience, role, domain fluency, writing habits, and exposure to
training rather than reducing them to high- and low-ability users.

### Section 11: A research program that needs real language

Synthetic paraphrases are useful for controlled testing but cannot represent the full variation
produced by people with different jobs, institutions, writing habits, domain knowledge,
conversational styles, and AI experience.

Invite enterprise workflow vendors, service-desk organizations, research groups, and employers with
diverse user populations to collaborate on de-identified task scenarios or a human-participant
study.

Offer:

- a frozen, auditable harness;
- deterministic task and final-state evaluation;
- a study design separating training, middleware, and execution-model tier;
- a scoped pilot reporting quality, safety, adherence, latency, and cost per successful task.

A partner contributes participant diversity, domain tasks, and operational cost knowledge. Phillip
contributes the harness, experimental design, architectural analysis, and appropriate reporting.

Return to the opening substitution. The humans on the call repaired it because they knew what
Phillip meant. The next generation of agent systems must either reconstruct that kind of repair
reliably or know when not to act.

## 11. Load-bearing joints

### J1: Application-equivalent language can be operationally non-equivalent

- **Engine:** Controlled induction.
- **Must be true:** Human-reviewed adequate and unambiguous variants produce repeatable differences
  on deterministic operational outcomes.
- **Evidence required:** Multiple independent canonical cases, repeated conditions, fixed prompts,
  and case-level statistics.
- **Falsifier:** Differences vanish after adequacy control, evaluator repair, or replication.
- **Strongest objection:** The variants were not actually equivalent.
- **Repair:** Narrow the claim to the variation classes that survive adjudication.

### J2: Canonical intent improves boundary behavior

- **Engine:** Paired architectural comparison.
- **Must be true:** The canonicalized path improves grounding, clarification, or final state after
  controlling information, model calls, and tool affordances.
- **Evidence required:** Direct versus runtime-canonicalized paired conditions with equal domain
  context and a strong direct clarification policy.
- **Falsifier:** A direct frontier model performs within the practical-equivalence margin at lower
  complexity.
- **Strongest objection:** The middleware condition received more information or a more explicit
  procedure.
- **Repair:** Use gold intent, information-parity controls, and call-balanced comparisons.

### J3: Model-facing vocabulary matters after meaning is fixed

- **Engine:** Paired post-canonical experiment.
- **Must be true:** A tested rendering materially outperforms canonical IDs and definitions alone on
  held-out cases.
- **Evidence required:** Real lexical contrast, multiple operations, no ceiling effect, fresh model
  instances, and versioned discovery.
- **Falsifier:** Canonical, discovered, and definition-only renderings remain practically equivalent.
- **Strongest objection:** "Stable handles" merely rename ordinary corpus frequency.
- **Repair:** If reproducible, describe the effect as a versioned behavioral dependency without
  asserting mechanism. If not, remove the lexical-adapter claim.

### J4: Repeated prose transformations cause exact argument drift

- **Engine:** Paired trajectory and final-state comparison.
- **Must be true:** Call-balanced free-form handoffs lose protected values more often than
  canonicalize-once across independent cases.
- **Evidence available:** Eight RMI cases, three stochastic gold-start executions per case,
  deterministic first-divergence tracking, and a visible-verbatim-contract ablation. LP1 beat LP0B
  in seven cases with one tie; the visible reminder did not improve over LP0B.
- **Remaining evidence:** Replication on another model and, for broader wording claims, a runtime
  design in which distinct user requests actually reach the tested model.
- **Falsifier:** A compact preservation instruction eliminates the difference, or the effect does not
  replicate.
- **Strongest objection:** The initial signal is one task artifact, not a general persistence effect.
- **Repair:** Scope the claim to exact public-message preservation or the tested operation family.

### J5: Middleware can substitute for human prompting training

- **Engine:** Randomized factorial comparison and cost analysis.
- **Must be true:** Middleware improves naturally phrased requests and reduces the incremental value
  of training without unacceptable cost.
- **Evidence required:** Real participants, randomized training, matched tasks, delayed adherence,
  and operational outcomes.
- **Falsifier:** Training dominates middleware, or both primarily add missing information rather than
  stabilize representation.
- **Strongest objection:** User populations and job roles create irreducible confounding.
- **Repair:** Randomize within appropriate strata and present organization-specific rather than
  universal estimates.

## 12. Strongest technical case for the article

1. Models consume token sequences, so perfect invariance across human-judged paraphrases should not
   be assumed.
2. Agent workflows can turn small interpretation or representation differences into tool arguments
   and persistent state.
3. Plausible substitutions may evade clarification precisely because they remain coherent.
4. Formal domain state can identify legal entities and transitions without requiring the model to
   carry them through prose.
5. Canonical intent, preservation contracts, and typed action interfaces are independently testable
   interventions.
6. Early traces show exact argument drift under call-balanced natural-language persistence and
   unsafe completion from hidden-state uniqueness.
7. The research program explicitly permits the simplest direct architecture to win.

## 13. Strongest technical case against the article

1. Wording sensitivity is already well known and may not support a distinctive contribution.
2. Natural-language synonyms are rarely semantically or pragmatically identical.
3. The original "model-native vocabulary" framing risks anthropomorphism and prompt folklore.
4. Canonicalization is ordinary software architecture under new terminology.
5. The strongest observed persistence result covers eight independent cases in one operation
   family and one pinned model. It may not generalize to other operations, models, or preservation
   contracts.
6. Direct and canonicalized conditions may differ in information packaging, not ontology.
7. More architecture can manufacture more failure opportunities and operating cost.
8. Model-discovered renderings have not produced an advantage.
9. A synthetic support domain may not generalize to less formal organizational work.
10. Human training and real linguistic variation remain untested.

## 14. Evidence plan before drafting claims as findings

### Before treating persistence as more than a motivating trace

- [x] Implement and validate v0.2.1 corrections.
- [x] Build eight independent request-more-information cases.
- [x] Compare call-balanced persistence without a visible preservation reminder, persistence with
  the reminder, and canonicalize-once.
- [x] Track exact protected-argument preservation and first argument-divergence stage.
- [x] Bootstrap at the canonical-case level and use case-level directional inference.
- [x] Report calls, tokens, latency, and cost.
- [ ] Replicate the frozen persistence protocol on an economical model.
- [ ] Use a runtime input design for any claim about human wording or lexical distance.

### Before claiming a lexical-adapter benefit

- Demonstrate genuine lexical contrast between canonical and model-discovered renderings.
- Avoid ceiling effects with tasks that require nontrivial reasoning or argument use.
- Show paired improvement after gold canonical intent is fixed.
- Replicate across multiple operations.
- Test at least one additional model or version.
- Treat model-specific behavior as a versioned dependency.

### Before claiming organizational ROI

- Recruit real participants with varied AI experience and job contexts.
- Randomize a structured-prompting intervention.
- Measure immediate and delayed behavior.
- Separate improvements in information completeness from improvements in expression.
- Include human composition time and adherence in the cost model.
- Compare at least one economical execution model after freezing the frontier baseline.

## 15. Article evidence map

| Proposed claim | Current status | Evidence source | Publication treatment |
|---|---|---|---|
| Plausible substitutions can preserve local coherence | Direct human observation | RAG verbal substitution | Opening illustration only |
| Natural-language artifacts can change across interface layers | Defensible systems description | Artifact chain and modality analysis | Explain, do not mechanize |
| Equivalent wording can change LLM behavior | Prior-art-supported broad premise | Multi-prompt and robustness literature | Import with verified citations |
| Controlled lexical variants create operational differences | Not observed for direct Opus in Phase One | v0.2.1 boundary, 20/20 adequate variants | Report as a bounded null result |
| Formal grounding can prevent hidden-state inference | Early direct observation | v0.2 inadequate-request traces | Present as exploratory trace |
| Repeated prose handoffs can alter exact arguments | Supported for one operation family and pinned Opus version | v0.3.0, eight RMI cases | Present as a bounded result |
| Canonicalize-once improves exact preservation | Supported for exact RMI public messages in the tested protocol | v0.3.0 call-balanced comparison | Report effect, interval, case directions, and scope |
| Canonical persistence can equalize frontier and economical model success | Supported only for the tested RMI protocol, where both models reached 24/24 under LP1 | v0.3.0 Opus versus Sonnet comparison | Bounded model-tier result, not a general cost claim |
| Exactness reminders interact with model tier | Secondary bounded signal: Sonnet improved while Opus did not | v0.3.0 cross-model reminder ablation | Report interval and case directions; request replication |
| Model-discovered terms improve execution | Unsupported | Post-canonical v0.2 cells at ceiling | Explicit non-finding |
| Middleware beats user training | Open Phase Two question | No participant study yet | Call to action, not conclusion |
| Economical model plus middleware can match frontier performance | Supported only for one exact-message operation family | v0.3.0 Opus versus Sonnet LP1, both 24/24 | Do not generalize without more families and cost analysis |

## 16. Prior-art-aware positioning

The article must not claim novelty for the general fact that prompt wording can affect model
performance. Before publication, verify and cite primary sources in these areas:

- multi-prompt evaluation and performance variation under instruction paraphrase;
- semantic consistency under meaning-preserving rewrites;
- agentic function-calling robustness;
- tool-name and tool-description perturbation;
- code-model robustness under identifier renaming and semantics-preserving transformations;
- evaluation artifacts created by exact match;
- robustness and calibration of LLM judges;
- canonical semantic parsing, typed APIs, and domain-model architecture;
- speech-recognition errors involving domain terminology and plausible substitutions.

Finding substantial prior art is part of the article's story, not an embarrassment to conceal. The
claim is not that Phillip discovered a new branch of ML. It is that a practitioner followed an
unfamiliar behavioral observation far enough to independently converge on questions that researchers
and product teams are taking seriously, then used that prior work to narrow and improve his own
tests. The article's contribution is the practitioner investigation, the harness, and the results,
including a null result if that is what the evidence supports.

Prior work named during harness planning and requiring verification before use includes:

- *State of What Art?*
- SCORE
- Berkeley Function Calling Leaderboard or BFCL methodology
- IBM work on robustness of agentic function calling
- RoTBench
- RAGAS, only for retrieval-specific experiments

The distinctive research question is narrower:

> Once natural-language variation has been resolved into stable canonical application meaning, does
> the lexical representation subsequently presented to the model still affect operational
> reliability?

A second potentially distinctive question is:

> When intent is already fixed, does preserving it through free-form natural-language handoffs cause
> more exact operational drift than canonicalizing once and preserving typed state?

## 17. Figures and tables for the eventual article

### Figure 1: The artifact chain

```text
human intent
  -> user expression
  -> interface or transcription artifact
  -> boundary interpretation
  -> agent handoffs
  -> action proposal
  -> typed system state
```

### Figure 2: The three-language architecture

```text
user vocabulary
  -> canonical organizational entity and operation
  -> optional model-facing rendering
  -> typed action
```

### Figure 3: Where language ends

```text
flexible language
  -> clarification
  -> grounded canonical intent
  -> protected arguments
  -> typed action
```

### Table 1: Observation, inference, and unsupported mechanism

Show one column each for what was observed, what the architecture infers, and what remains unknown
about model internals.

### Table 2: Competing explanations

Compare lexical sensitivity, request inadequacy, ambiguity, persistence, procedure, interface, and
evaluation artifact, along with the experiment that distinguishes each.

### Table 3: Phase Two factorial design

Show natural versus trained user language crossed with direct execution versus canonical intent
middleware, followed by a second model-tier dimension.

## 18. Motifs and reusable lines

### Primary motif

"Resource augmented generation" as a harmless plausible substitution repaired by knowledgeable
humans.

### Secondary motif

Chess as the distinction between linguistic interpretation and formal world state.

### Optional motif

The transcript as a lossy intermediate representation. Use only if modality remains in the article.

### Candidate lines to preserve, not automatically publish

> Models do not receive intentions. They receive linguistic artifacts shaped by interfaces.

> Vocabulary is not merely the label on the control. Sometimes it is part of the control surface.

> Flexible language. Stable ontology. Formal action.

> Linguistic flexibility can exist at the interface. Operational ambiguity cannot exist at the
> point of action.

> The most dangerous translation errors in natural-language systems are not nonsense. They are
> plausible substitutions.

> Use the model as the linguistic interface to the world model, not as the world model itself.

> Treat model-effective terminology as an adapter layer, not as the domain model.

> Be provocative about what was observed. Be humble about why it happened.

> The more natural the interface feels to the user, the more semantic engineering may be required
> behind the boundary.

## 19. Ideas bracketed from this article

### Intelligence as a stack of preferences

Keep as a separate future article. It is not necessary to establish lexical non-equivalence,
canonical intent, persistence, or formal action. Introducing it would expand a bounded engineering
investigation into claims about intelligence, identity, preference, and cognition.

### Full voice-interface thesis

The typed-versus-spoken distinction is relevant to the artifact chain, but a complete treatment of
modality-conditioned language, prosody loss, transcript normalization, and speech-interface design
may deserve its own article.

### Tacit ontology and institutional semantics

Preserve as either a later section or a separate essay. Formal ontology tells an agent what entities
and operations exist. Institutional semantics includes local connotation, status, taboo, role,
register, and distinctions that participants understand without formal documentation. This is
important but could overwhelm the narrower empirical article.

### Mountweazel analogy

A mountweazel is deliberately fabricated, whereas the relevant substitutions here are accidental.
The analogy may illustrate how plausibility lets a false object survive among real ones, but it
should not carry the mechanism.

## 20. Working titles

### Architecture-forward

- Flexible Language, Stable Ontology, Formal Action
- Where Language Should End in an AI Agent
- The Formal Boundary Behind a Natural-Language Agent
- Agents Need Grounded Intent, Not Better-Sounding Prompts

### Lexical-forward

- When Synonyms Stop Being Synonymous
- Vocabulary as a Control Surface
- The Hidden Cost of Translating an Agent's Working Vocabulary
- Concept Identity, Lexical Identity, and Model Behavior

### Human-interface-forward

- Models Do Not Receive Intentions
- The Plausible Substitution Problem
- Natural Interfaces Move the Work Behind the Boundary
- Should We Train People to Speak AI?

The final title should follow the result. Do not use a model-native-vocabulary title if the lexical
adapter hypothesis remains unsupported.

## 21. Drafting gates

### Safe to draft now

- The opening human substitution scene.
- The distinction between intention and linguistic artifact.
- The architecture and experimental questions.
- The strongest counterarguments.
- The honest report of the exploratory traces and non-finding.
- The Phase Two call to action.

### Supported after the v0.3.0 replication, with narrow scope

- Numerical reporting for exact public-message preservation in the tested RMI protocol.
- A bounded claim that canonical authoritative state outperformed repeated free-form handoffs for
  the pinned Opus version.
- A bounded non-finding that the compact visible verbatim reminder did not improve over unreminded
  prose for Opus in this run.
- A bounded model-tier finding that canonical-state persistence reached 24 of 24 for both Opus 4.8
  and Sonnet 5 while their prose conditions differed.
- A secondary signal that the visible exactness reminder helped Sonnet more than Opus on this
  operation family.

Do not turn these into a universal claim that a frontier model "needs" middleware.

### Must wait for later research

- Model-native lexical advantage.
- Cross-model lexical stability.
- ROI of training versus middleware.
- Economical model plus middleware versus frontier direct execution across multiple operation
  families and realistic cost inputs.
- Effects of typed versus spoken input among real participants.

## 22. Proposed drafting order

When the next evidence checkpoint is complete:

1. Update Sections 7, 14, and 15 of this tracker with the frozen results.
2. Run a new adversarial Steelman pass against the actual findings.
3. Verify the prior-art sources and build a citation ledger.
4. Decide whether the article is primarily about lexical representation, natural-language
   persistence, or the formalization boundary.
5. Freeze the one-sentence thesis and title family.
6. Draft Sections 1 through 4 as one conceptual movement.
7. Draft the harness and findings sections from the frozen report.
8. Draft the countercase before the architectural recommendation.
9. Draft the Phase Two collaboration invitation.
10. Audit every empirical sentence against the evidence map.

## 23. Suggested continuation prompt for the article thread

> Continue the article-development work for "Model Vocabulary and Stability." Read
> `docs/ARTICLE_OUTLINE_AND_EVIDENCE_TRACKER.md` and `docs/STATUS_AND_ROADMAP.md` completely. Do not
> draft the article unless I explicitly ask. First update the evidence ledger from the newest frozen
> harness results, identify which proposed article claim those results strengthen or weaken, and
> preserve the distinction between observed behavior, architectural inference, and unsupported
> claims about model internals. Preserve Phillip's posture as a technically serious practitioner who
> followed an observation into a falsifiable investigation, not as a data scientist or ML researcher
> claiming academic novelty. Keep the professional signal implicit: the work should demonstrate
> "this is what I do when I find something I don't understand" without turning the article into a job
> application. Keep "intelligence as a stack of preferences" bracketed as a separate future article.

## 24. Change log

### 2026-07-21

- Created the first durable article-specific outline and evidence tracker.
- Consolidated the original vocabulary-stability conversation, harness specification, v0.2
  findings, v0.2.1 roadmap, and Phase Two research opportunity.
- Narrowed the current defensible article from model-native vocabulary to grounded intent,
  representation persistence, and formal action.
- Preserved the lexical-adapter hypothesis as an explicit open question and non-finding.
- Added the human-training versus middleware study and collaboration call to action.
- Added the practitioner authorial posture, independent-convergence framing, and implicit
  professional subtext while explicitly rejecting claims of academic novelty.
- Restored the tracker in the Git-backed repository after the original project-mirror copy was
  removed during a task refresh.
- Added the frozen v0.3.0 eight-case Opus persistence replication, corrected canonical-case
  inference, effective-input audit, bounded publication claim, and economical-model replication
  gate.

### 2026-07-22

- Added the compatible 72-cell Sonnet 5 replication and formal Opus-versus-Sonnet difference in
  differences.
- Recorded the bounded 24-of-24 LP1 result for both models, the inconclusive primary cross-model
  benefit difference, and the stronger secondary reminder interaction.
- Preserved cross-model lexical preference, multi-operation generalization, and ROI as open claims.
