# Cross-Model Persistence Findings and Trajectory Analysis

Status: Frozen analytical addendum to the Opus Phase One evidence record  
Date: 2026-07-22  
Models: `claude-opus-4-8` and `claude-sonnet-5`  
Benchmark: `dataset/manifests/benchmark-v0.3.0.json`

## 1. Analytical question

The focused comparison asks:

> After intent has already been resolved, how reliably do two execution models preserve an exact
> public-message argument through repeated free-form handoffs, and how does that compare with
> keeping canonical state authoritative?

It does not ask whether raw user wording changes model behavior. Every condition begins from gold
canonical intent. The three request rows per canonical case collapse to the same first model input
and function as repeated stochastic executions.

It also does not test whether one model is generally better. It tests whether the benefit of a
particular representation architecture differs by model.

## 2. Run artifacts and compatibility

### Opus

```text
runs/run-v0.3.0-rmi-replication-1x-20260721
```

### Sonnet

```text
runs/run-v0.3.0-sonnet5-rmi-replication-1x-20260722
```

### Formal comparison

```text
runs/model-comparison-opus48-sonnet5-v0.3.0.json
```

### Shared execution facts

- 72 cells per model
- 288 `execution_primary` calls per model
- eight independent canonical cases
- three repeated request rows per case
- one operation family: `REQUEST_MORE_INFORMATION`
- four model calls per cell
- no invoked canonicalizer, adequacy assessor, judge, or other model role
- benchmark root hash:
  `sha256:9db43100507cc31fa1c256cc14888ed61dba0d89cde3b09155167cf74b39d99e`
- matrix hash:
  `sha256:4774655317382ac4812c52fa159d955130919c2a00fd213c8820d2aaf124ffd1`
- shared evaluator source hash:
  `sha256:eef042d624358aee1b0ba4602afb6ea30492d6c9439c1b0d8e8ae11b8dd1e8bf`

Both runs are complete, healthy, baseline-eligible, and free of provider errors, length
terminations, and aborted cells.

### Compatibility warnings

The formal comparison reports three warnings:

1. The configured but unused `adequacy_assessor` roles differ.
2. The configured but unused `boundary_canonicalizer` roles differ.
3. The execution code revision differs.

The first two are non-causal because neither role was invoked. The code-revision audit found no
runner, prompt, provider, graph, procedure, or execution-path difference affecting this matrix.
Frozen prompts, procedures, interfaces, parameters, matrix rows, and evaluation code match.

A publication-grade replication should run both models from one final commit. The existing
comparison remains valid for analysis and research planning.

## 3. Experimental conditions

### LP0B: call-balanced free-form persistence

```text
gold resolved task
  -> triage model call and free-form handoff
  -> policy model call and free-form handoff
  -> planner model call and free-form handoff
  -> final proposal model call
```

Each stage is instructed to preserve supplied arguments, but the prose handoff becomes the
authoritative input to the next stage.

### LP0BV: free-form persistence with visible preservation reminder

LP0BV uses the same four-call architecture but names the protected arguments at every mutable
stage. The prompt says to preserve the `message` field exactly. It does not duplicate the original
literal in a separate authoritative sidecar.

### LP1: canonical once

LP1 resolves canonical intent once and keeps structured canonical state authoritative across all
four calls. Natural-language handoffs do not replace the protected field.

### Protected argument

Every case invokes `REQUEST_MORE_INFORMATION` with:

- `incident_id`, preservation mode `CANONICAL`;
- `message`, preservation mode `VERBATIM`.

The message becomes a public comment and must remain exact. A fluent paraphrase is therefore a
contract failure even when it asks for approximately the same information.

## 4. Headline results

| Condition | Opus exact message and final state | Sonnet exact message and final state |
|---|---:|---:|
| LP0B free-form handoffs | 6/24, 25.0% | 2/24, 8.3% |
| LP0BV free-form plus reminder | 5/24, 20.8% | 12/24, 50.0% |
| LP1 canonical state | 24/24, 100% | 24/24, 100% |

Across the 96 LP0B and LP0BV cells from both models:

- 96 of 96 were schema-valid.
- 96 of 96 selected the correct decision.
- 96 of 96 selected the correct tool.
- 96 of 96 preserved the incident ID.
- zero produced a false action.
- only 25 of 96 preserved the exact public message.

Across the 48 LP1 cells from both models, all 48 preserved the exact public message and correct
final state.

This separates operational interpretation from literal preservation. The language paths usually
understood what action to perform and which incident to update. They failed to keep an application
argument unchanged.

## 5. Within-model effects

### 5.1 Opus

LP1 canonical state minus LP0B prose:

- estimate: +0.750
- case-clustered 95 percent interval: +0.500 to +0.917
- seven independent cases favored LP1
- zero favored LP0B
- one tied
- exact case-level sign test: `p = 0.015625`

LP1 canonical state minus LP0BV reminded prose:

- estimate: +0.792
- interval: +0.542 to +1.000
- seven cases favored LP1
- zero favored LP0BV
- one tied
- exact case-level sign test: `p = 0.015625`

LP0BV reminder minus LP0B prose:

- estimate: -0.042
- interval: -0.208 to +0.208
- one case favored LP0BV
- three favored LP0B
- four tied
- exact case-level sign test: `p = 0.625`

The reminder did not improve Opus final preservation.

### 5.2 Sonnet

LP1 canonical state minus LP0B prose:

- estimate: +0.917
- interval: +0.792 to +1.000
- all eight independent cases favored LP1
- exact case-level sign test: `p = 0.0078125`

LP1 canonical state minus LP0BV reminded prose:

- estimate: +0.500
- interval: +0.208 to +0.792
- five cases favored LP1
- zero favored LP0BV
- three tied
- exact case-level sign test: `p = 0.0625`

LP0BV reminder minus LP0B prose:

- estimate: +0.417
- interval: +0.167 to +0.667
- five cases favored LP0BV
- zero favored LP0B
- three tied
- exact case-level sign test: `p = 0.0625`

The reminder materially improved Sonnet in this small family, although five non-tied cases leave
the case-level directional evidence one step short of a conventional 0.05 threshold.

## 6. Cross-model effects

### Raw condition differences, Sonnet minus Opus

- LP0B prose: -0.167, interval -0.458 to +0.042
- LP0BV reminded prose: +0.292, interval -0.167 to +0.750
- LP1 canonical state: 0.000, interval 0.000 to 0.000

Sonnet was descriptively worse without a reminder, descriptively better with the reminder, and
identical under canonical persistence. Neither raw prose difference supports a general model
ranking.

### Difference in differences: canonical state benefit

```text
(Sonnet LP1 - Sonnet LP0B) - (Opus LP1 - Opus LP0B)
```

- estimate: +0.167
- interval: -0.042 to +0.458
- Sonnet received the larger benefit in three cases
- Opus received the larger benefit in one case
- four cases tied
- exact case-level sign test: `p = 0.625`

The direction suggests that Sonnet may benefit more from canonical persistence, but the interval
includes zero. The supported conclusion is that both models benefited greatly, not that one
benefited more.

### Difference in differences: reminder benefit

```text
(Sonnet LP0BV - Sonnet LP0B) - (Opus LP0BV - Opus LP0B)
```

- estimate: +0.458
- interval: +0.208 to +0.750
- five cases favored a larger Sonnet reminder effect
- zero favored a larger Opus reminder effect
- three tied
- exact case-level sign test: `p = 0.0625`

This is a credible model-by-prompt interaction candidate. It is secondary, limited to eight cases,
and should not be presented as a general Sonnet property.

## 7. Where exact content first changed

The relevant field is `first_verbatim_argument_divergence`, not the generic
`first_divergence_stage`.

### Final-failure trajectories

| Model and condition | Triage first | Policy first | Planner handoff first | Final failures |
|---|---:|---:|---:|---:|
| Opus LP0B | 10 | 7 | 1 | 18 |
| Opus LP0BV | 1 | 9 | 9 | 19 |
| Sonnet LP0B | 20 | 1 | 1 | 22 |
| Sonnet LP0BV | 10 | 1 | 1 | 12 |

### Interpretation

Sonnet usually rewrote the message in the first free-form handoff. The visible reminder prevented
many of those early changes and raised final preservation from 2 of 24 to 12 of 24.

Opus reacted differently. The reminder reduced triage-first failures from 10 to one, but the
message was then rewritten at policy or planning. The reminder delayed drift without improving the
final outcome.

This is why final scoring and trajectory scoring are both necessary. A prompt can alter the path
without improving the delivered result.

## 8. Recovery after divergence

Opus had 43 cells with an intermediate verbatim divergence across the two language conditions.
Six later recovered the exact message, approximately 14 percent:

- LP0B recovery rate: 14.3 percent
- LP0BV recovery rate: 13.6 percent

Sonnet had 34 verbatim-divergent language cells and recovered none.

Recovery does not make free-form persistence reliable. It shows that a later generation can
reconstruct a familiar phrase after an earlier paraphrase, but that reconstruction is stochastic
and case-dependent.

LP1 had no intermediate verbatim divergence in any of its 48 cross-model cells.

## 9. Exact values lost after a structured planner result

Each LP0B or LP0BV stage call returned both:

- a typed diagnostic `stage_result`;
- a free-form `handoff_text` that became the authoritative input to the next stage.

The planner `stage_result` included formal operation arguments. In 15 of the 96 language cells, the
planner's typed result still contained the exact correct message but the final action did not:

| Model and condition | Planner exact, final changed |
|---|---:|
| Opus LP0B | 2/24 |
| Opus LP0BV | 9/24 |
| Sonnet LP0B | 1/24 |
| Sonnet LP0BV | 3/24 |
| Total | 15/96 |

This is one of the clearest architectural findings. The system had the right value, then selected a
prose rendering rather than the typed field as its source of truth.

The visible reminder named the protected field but did not carry the original literal separately.
Once a handoff changed the value, a later instruction to preserve `message` exactly could not tell
the model which earlier wording had been authoritative.

## 10. Failure morphology

The failures were mostly fluent and helpful-sounding. A deterministic, overlapping string-pattern
scan of the 71 final mismatches found:

| Pattern | Opus | Sonnet | Combined |
|---|---:|---:|---:|
| Polite or conversational reframing | 27 | 31 | 58 |
| Added investigation rationale or workflow explanation | 16 | 13 | 29 |
| Literal `.log` filenames changed to ordinary words | 2 | 3 | 5 |
| `can we use` changed to passive `can be used` | 5 | 2 | 7 |
| Reproduction request strengthened with `exact`, `detailed`, or `step-by-step` | 5 | 4 | 9 |
| `change ticket` narrowed to `change ticket number` | 0 | 4 | 4 |
| VPN question made conditional with `if so` | 0 | 1 | 1 |

The categories overlap and are diagnostic, not a replacement for the deterministic verbatim gold
contract.

### Common helpful rewrite

Expected:

```text
What was the exact local time of the failure, including the time zone?
```

Observed:

```text
Could you please provide the exact local time of the failure, including the time zone?
```

The request remains understandable but violates an exact public-comment contract.

### Exact identifier weakened

Expected:

```text
Please attach the application.log and launcher.log files from the affected device.
```

Observed variants included:

```text
Please attach the application log and launcher log files from the affected device.
```

The punctuation is part of the filenames. This is not merely a stylistic change.

### Scope made conditional

Expected:

```text
Were you connected through the corporate VPN, and from which office or network?
```

Observed:

```text
...whether you connected via the corporate VPN, and if so, from which office or network...
```

The added condition may stop the reporter from naming the network when they were not on VPN.

### Actor or authorization nuance removed

Expected:

```text
How many users are affected, and which usernames can we use for testing?
```

Observed:

```text
How many users are affected and which usernames can be used for testing?
```

The passive rewrite removes the explicit testing actor and may weaken an authorization nuance.

### Internal workflow detail leaked into public text

One output appended:

```text
We are pausing this incident to await your response.
```

The harness expected only the approved reporter question. The model converted internal workflow
state into additional user-facing content.

## 11. Case-level heterogeneity

Values are exact successes out of three repeated executions.

| Case | Opus LP0B | Opus LP0BV | Sonnet LP0B | Sonnet LP0BV | Both LP1 |
|---|---:|---:|---:|---:|---:|
| RMI_REP_001 | 3 | 3 | 0 | 0 | 3 each |
| RMI_REP_002 | 0 | 0 | 0 | 0 | 3 each |
| RMI_REP_003 | 1 | 0 | 0 | 1 | 3 each |
| RMI_REP_004 | 1 | 0 | 0 | 0 | 3 each |
| RMI_REP_005 | 0 | 0 | 0 | 3 | 3 each |
| RMI_REP_006 | 1 | 0 | 1 | 3 | 3 each |
| RMI_REP_007 | 0 | 0 | 1 | 3 | 3 each |
| RMI_REP_008 | 0 | 2 | 0 | 2 | 3 each |

Important observations:

- `RMI_REP_002` defeated both prose conditions for both models. Both models consistently converted
  the direct question into a polite request.
- `RMI_REP_001` was perfectly preserved by Opus and never preserved by Sonnet in either prose
  condition.
- Sonnet's reminder was perfect on cases 005, 006, and 007, while Opus's reminder failed every
  execution of those cases.
- Canonical state eliminated all case-level heterogeneity in this benchmark.

The interaction appears tied to both model and sentence form. The data do not identify a mechanism.

## 12. Usage and finish behavior

### Opus

- calls: 288
- prompt tokens: 424,816
- completion tokens: 48,890
- total tokens: 473,706
- mean completion tokens: 169.8
- maximum completion tokens: 333
- p95 completion tokens: 272
- mean latency: 3,376 ms
- p95 latency: 4,978 ms
- all calls finished with `end_turn`

### Sonnet

- calls: 288
- prompt tokens: 422,115
- completion tokens: 62,783
- total tokens: 484,898
- mean completion tokens: 218.0
- maximum completion tokens: 727
- p95 completion tokens: 434
- mean latency: 3,592 ms
- p95 latency: 6,357 ms
- all calls finished with `end_turn`

The shared 1,024-token execution budget was sufficient. No result is explained by truncation.

## 13. Reporting caveats discovered during analysis

### 13.1 Misnamed case-level file

`comparison-results/case-level-cross-model-v0.3.json` contains TSV text. It should be renamed to a
`.tsv` extension or regenerated as actual JSON before other tooling consumes it.

### 13.2 First-divergence summaries are not failure-only

The generated `failure-first-divergence-stages` tables aggregate the generic
`first_divergence_stage`. They may include:

- cells that diverged and later recovered;
- entity-representation divergence even when the exact message remained correct.

This explains why the table totals do not equal the final failure counts of 37 for Opus and 34 for
Sonnet.

For exact-message failure analysis use:

- `verbatim_arguments_correct == false`;
- `metadata.first_verbatim_argument_divergence`;
- each run's `failed-trajectories.json`.

The harness should eventually give these tables more precise names or add a final-failure-only
variant.

## 14. Strongest supported interpretation

> The two models generally preserved application-level intent while editing its lexical payload.
> Free-form handoffs treated the public message as material to summarize, clarify, or improve.
> Canonical state marked it as an authoritative value to carry. The architecture changed what the
> model was permitted to reinterpret.

This result is closer to a typed-data argument than a vocabulary-preference argument. It shows
that natural language can be an inferential representation even after the requested action is
known.

## 15. Supported article claims

Safe with explicit scope:

- Models do not receive intentions directly. They receive representations produced by users,
  interfaces, and prior model calls.
- A model may preserve operational meaning while changing an exact application value.
- Helpful rewriting is a real failure mode when the field contract is literal.
- In the tested multi-call workflow, canonical authoritative state prevented exact-message drift
  for both a frontier model and a less expensive comparison model.
- Prompt reminders were model-dependent and less reliable than retaining the authoritative value.
- Language can remain flexible at the interface while exact application arguments require formal
  preservation before action.

## 16. Claims this comparison does not support

- Sonnet generally needs middleware more than Opus.
- Opus generally follows preservation instructions worse than Sonnet.
- The reminder effect will transfer to other tasks or prompt wording.
- Canonical ontology is always necessary for any multi-agent workflow.
- Every paraphrase is operationally significant.
- User-language variants caused these failures.
- A lexical adapter improves post-canonical reasoning.
- The models share or differ in a known internal mechanism.

## 17. Bottom line

The comparison supplies a real, replicated, bounded signal:

> Across two models, the same exact argument was unreliable when repeatedly carried through
> model-authored prose and perfectly reliable when retained as authoritative canonical state.

The next experiment should isolate whether the full canonical representation is necessary or
whether a smaller protected-literal sidecar is sufficient. That plan is specified in
`docs/NEXT_RESEARCH_PROGRAM.md`.
