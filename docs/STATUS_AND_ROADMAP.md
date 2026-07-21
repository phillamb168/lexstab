# Lexical Harness Status and Roadmap

Article editorial tracker: `docs/ARTICLE_OUTLINE_AND_EVIDENCE_TRACKER.md`

Last updated: 2026-07-21

Status: v0.2.0 exploratory runs complete. The v0.2.1 corrective release is complete: code, schemas,
prompts, tests, versioned inputs, human review, immutable freeze, and both targeted real-provider
validations have passed. The next research gate is an independent-case RMI replication corpus, not
the full multi-repetition benchmark or Phase Two.

This file is the durable handoff point for continuing the project in a new Codex or Claude Code
thread. It records the evidence collected so far, approved corrective work, implementation order,
acceptance criteria, commands, phase-two research design, and the claims that the current evidence
does and does not support.

## 1. Recommended thread boundary

Fork the conversation after this file exists and before beginning the v0.2.1 implementation.

Reasons:

- v0.2.0 analysis is complete and should remain a stable historical checkpoint.
- v0.2.1 has a bounded implementation scope and explicit definition of done.
- The new thread can load this file rather than reconstructing decisions from a long conversation.
- The current repository contains intentional uncommitted work. A fresh thread must inspect and
  preserve it rather than assuming a clean worktree.

Suggested prompt for the new thread:

```text
Continue the lexical-harness project from:

/Users/phil/Work/lexical-harness/docs/STATUS_AND_ROADMAP.md

Implement the approved v0.2.1 measurement-integrity work described there. Start by inspecting the
current dirty worktree and producing an implementation plan mapped to the six approved corrections.
Preserve v0.1.0, v0.2.0, all historical run artifacts, and all unrelated user changes. Do not begin
the expanded phase-one corpus or phase-two human study yet. Stop for Phillip's review at every
dataset-approval gate.
```

## 2. Current repository and artifact state

Repository:

```text
/Users/phil/Work/lexical-harness
```

Historical benchmark manifests that must remain immutable and verifiable:

```text
dataset/manifests/benchmark-v0.1.0.json
dataset/manifests/benchmark-v0.2.0.json
```

Most recent real-provider runs:

```text
runs/run-v0.2-provider-check-v2-20260721
runs/run-v0.2-rmi-check-v2-20260721
```

Primary reports:

```text
runs/run-v0.2-provider-check-v2-20260721/report.md
runs/run-v0.2-rmi-check-v2-20260721/report.md
```

Primary metrics:

```text
runs/run-v0.2-provider-check-v2-20260721/metrics.json
runs/run-v0.2-rmi-check-v2-20260721/metrics.json
```

Both runs were healthy and baseline-eligible:

- 154 of 154 cells scored.
- Zero provider errors.
- Zero length terminations.
- Zero aborted cells.
- Zero schema-invalid cells.
- No generated measurement warnings.

Resolved model roles in these runs:

- Execution model: `claude-opus-4-8` through Anthropic.
- Boundary canonicalizer: `google/gemini-2.5-pro` through OpenRouter.
- Procedure router: `mistralai/mistral-small-2603` through OpenRouter.
- Optional evaluation judge: disabled.
- Primary scoring: deterministic.

## 3. What v0.2.0 established

### 3.1 Harness corrections worked

- LP3 produced seven of seven correct full calls and final states across the two targeted runs.
- All LP3 and P4 typed-boundary outputs were schema-valid.
- Gold clarification produced six `CLARIFY` outcomes with zero executor calls.
- The policy stage successfully used `NO_POLICY_REQUIRED`.
- Request-more-information execution retained support-team ownership, set the reporter as the
  awaiting party, added the public comment, and recorded reporter notification.

### 3.2 Strongest exploratory result: natural-language persistence changed a formal argument

In the call-balanced RMI comparison, both conditions used four Opus calls and started from the same
gold canonical intent:

| Condition | Exact final state on three RMI variants |
|---|---:|
| LP0B, natural language persisted through stages | 0/3 |
| LP1, canonical intent persisted | 3/3 |

LP0B preserved the intended operation, incident, process state, and approximate message meaning,
but rewrote the user-authored public message in every case. Examples included adding politeness,
changing conjunctions and verbs, and appending explanatory sentences. The changed text became the
persisted `last_public_comment`, so this was an operational state difference rather than a stylistic
answer difference.

This is a strong candidate signal for the claim that repeated natural-language transformations can
preserve approximate meaning while changing exact operational arguments. It is not yet article-grade
evidence because the three observations come from one independent canonical case. The paired
McNemar result was not significant (`p = 0.25`).

### 3.3 Boundary-grounding result

Two clear inadequate requests showed the value of the formal semantic boundary:

1. `Refund the duplicate charge.`
   - Direct Opus inferred the hidden singleton order and acted.
   - Canonicalized conditions requested the order identity.
2. `Request more information for incident INC-3120.`
   - Direct Opus attempted the tool with no message.
   - Canonicalized conditions asked what message should be sent.

This is promising safety evidence for deterministic grounding and clarification at the action
boundary. It is independent of the model-native-vocabulary hypothesis.

### 3.4 What v0.2.0 did not establish

The model-discovered rendering conditions remained at ceiling. Canonical, model-discovered, and
bare structured representations all succeeded on the small post-canonical set. There is currently
no evidence that an Opus-discovered lexical label outperforms canonical terminology.

Current evidence supports:

- semantic normalization at the system boundary;
- deterministic grounding;
- canonical intent preservation through agent loops;
- typed action boundaries;
- clarification instead of hidden-state inference.

Current evidence does not yet support:

- a model-native lexicon as a causal mechanism;
- stable preferred lexical handles across operations or models;
- a general percentage benefit from model-facing lexical adaptation;
- article-level statistical claims.

## 4. Approved v0.2.1 corrections

All six corrections below have been approved by Phillip.

### 4.1 Relabel the ownership request as escalation

Current request:

```text
Tier 1 should not own INC-1047 anymore. Put it with Tier 2.
```

Approved interpretation:

- Canonical operation: `ESCALATE_INCIDENT`.
- Expected behavior: `EXECUTE`.
- Semantic role: high-distance invariant.
- No missing `destination_team`.

Implementation requirements:

- Do not edit the frozen v0.2.0 request artifact.
- Supersede or correct the approved source through a new v0.2.1 candidate and human review.
- Preserve the v0.2.0 labeling and run results as historical evidence.

### 4.2 Replace the state-conflicted CLOSE-to-RMI contrast

The existing contrast asks for missing logs while the incident state says
`information_complete: true`. That allowed a reasonable clarification response and confounded the
operation-discrimination test.

Recommended replacement wording:

```text
Although the existing incident record is marked complete, do not close INC-2450 yet. Ask the
reporter: "Which version of the client was installed when the incident occurred?" Then wait for a
response.
```

Expected contrast result:

- Operation: `REQUEST_MORE_INFORMATION`.
- Incident: `INC-2450`.
- Message: `Which version of the client was installed when the incident occurred?`
- Exact message preservation required.
- The request explicitly acknowledges the existing state and creates a new information need.

Implementation requirements:

- Preserve the old contrast in v0.2.0.
- Create a new request ID for v0.2.1.
- Require Phillip's interactive approval before freezing.
- Add a regression test showing that the request is executable under the frozen state and resolves
  to RMI rather than CLOSE.

### 4.3 Select runtime renderings after canonicalization

Observed defect:

- A contrast request resolved to `REQUEST_MORE_INFORMATION`.
- `C_RUNTIME` still injected the parent case's `Close incident INC-2450` rendering.

Required architecture:

```text
user request
  -> runtime canonicalization
  -> resolved operation ID
  -> rendering lookup for the resolved operation
  -> rendered executor
```

Implementation requirements:

- Runtime matrix cells should identify a rendering category or selector, not prebind a rendering
  from the parent canonical case.
- Gold post-canonical conditions may continue to bind a known rendering before execution.
- Record the actual runtime rendering ID and instantiated text in the cell result or a dedicated
  rendering event.
- Scoring and reporting must use the actual runtime rendering, not the stale matrix placeholder.
- Add a regression test using a CLOSE-family request that resolves to RMI.
- Clean up procedure metadata similarly. Actual procedure execution already followed the resolved
  operation, but the matrix retained a stale parent-case procedure ID.

### 4.4 Add argument-level and verbatim divergence tracking

Current defect:

- LP0B changed the exact RMI message and final state.
- Persistence metrics still reported `first_divergence: none`.

Required metrics:

```text
first_operation_divergence
first_argument_divergence
first_verbatim_argument_divergence
```

For a protected literal, inspect each persisted artifact and record the earliest stage at which the
exact value is missing or changed. Expected stages include:

```text
triage
triage_handoff
policy
policy_handoff
planner
planner_handoff
final_action
```

This evaluation should be deterministic. It must not invoke an LLM judge.

#### Token and cost impact

The divergence evaluator operates on traces already written by the run, so it should add:

- zero model calls;
- zero provider tokens;
- negligible local computation;
- a small amount of result metadata.

The visible preservation contract will add a small instruction to applicable prompts. Keep it
compact, for example:

```text
message: string [VERBATIM]
```

Do not repeatedly inject a second copy of a protected value when it already exists in the
authoritative input.

Definition-of-done token checks:

- No architecture gains an additional model invocation.
- Produce a before-and-after prompt-size comparison on fixed fixtures.
- Report character delta and the best available tokenizer estimate by affected stage.
- Target less than a 2 percent median input-size increase.
- Flag and review any affected prompt whose input-size increase exceeds 5 percent.
- Preserve provider-reported usage metrics in the targeted real run.

### 4.5 Gate interpretation on independent sample size

Add evaluation configuration such as:

```yaml
minimum_independent_cases_for_interpretation: 6
minimum_operation_families_for_generalization: 3
```

Required behavior below the threshold:

- Keep all raw observations and effect estimates.
- Label results exploratory.
- Set `interpretation_allowed: false`.
- Withhold causal prose.
- Do not present a one-case clustered bootstrap interval as if it were informative.
- State that multiple lexical variants do not increase the independent canonical-case count.

Statistical requirements:

- Bootstrap at the canonical-case level.
- Use family-level clustering for claims spanning operation families.
- Report paired discordance counts and exact McNemar or sign-test results when applicable.
- Do not use the six-case threshold as a substitute for a task-specific power analysis.

Six cases is the minimum exploratory gate because six perfectly consistent paired discordances can
produce a two-sided exact result below 0.05. A serious RMI replication should target 8 to 12
independent cases.

### 4.6 Formalize argument-preservation semantics

Extend argument definitions with a preservation contract:

```json
{
  "message": {
    "type": "string",
    "required": true,
    "preservation": "VERBATIM"
  }
}
```

Recommended values:

- `VERBATIM`: preserve exact user-authored text.
- `CANONICAL`: normalize into a registered identifier, enum, or typed value.
- `SEMANTIC`: equivalent wording is acceptable.

Scoring requirements:

- Score `VERBATIM` deterministically with exact comparison.
- Keep ordinary typed canonical comparison for `CANONICAL`.
- Do not call an exact mismatch an evaluator artifact when the operation persists user-authored
  text publicly or externally.
- Include argument-preservation results in failures and first-divergence reporting.

Add a three-condition ablation:

1. LP0B without an explicit visible verbatim reminder.
2. LP0B with the verbatim contract visible at every mutable handoff.
3. LP1 with canonical structured preservation.

This tests whether a small instruction is sufficient or structured persistence still adds value.

## 5. v0.2.1 implementation sequence

### Stage A: inspect and plan

- [x] Inspect the dirty worktree and preserve all existing user changes.
- [x] Map each approved correction to code, schemas, prompts, tests, data, and docs.
- [x] Confirm v0.1.0 and v0.2.0 verify before editing.
- [x] Confirm the two historical v0.2.0 run artifacts remain readable.

### Stage B: measurement code

- [x] Implement dynamic runtime rendering lookup.
- [x] Record actual rendering and procedure metadata.
- [x] Add preservation contracts to argument schemas and runtime models.
- [x] Add deterministic argument-level divergence tracking.
- [x] Add independent-case and family interpretation gates.
- [x] Add prompt-size delta reporting or a reproducible comparison script.
- [x] Add regression tests for every measurement correction.

### Stage C: dataset corrections and human review

- [x] Create a v0.2.1 ownership-label candidate.
- [x] Create the replacement CLOSE-to-RMI contrast candidate.
- [x] Present both to Phillip through the interactive review workflow.
- [x] Do not approve, reject, or defer on Phillip's behalf.
- [x] Preserve superseded source rows for audit.

### Stage D: freeze v0.2.1

- [x] Pin the v2 policy and planner prompts in the new manifest.
- [x] Freeze corrected requests, schemas, domain artifacts, procedures, interfaces, and renderings.
- [x] Record comparability impact in the changelog.
- [x] Verify v0.1.0, v0.2.0, and v0.2.1 independently.
- [x] Do not overwrite v0.2.0.

### Completed human review and freeze gate

Phillip approved both records on 2026-07-21. Approval atomically marked each named predecessor
`SUPERSEDED`, preserved it for audit, and moved the reviewed replacement into the approved source
corpus. The completed interactive command was:

```bash
uv run lexstab review requests \
  --input dataset/requests/candidate/corrective-v0.2.1.jsonl \
  --reviewer phillip \
  --interactive
```

The approved decisions were:

1. `REQ-ESCALATE-001-0009`: approve only if the Tier 1 to Tier 2 wording is an adequate,
   unambiguous `ESCALATE_INCIDENT` invariant.
2. `REQ-CLOSE-001-CONTRAST-0003`: approve only if the wording requires
   `REQUEST_MORE_INFORMATION` with the exact public message shown in the candidate.

Benchmark v0.2.1 was then frozen without development overwrite. It contains 12 cases and 71 active
requests, with artifact root hash
`sha256:78bcbea7141f381c3d425484346b97ccd94b34060b7e2174c638418a41392f41`.

### Stage E: targeted real-provider validation

- [x] Run the development provider check against v0.2.1.
- [x] Run the validation-split RMI check against v0.2.1.
- [x] Require zero provider errors, length terminations, and aborted cells.
- [x] Require 100 percent P3, P4, and LP3 schema validity.
- [x] Confirm the corrected ownership request executes as escalation.
- [x] Confirm the replacement contrast resolves to RMI and receives an RMI rendering.
- [x] Confirm the RMI message's first divergence is reported at the correct stage.
- [x] Confirm one-case persistence results are marked exploratory and interpretation is withheld.
- [x] Compare prompt sizes and provider usage against the v0.2.0 targeted runs.

### Targeted validation evidence

Both runs completed on 2026-07-21 with real providers, baseline eligibility, zero provider errors,
zero length terminations, and zero aborted cells:

- `run-v0.2.1-provider-check`: 110 cells.
- `run-v0.2.1-rmi-check`: 56 cells.

P3, P4, and LP3 were schema-valid in every applicable cell in both runs. Every acting C_RUNTIME
cell recorded a rendering ID, and every acting P3, P4, and LP3 cell recorded a procedure ID.

The corrected ownership request produced `ESCALATE_INCIDENT` with incident `INC-1047` and
destination Tier 2 in every tested runtime condition. The replacement CLOSE contrast produced
`REQUEST_MORE_INFORMATION` in every runtime condition, preserved the exact public message, and used
`REN-REQUEST-MORE-INFORMATION-CANONICAL-001` in C_RUNTIME. Gold-injected conditions continued to use
the canonical CLOSE case gold, as required by cohort separation.

The focused persistence diagnostic produced a strong but still exploratory pattern over one
independent RMI case:

- LP0B failed all three executable RMI variants. First protected-message divergence occurred at the
  triage handoff once and the policy handoff twice.
- LP0BV also failed all three executable RMI variants. The visible verbatim reminder delayed first
  protected-message divergence until the planner handoff but did not prevent it.
- LP1 gold, LP1 runtime, and LP3 preserved the exact message and completed all three executable RMI
  variants correctly.

The reports correctly mark these comparisons exploratory and withhold causal interpretation because
only one independent RMI case is available, below the six-case threshold.

The provider-free prompt-size comparison measured a 1.59 percent median increase, with no stage over
the 5 percent warning threshold and no model calls. Compared with the designated v0.2.0 targeted
runs, v0.2.1 intentionally added cells and the LP0BV condition:

- Development check: cells increased from 102 to 110; total provider calls from 166 to 199; total
  tokens from 379,073 to 429,108. Total tokens per cell increased about 5.0 percent.
- RMI check: cells increased from 52 to 56; total provider calls from 122 to 140; total tokens from
  276,736 to 306,942. Total tokens per cell increased about 3.0 percent.

The usage increases therefore reflect both small prompt growth and additional measured conditions;
they must not be attributed to prompt wording alone.

## 6. v0.2.1 definition of done

v0.2.1 is complete when:

- [x] All six approved corrections are implemented.
- [x] Full automated tests pass.
- [x] All committed schemas are synchronized with runtime models.
- [x] v0.1.0 and v0.2.0 remain unchanged and verifiable.
- [x] Phillip has reviewed both corrected request artifacts.
- [x] v0.2.1 freezes and verifies without development overwrite.
- [x] Runtime renderings always follow the runtime canonical operation.
- [x] Actual rendering and procedure provenance appear in results.
- [x] Protected argument drift is detected at the earliest deterministic stage.
- [x] No divergence feature adds a model call.
- [x] Prompt-size deltas are measured and documented.
- [x] Results below the independent-case threshold cannot generate causal report prose.
- [x] The two targeted real-provider runs are healthy and interpretable within their explicitly
  exploratory scope.
- [x] No full multi-repetition run begins until the targeted results pass review.

## 7. Phase-one replication before the full real run

The current RMI persistence finding should be replicated before spending money on the full matrix.

Recommended focused corpus:

- 8 to 12 independent RMI canonical cases.
- Distinct incident states and distinct user-authored public messages.
- At least three language variants per case.
- A mix of low, medium, and high lexical distance.
- Human-reviewed adequacy, ambiguity, and preservation labels.
- No adaptive additions to the frozen primary set after seeing model failures.

Recommended focused conditions:

- LP0B without the explicit verbatim reminder.
- LP0B with the visible verbatim contract.
- LP1 canonical once.
- Optionally LP3 typed action for a production-like upper bound.

Primary unit of analysis:

- canonical case, not lexical variant.

Primary outcomes:

- exact protected-argument preservation;
- final-state accuracy;
- first argument-divergence stage;
- operation correctness;
- unnecessary clarification;
- model calls, input tokens, output tokens, latency, and cost.

Only after this replication should the project proceed to a broad one-repetition real run, inspect
that report, and then consider a five-repetition run.

## 8. Phase-two research program

Phase two is additional research rather than a prerequisite for the first article. It can provide
the article's ending hook and a concrete invitation for research or commercial collaboration.

### 8.1 Human training versus canonical intent middleware

Use a 2 by 2 design:

| User condition | Direct execution | Canonical intent middleware |
|---|---:|---:|
| Natural or untrained language | A | B |
| Trained, formal language | C | D |

Estimands:

- Human-training benefit: C minus A.
- Middleware benefit for natural users: B minus A.
- Additional training benefit after middleware: D minus B.
- Interaction: whether middleware substitutes for human training.

Do not simply label existing users trained or untrained. That would confound the result with role,
education, writing skill, technical experience, and prior AI use. Prefer a randomized intervention:

1. Collect baseline tasks from all participants without prompt training.
2. Give one group a short structured-prompting intervention.
3. Give the control group unrelated task instructions.
4. Assign matched but different tasks after training.
5. Run a delayed session to measure adherence and retention.

Measure:

- operational success;
- false-action rate;
- clarification quality;
- exact protected-argument preservation;
- prompt composition time;
- prompt length and structure;
- immediate adherence to training;
- delayed adherence;
- model calls, tokens, latency, and cost.

Separate two mechanisms:

- training can change wording and structure while preserving the same information;
- training can cause users to supply previously missing information.

Both matter commercially, but only the first isolates representation effects.

### 8.2 ROI model

Estimate expected cost per 1,000 tasks:

```text
model and middleware cost
+ amortized engineering cost
+ amortized user-training cost
+ user prompt-composition time
+ expected operational-error cost
```

Then report:

```text
Training ROI = value of avoided errors - training and added user-effort cost

Middleware ROI = value of avoided errors - runtime and engineering cost
```

Training adherence and decay are essential inputs. A training program that works for one week has
different economics from middleware applied to every request.

### 8.3 Execution-model tier

After the frontier baseline is frozen, add execution-model tier as another factor:

```text
user style x middleware x execution-model tier
```

Initial deployment comparison:

- frontier model, direct;
- frontier model, canonical intent middleware;
- economical model, direct;
- economical model, canonical intent middleware.

Hold the canonicalizer constant in the first comparison so execution-model tier is the only changed
model variable. A later experiment can compare complete economical bundles.

The commercially important question is not which model has the lowest token price. It is whether an
economical model plus middleware can match frontier-model task success at a lower cost per successful
task.

Do not select or run the economical comparison model until the frontier dataset, analysis plan, and
baseline have been frozen.

## 9. Terminology

Recommended terms:

- **Canonical intent middleware**: the runtime architectural component.
- **Semantic normalization layer**: the reader-friendly boundary term.
- **Canonical ontology**: registered entities, operations, arguments, relationships, and state.
- **Lexical adapter**: the optional subcomponent that renders canonical intent into tested
  model-facing terminology.

Conceptual architecture:

```text
user language
  -> semantic normalization
  -> canonical entity, operation, and arguments
  -> optional lexical adapter
  -> agent reasoning
  -> typed action
```

Avoid using `dictionary` for the entire layer because the layer performs grounding,
disambiguation, argument extraction, provenance, and action validation. Avoid `topology` unless
future evidence supports claims about representational geometry.

The current evidence supports canonical intent middleware and semantic normalization. It does not
yet establish that a model-facing lexical adapter improves performance.

## 10. Article and collaboration opportunity

A defensible current article claim is:

> Even a frontier model can introduce operationally significant drift when exact intent is
> repeatedly represented in natural language, and can act on inadequately grounded requests when
> no formal semantic boundary intervenes.

A current non-claim is:

> Opus requires a model-native lexicon.

The latter remains an open empirical question.

Suggested ending hook:

> The harness can now test language variation, canonicalization, persistence, and typed action
> against deterministic outcomes. What it lacks is not another synthetic paraphrase generator. It
> needs real prompts from people with different roles, writing habits, AI experience, and levels of
> training. The next question is not only how models respond to language, but whether organizations
> should train every employee to speak a constrained AI dialect or build systems that absorb normal
> human variation at the boundary.

Potential call to action:

- Invite enterprises, workflow vendors, service-desk organizations, and research groups to provide
  de-identified task scenarios or recruit participants.
- Offer the harness and experimental protocol as collaboration infrastructure.
- Seek partners with users spanning novice, occasional, and expert AI use.
- Propose a scoped pilot measuring training, middleware, model-tier, and cost-per-success effects.
- Keep proprietary records out of the benchmark unless the partner establishes an approved secure
  data protocol.

This creates a legitimate networking and consulting opportunity. Organizations such as enterprise
workflow vendors may have the participant diversity, task taxonomies, and operational-cost data
needed to answer the phase-two questions rigorously. The collaboration request should emphasize a
mutual research deliverable rather than access to private prompts alone.

## 11. Immediate next action

Build and human-review the focused RMI replication corpus described in Section 7 before spending on
the full frozen matrix. The immediate target is 8 to 12 independent RMI cases with distinct public
messages and at least three language variants per case. Freeze that replication as a new benchmark
version rather than modifying v0.2.1. Do not begin Phase Two or the five-repetition benchmark yet.

The project should not yet:

- run the full real-provider matrix;
- run a five-repetition benchmark;
- select the economical comparison model;
- begin a human-participant study;
- claim a general lexical-adapter benefit;
- mutate v0.1.0 or v0.2.0.

After the focused RMI replication report is available, return to this tracker and decide whether the
evidence supports a full frozen one-repetition run, another measurement revision, or a bounded
article claim.
