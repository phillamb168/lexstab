# Model-tier comparison protocol

This protocol compares the focused v0.3.0 persistence replication across execution models while
changing only the `execution_primary` model. It is provider-free until the operator reaches the
explicit health-check and frozen-run commands in section 5.

The first planned comparison is:

- baseline execution model: `claude-opus-4-8`;
- comparison execution model: `claude-sonnet-5`;
- benchmark: frozen `benchmark-v0.3.0.json`;
- primary operation family: `REQUEST_MORE_INFORMATION`;
- conditions: LP0B, LP0BV, and LP1;
- calls per cell: four in every condition;
- cells in the full run: 72;
- estimated execution calls in the full run: 288.

Anthropic documents `claude-sonnet-5` as the fixed Sonnet 5 API model ID. The initial comparison
preserves the existing 1,024-token response budget and does not add sampling or thinking controls.
That keeps the harness request parameters matched to the Opus run. If the health check reaches the
length limit, stop and treat response-budget selection as a new preregistered factor rather than
silently changing the full run.

Official model references:

- <https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5>
- <https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions>

## 1. Question and estimands

The model-tier question is not simply whether Sonnet has lower raw accuracy than Opus. The primary
question is whether canonical-state persistence changes each model's results by a different amount.

For each model, calculate these paired benefits:

1. `LP1 - LP0B`: canonical state versus call-balanced prose;
2. `LP1 - LP0BV`: canonical state versus call-balanced prose with a visible exactness reminder;
3. `LP0BV - LP0B`: reminder benefit within natural-language persistence.

Then calculate the cross-model difference in differences:

```text
(Sonnet structured benefit) - (Opus structured benefit)
```

A positive LP1 difference in differences means Sonnet benefits more from canonical-state
persistence than Opus. A value near zero means the tested architecture benefit is similar for both
models. A negative value means Opus benefits more.

Primary outcome:

- exact protected argument preservation and resulting final-state correctness.

Secondary outcomes:

- each condition's raw final-state and verbatim-preservation accuracy;
- first-divergence stage and recovery behavior;
- output-token use, finish reasons, and latency;
- condition-level raw model accuracy differences.

The canonical case remains the independent resampling unit. The three request rows per case do not
count as three independent cases.

## 2. Compatibility gate

`lexstab compare-runs` refuses a cross-model persistence comparison unless all runs have:

- the same benchmark root hash;
- the same matrix hash and exact matrix rows;
- the same seed and frozen run clock;
- the same prompt, procedure, and interface hashes;
- the same configuration and invocation counts for every role actually used by the run;
- complete, healthy, evaluated artifacts;
- the same evaluation-harness source hash.

The execution model ID and response statistics may differ. The execution provider and parameters,
including `max_tokens`, must remain identical. Configuration differences for roles that were not
invoked in either run are recorded as non-causal warnings rather than blocking the comparison. A
code-revision difference is also reported as a warning when the frozen execution inputs still
match. Before publication, rerunning both models from one code revision is preferable.

Re-evaluate the stored Opus run after the comparison implementation is finalized. Evaluation is
provider-free and makes the evaluator source hash match the future Sonnet evaluation.

## 3. Why this matrix is the first comparison

The v0.3.0 matrix isolates a known persistence mechanism using eight independent cases and three
language-distance variants per case. Every condition begins from gold canonical intent. Source
wording is therefore not an active input factor in this experiment. The comparison tests whether
repeated natural-language handoffs preserve exact action content differently across model tiers.

This run can establish a cross-model replication inside one operation family. It cannot establish:

- all-operation generality;
- a model-native vocabulary advantage;
- the value of user training;
- the effect of raw user-language variation;
- a complete cost-per-success business case.

Those remain later experiments.

## 4. Provider-free preparation

Run these after committing the harness changes and before making any Sonnet calls:

```bash
uv run pytest -q

uv run lexstab benchmark verify \
  --manifest dataset/manifests/benchmark-v0.3.0.json

uv run lexstab evaluate \
  --run runs/run-v0.3.0-rmi-replication-1x-20260721 \
  --config config/run.v0.3.0-rmi-replication-1x.yaml

EXECUTION_MODEL_ID=claude-sonnet-5 uv run lexstab doctor \
  --models config/models.local.yaml \
  --run config/run.v0.3.0-model-comparison-health.yaml

EXECUTION_MODEL_ID=claude-sonnet-5 uv run lexstab run \
  --config config/run.v0.3.0-model-comparison-health.yaml \
  --dry-run
```

The health dry run should report 18 matrix cells and 72 estimated execution-model calls. The full
dry run should report 72 cells and 288 calls:

```bash
EXECUTION_MODEL_ID=claude-sonnet-5 uv run lexstab run \
  --config config/run.v0.3.0-rmi-replication-1x.yaml \
  --dry-run
```

Shell environment variables take precedence over values loaded from `.env`, so the inline model ID
changes the execution model without editing `models.local.yaml`.

## 5. Paid provider sequence

The operator, not an automated test, runs these commands.

### 5.1 Health check

```bash
EXECUTION_MODEL_ID=claude-sonnet-5 uv run lexstab run \
  --config config/run.v0.3.0-model-comparison-health.yaml \
  --run-id run-v0.3.0-sonnet5-health-20260721

jq '{status,healthy,baseline_eligible,provider_error_calls,length_terminated_calls,aborted_cells}' \
  runs/run-v0.3.0-sonnet5-health-20260721/run-summary.json
```

Continue only if the run is complete and healthy with zero provider errors, length terminations,
and aborted cells. Evaluate and inspect the health run before paying for the full matrix:

```bash
uv run lexstab evaluate \
  --run runs/run-v0.3.0-sonnet5-health-20260721 \
  --config config/run.v0.3.0-model-comparison-health.yaml

uv run lexstab report \
  --run runs/run-v0.3.0-sonnet5-health-20260721 \
  --formats markdown,html,csv,parquet,json
```

### 5.2 Full frozen matrix

```bash
EXECUTION_MODEL_ID=claude-sonnet-5 uv run lexstab run \
  --config config/run.v0.3.0-rmi-replication-1x.yaml \
  --run-id run-v0.3.0-sonnet5-rmi-replication-1x-20260721

jq '{status,healthy,baseline_eligible,provider_error_calls,length_terminated_calls,aborted_cells}' \
  runs/run-v0.3.0-sonnet5-rmi-replication-1x-20260721/run-summary.json

uv run lexstab evaluate \
  --run runs/run-v0.3.0-sonnet5-rmi-replication-1x-20260721 \
  --config config/run.v0.3.0-rmi-replication-1x.yaml

uv run lexstab report \
  --run runs/run-v0.3.0-sonnet5-rmi-replication-1x-20260721 \
  --formats markdown,html,csv,parquet,json
```

Do not change `max_tokens`, prompts, procedures, interfaces, seed, run clock, selected cases, or
request IDs between models. If the provider run fails, retain the artifacts and diagnose the
failure. Do not splice a partial health run into the frozen comparison.

## 6. Provider-free cross-model analysis

After both evaluated runs are complete:

```bash
uv run lexstab compare-runs \
  --runs runs/run-v0.3.0-rmi-replication-1x-20260721,runs/run-v0.3.0-sonnet5-rmi-replication-1x-20260721 \
  --baseline-model claude-opus-4-8 \
  --bootstrap-samples 2000 \
  --output runs/model-comparison-opus48-sonnet5-v0.3.0.json
```

Read the result in this order:

1. `compatibility`: must say `compatible: true`; read every warning.
2. `models.<id>.persistence.conditions`: each model's raw LP0B, LP0BV, and LP1 intervals.
3. `models.<id>.persistence.within_model_benefits`: each model's paired architecture effects.
4. `pairwise_persistence.*.difference_in_differences`: the primary cross-model result.
5. `case_level_sign_test`: count independent cases favoring each model, not request rows.
6. `execution_usage`: compare calls, tokens, finish reasons, and latency.

Do not interpret a lower raw Sonnet score by itself as proof that middleware is more valuable for
Sonnet. That requires a larger Sonnet LP1-minus-prose benefit than the corresponding Opus benefit.

## 7. Decision after one repetition

The one-repetition comparison is the first real signal, not a final model ranking. Continue only if:

- both runs are compatible and healthy;
- the protected-message outcome is measured identically;
- no length termination or provider artifact explains the difference;
- the direction of the difference in differences is interpretable across the eight cases.

If the result is interesting, preregister a higher-repetition comparison before running it. If the
result is weak or heterogeneous, inspect case-level divergence patterns before spending more. Do
not expand to the broad v0.2.1 matrix until this focused mechanism test is understood.
