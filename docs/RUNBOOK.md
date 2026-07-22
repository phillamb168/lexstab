# Operator runbook

This runbook follows the command sequence of spec §42 (installation and configuration runbook) and
covers the operator tasks required by spec §49.13: installation, credentials, exact model IDs,
execution versus evaluation roles, cost estimation, smoke runs, full runs, specialized tracks,
evaluation, reporting, judging, red teaming, regression, recovery, LangSmith, and diagnostics.

All commands below are run from the repository root. `uv` is expected on `PATH`
(`export PATH="$HOME/.local/bin:$PATH"` if needed).

## 1. Installation (spec §42.1–42.2)

Prerequisites: Python 3.12 or later (developed on 3.13; D-002), `uv`, and provider API credentials
for the roles you intend to run. LangSmith is optional.

```bash
uv sync --frozen
cp .env.example .env
cp config/models.example.yaml config/models.local.yaml
cp config/run.example.yaml config/run.local.yaml
```

`uv.lock` is committed and CI installs with `--frozen` (D-021). The mocked configuration
(`config/models.mock.yaml`, `config/run.smoke.yaml`) requires no credentials.

## 2. Credentials and exact model IDs (spec §19.3–19.4)

Fill `.env`. Every value is read from the environment; secrets never go in YAML, `.env` is
git-ignored, and the harness never logs credential values (spec §19.3).

Credentials:

```dotenv
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
OPENROUTER_API_KEY=
```

Exact provider model identifiers — one per role, referenced from `config/models.local.yaml` as
`${VAR}`:

```dotenv
EXECUTION_MODEL_ID=
COMPARISON_MODEL_ID=
CANONICALIZER_MODEL_ID=
ADEQUACY_ASSESSOR_MODEL_ID=
MEMORY_RETRIEVER_MODEL_ID=
PROCEDURE_ROUTER_MODEL_ID=
AUTHORING_GENERATOR_MODEL_ID=
EQUIVALENCE_CRITIC_MODEL_ID=
ADVERSARIAL_CRITIC_MODEL_ID=
EVALUATION_JUDGE_MODEL_ID=
FAILURE_ANALYST_MODEL_ID=
```

Optional LangSmith and storage settings:

```dotenv
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=lexstab-local
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LEXSTAB_RUNS_DIR=./runs
LEXSTAB_CODE_SANDBOX_RUNTIME=docker
LEXSTAB_CODE_SANDBOX_IMAGE=python:3.13-alpine
```

**Model IDs must be exact provider identifiers, never marketing aliases** ("Opus", "GPT", "latest")
and never floating tags for publication-grade runs (spec §19, §19.4). The run manifest records the
resolved ID, parameters, adapter versions, and timestamps for every role, because hosted models can
change behavior behind a stable alias (spec §46.13).

## 3. Execution versus evaluation roles (spec §19.1)

Model configuration is role-based. The load-bearing separation: **models that execute the benchmark
must not author its data or score their own output**, and a run fails before execution if the
separation policy is violated (spec §9.4), unless `allow_role_overlap` is explicitly set and
recorded as a research override. Summary of the §19.1 role table:

| Role | Purpose | Sees benchmark gold? | Mutates artifacts? | Scores MUT output? |
|---|---|---|---|---|
| `execution_primary` | Primary model under test (MUT) | only what the execution prompt shows | no | no |
| `execution_comparison` | Optional comparison MUT | same as primary | no | no |
| `boundary_canonicalizer` | Runtime mapping in B-Runtime / C-Runtime | ontology, not per-request gold | no | no |
| `adequacy_assessor` | Runtime adequacy/ambiguity gate (intent track) | domain + context, not gold | no | no |
| `memory_retriever` | Memory-ablation retrieval | frozen retrieval corpus | no | no |
| `procedure_router` | Optional runtime procedure selection | intent + registry, not gold selection | no | no |
| `authoring_generator` | Synthetic request creation | canonical case, during authoring only | candidates only | no |
| `authoring_equivalence_critic` | Candidate semantic review | case + candidate | judgments only | no |
| `authoring_adversarial_critic` | Challenge candidate equivalence | case + prior judgment | judgments only | no |
| `evaluation_judge` | Optional non-deterministic scoring | rubric as needed | no | yes, blinded |
| `failure_analyst` | Cluster and explain failures | aggregated run data | hypotheses only | no final authority |

The primary evaluator is deterministic code plus the state simulator; the judge is optional,
blinded, and gated (see step 11). Evaluation (`lexstab evaluate`) requires **no** model access at
all.

Only roles reachable from the selected tracks must resolve. A required role with a missing model
ID fails configuration before the first invocation. If any invoked role uses the mock provider,
the entire run is marked `mocked: true` and cannot become a baseline.

## 4. Verify configuration: `lexstab doctor` (spec §42.3)

```bash
uv run lexstab doctor --models config/models.local.yaml --run config/run.local.yaml
```

Checks: model config loads, role-separation policy passes, model IDs resolve from the environment,
the run config and its benchmark manifest exist, committed schemas match the models, prompt
templates validate, the runs directory is writable, and LangSmith settings are consistent when
tracing is enabled. Add `--ping` to also send one minimal non-benchmark request per configured real
provider to verify credentials (the diagnostic never uses benchmark prompts, per §42.3):

```bash
uv run lexstab doctor --models config/models.local.yaml --run config/run.local.yaml --ping
```

Without flags, `doctor` checks the mocked configuration (`config/models.mock.yaml`,
`config/run.smoke.yaml`).

## 5. Validate domain and artifacts (spec §42.4)

```bash
uv run lexstab schema validate --all
uv run lexstab domain validate --root dataset/domain
uv run lexstab cases validate --root dataset/cases/support
uv run lexstab requests validate --root dataset/requests/frozen
uv run lexstab contexts validate --root dataset/contexts/frozen
uv run lexstab renderings validate --root dataset/renderings/frozen
uv run lexstab memory validate --root dataset/memory
uv run lexstab procedures validate --root dataset/procedures/frozen
uv run lexstab interfaces validate --root dataset/interfaces
uv run lexstab integrity
```

For the corrected `v0.2.0` source artifacts, validate the manifest inputs explicitly:

```bash
uv run lexstab domain validate --root dataset/domain/v0.2.0
uv run lexstab cases validate \
  --root dataset/cases/support-v0.2.0 \
  --domain-root dataset/domain/v0.2.0
uv run lexstab interfaces compare \
  --domain-root dataset/domain/v0.2.0 \
  --generic dataset/interfaces/v0.2.0/generic-action-proposal.json \
  --typed dataset/interfaces/v0.2.0/typed-tools/support.jsonl
uv run lexstab integrity \
  --domain-root dataset/domain/v0.2.0 \
  --cases-root dataset/cases/support-v0.2.0 \
  --interfaces-root dataset/interfaces/v0.2.0
```

The versioned source paths prevent a corrected ontology or gold case from changing files hashed by
the historical `v0.1.0` manifest. The benchmark loader verifies and loads the paths declared by
each manifest.

`lexstab integrity` runs the full referential-integrity sweep over approved artifacts. Dataset
construction and freezing (spec §42.5–42.10) are covered in `docs/DATASET_AUTHORING.md` and
`docs/PROCEDURES_AND_INTERFACES.md`.

## 6. Cost estimation: dry run (spec §42.11)

Dry-run mode assembles prompts, validates tools, expands the matrix, and estimates calls and cost
without invoking any provider:

```bash
uv run lexstab run \
  --config config/run.local.yaml \
  --split development \
  --limit-cases 2 \
  --repetitions 1 \
  --dry-run
```

The JSON output includes `matrix_cells`, `cells_by_track`, `estimated_model_calls`,
`estimated_cost_usd_at_placeholder_rate`, skipped combinations, the matrix hash, and the resolved
execution model. The dollar figure uses a flat placeholder rate ($0.01/call) for planning only —
real cost accounting comes from provider usage in the run traces. When the
progressive-formalization track is enabled, the dry-run additionally lists procedure and interface
hashes, which conditions use runtime versus gold canonical intent, and the estimated marginal call
delta per P-transition (spec §42.14).

## 7. Smoke runs (spec §42.12, §17.4)

Fully mocked, no credentials (the frozen starter benchmark ships in the repo):

```bash
uv run lexstab run --config config/run.smoke.yaml
```

Against real providers, small and cheap:

```bash
uv run lexstab run \
  --config config/run.local.yaml \
  --split development \
  --limit-cases 5 \
  --repetitions 1
```

Smoke results are never reported as evidence for or against any hypothesis (spec §17.4). Mocked
runs are additionally stamped `mocked: true`, `baseline_eligible: false` (D-009).

## 8. Full frozen run (spec §42.13)

```bash
uv run lexstab run \
  --config config/run.local.yaml \
  --split test \
  --repetitions 5
```

On completion the command prints the run ID, benchmark hash, matrix cell count, mocked and
baseline-eligibility flags, and resolved execution model ID. Useful options:

- `--run-id <name>` — choose the run directory name.
- `--runner graph|procedural` — LangGraph or the procedural baseline runner; both execute
  identical node functions (D-008). Default: `procedural`.
- `--manifest <path>` overrides the frozen benchmark or promoted regression-suite manifest.

`semantic_retries` is pinned to 0 for all primary conditions; failed JSON parses are recorded and
scored incorrect, never re-prompted (spec §7.11; D-018).

## 9. Specialized experimental tracks (spec §42.14)

`--track <name>` enables exactly that track from the run config and disables the others. Track
names match the `tracks:` keys in `config/run.example.yaml`: `boundary`, `intent_elicitation`,
`memory_ablation`, `progressive_formalization`, `post_canonical`, `agent_loop`.

Intent-elicitation track alone:

```bash
uv run lexstab run \
  --config config/run.local.yaml \
  --track intent_elicitation \
  --split test \
  --repetitions 5
```

Semantic-memory ablations (only when the frozen memory corpus is configured):

```bash
uv run lexstab run \
  --config config/run.local.yaml \
  --track memory_ablation \
  --split test \
  --repetitions 5
```

Progressive formalization and language persistence, selecting conditions explicitly with
`--conditions` (P… entries populate `conditions`, LP… entries populate `persistence_conditions`):

```bash
uv run lexstab run \
  --config config/run.local.yaml \
  --track progressive_formalization \
  --conditions P0_RAW_PROPOSAL,P1_CLARIFY_PROPOSAL,P2_CANONICAL_PROPOSAL,P3_CANONICAL_PROCEDURE_PROPOSAL,P4_CANONICAL_PROCEDURE_TOOL,LP0_LANGUAGE_THROUGHOUT,LP0G_GOLD_START_LANGUAGE,LP1_CANONICAL_ONCE,LP2_CANONICAL_PROCEDURE,LP3_CANONICAL_PROCEDURE_TOOL \
  --split test \
  --repetitions 5
```

## 10. Evaluate and rescore without model access (spec §42.15)

Evaluation reads only stored run artifacts plus the frozen benchmark. It never invokes an
execution model, so it can be re-run at any time (evaluator fixes, different bootstrap settings)
without provider credentials or cost:

```bash
uv run lexstab evaluate --run runs/<run_id> --config config/run.local.yaml
```

`--config` supplies `evaluation.bootstrap_samples`; `--bootstrap-samples <n>` overrides directly.
Output: `runs/<run_id>/scores.jsonl` and `runs/<run_id>/metrics.json`. Evaluation verifies the
benchmark root hash recorded in the run manifest against the current frozen artifacts and aborts on
mismatch.

## 11. Reports and the optional judge pass (spec §42.16, §35.3)

```bash
uv run lexstab report --run runs/<run_id> --formats markdown,html,csv,parquet
```

Default formats are `markdown,html,csv,parquet,json`. Outputs land under `runs/<run_id>/`
(`report.md`, `report.html`, `tables/`, `charts/`). How to read them is `docs/RESULTS_GUIDE.md`.

Optional blinded LLM-judge pass over clarification questions:

```bash
uv run lexstab judge --run runs/<run_id> --models config/models.local.yaml --limit 50
```

Judge scores are labeled `exploratory` and excluded from headline metrics unless a calibration
record `runs/<run_id>/judge-calibration.json` with at least two human raters and paraphrase
robustness stats exists; the gate is enforced in reporting code (spec §35.5, §49.9; D-016).

## 12. Adaptive red team (spec §42.17, §17.2)

Run only after the frozen results exist:

```bash
uv run lexstab redteam \
  --run runs/<run_id> \
  --models config/models.local.yaml \
  --max-candidates 200 \
  --output dataset/requests/candidate/redteam-<run_id>.jsonl
```

The command prints the required warning: red-team candidates are exploratory, enter only the
candidate corpus for the *next* benchmark version after validation and human review, and never
alter the frozen run's results. A `redteam-report.json` summary is written into the run directory;
the frozen scores are untouched.

## 13. Regression promote and verify (spec §42.18, §45.5)

Promote human-approved red-team failures into a new versioned regression suite (promotion always
creates a new version and records provenance to the discovering run):

```bash
uv run lexstab regression promote \
  --version 0.2.0 \
  --request-ids REQ-ESCALATE-001-RT-0001 \
  --corpus dataset/requests/candidate/redteam-<run_id>.jsonl \
  --run-id <run_id> \
  --reason "reproducible false action on idiomatic variant" \
  --approved-by phillip

uv run lexstab regression verify --version 0.2.0
```

Only requests whose candidate record carries an approving reviewer decision can be promoted. A
regression-suite manifest is a verified overlay on its pinned base benchmark. It replaces only the
request stimuli and reuses the base ontology, cases, contexts, procedures, interfaces, renderings,
and prompts. Run it with fewer repetitions as is normal for CI:

```bash
uv run pytest tests/regression
uv run lexstab run \
  --config config/run.local.yaml \
  --manifest dataset/manifests/regression-v0.2.0.json \
  --repetitions 3
uv run lexstab evaluate --run runs/<run_id>
uv run lexstab regression check \
  --run runs/<run_id> \
  --thresholds config/thresholds.example.yaml
```

The check writes `threshold-check.json` and exits nonzero when a blocking gate fails. Narrow runs
report specialized gates as skipped when their selected tracks do not produce the relevant metric.

## 14. Recovery guidance

Runs are append-only and each run gets a fresh directory:

- Every completed matrix cell is appended to `runs/<id>/cell-results.jsonl` (and its invocations,
  ledger, and simulator events to their JSONL files) as soon as it finishes. **A failed or
  interrupted run keeps every completed cell**; a cell that raised is recorded with an
  `error_category` rather than dropped (spec §39.11 — never drop failed cells silently).
- The run manifest is written before execution and made read-only after the first invocation
  (spec §21.2). Run directories are never reused: re-running creates a new run directory with a
  new run ID. There is no in-place resume; treat a partial run as data.
- `lexstab evaluate` works on partial runs. It compares `matrix.jsonl` against scored cells and
  reports `missing_cells` and a `completion` rate in `metrics.json`; thresholds can be configured
  to block on missing cells (spec §45.3).
- Frozen artifacts are hash-verified before every use and are read-only on disk (D-007). If
  evaluation aborts with a benchmark root-hash mismatch, the dataset changed after the run: do not
  edit frozen files — freeze a new benchmark version and re-run.
- Transport failures stay in the reliability denominator; behavioral accuracy excluding them is a
  separately labeled analysis (spec §39.11).

### 14.1 Whole-track response-budget repair

When a broad run completed its matrix but failed health because one complete track contained
response-limit terminations, do not repeat the entire matrix and do not splice selected failed
cells. Rerun the complete affected track in a fresh run directory, then compose only after the
repair is healthy.

Example repair run:

```bash
uv run lexstab run \
  --config config/run.v0.2.1-elicitation-repair.yaml \
  --track intent_elicitation \
  --run-id run-v0.2.1-elicitation-repair-20260721

jq '{status,healthy,baseline_eligible,provider_error_calls,length_terminated_calls,aborted_cells}' \
  runs/run-v0.2.1-elicitation-repair-20260721/run-summary.json
```

Require `healthy: true` and zero provider errors, length terminations, and aborted cells. Then create
a new provider-free composite:

```bash
uv run lexstab compose-track-repair \
  --base-run runs/run-v0.2.1-frozen-1x-20260721 \
  --replacement-run runs/run-v0.2.1-elicitation-repair-20260721 \
  --output-run-id run-v0.2.1-phase-one-composite-20260721 \
  --tracks intent_elicitation

uv run lexstab evaluate \
  --run runs/run-v0.2.1-phase-one-composite-20260721

uv run lexstab report \
  --run runs/run-v0.2.1-phase-one-composite-20260721 \
  --formats markdown,html,csv,parquet,json
```

The command rejects a partial track, changed benchmark, changed code revision, changed prompts,
changed model or provider, changed sampling parameter, lower response budget, or unhealthy repair.
Only an increased `max_tokens` budget is permitted. It writes `composition-provenance.json` and a
visible report disclosure. Both source runs remain unchanged.

This is a provenance-linked composite, not one uniform provider execution. Interpret each exact
track and cohort under its recorded response budget.

## 15. LangSmith enablement (spec §23.4; D-015)

Local JSONL traces are always the source of truth; LangSmith is an optional mirror. Enable it by
setting in `.env`:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<key>
LANGSMITH_PROJECT=lexstab-local
```

and installing the `langsmith` package. `lexstab doctor` flags inconsistent settings. Mirror a
stored run:

```bash
uv run lexstab langsmith-export --run runs/<run_id> --project lexstab-local
```

The export attaches the §23.4 metadata (benchmark hash, run ID, case/request/rendering/procedure/
interface IDs, architecture, track, model, repetition, condition). Everything degrades to a no-op
when tracing is disabled; the harness fully works without LangSmith.

## 16. Auxiliary experiment commands

Experiments 4, 5, and 7 (grammar terminology, code identifiers, input modality) have separate
entry points with mocked defaults (D-014):

```bash
uv run lexstab experiment grammar --dataset dataset/grammar/editing-corpus.jsonl --condition definition_only
uv run lexstab experiment code --dataset dataset/code/families.jsonl
uv run lexstab experiment modality --dataset dataset/modality/artifact-chains.jsonl
```

Each accepts `--models` and `--output`; shipped datasets are minimal demonstrations, and
research-grade corpora are operator work (see `IMPLEMENTATION_STATUS.md`).

The code experiment never executes real model output directly on the host. It uses the configured
container runtime with no network, a read-only filesystem, dropped capabilities, resource limits,
and an unprivileged user. If the runtime is unavailable, the experiment records a sandbox error
and does not execute the candidate. Local execution exists only for repository-owned deterministic
mock fixtures used by offline tests.

## 17. Corrected `v0.2.0` release and validation sequence

The corrective release preserves `v0.1.0`, its frozen artifacts, and all historical run outputs.
Do not use `--dev-overwrite` against `v0.1.0`.

### 17.1 Human review gates

First inspect and review the corrected request labels. The original ownership wording becomes a
clarification case; the explicit tier-transition wording becomes its invariant replacement.

```bash
uv run lexstab review requests \
  --input dataset/requests/candidate/corrective-v0.2.0.jsonl \
  --reviewer phillip \
  --interactive
```

Then generate all eight model-discovered operation renderings. This is 400 fresh Opus calls when
`execution_primary` is configured as the pinned Opus model.

```bash
uv run lexstab discover renderings \
  --operations ESCALATE_INCIDENT,REASSIGN_INCIDENT,CLOSE_INCIDENT,REQUEST_MORE_INFORMATION,REQUEST_APPROVAL,REFUND_DUPLICATE_CHARGE,REQUEST_MANAGER_REVIEW,SUSPEND_ACCOUNT \
  --execution-model-role execution_primary \
  --samples 50 \
  --models config/models.local.yaml \
  --output dataset/renderings/candidate/discovery-opus-v0.2.0.jsonl
```

The discovery command requests provider-enforced JSON structured output and checkpoints every
sample immediately beside the candidate file as `discovery-opus-v0.2.0.samples.jsonl`. It also
writes `discovery-opus-v0.2.0.summary.json`. If the command is interrupted, repeat the same command
to resume. Previously completed compatible samples are reused. Do not delete the sample checkpoint
until discovery and human review are complete.

The checkpoint is append-only. A retried sample retains both its failed and successful provider
attempts, so `wc -l` can exceed 400. The completed experiment requires 400 unique sample keys and
400 effective valid responses, not exactly 400 physical checkpoint lines. The summary records both
figures under `checkpoint_audit`.

If discovery reports five consecutive invalid structured responses for an operation, it stops that
operation and preserves the responses for diagnosis. Provider failures stop the command immediately
after the failed response is recorded. Neither failure mode silently substitutes a semantic retry.

Stop and inspect the eight candidates before approval. The review command records the human
reviewer and supersedes prior active discovered renderings for the same operation.

```bash
uv run lexstab review renderings \
  --input dataset/renderings/candidate/discovery-opus-v0.2.0.jsonl \
  --reviewer phillip \
  --interactive
```

The interactive review approves, rejects, or defers each operation independently. Approved and
rejected rows leave the candidate file; deferred rows remain for later review. Batch approval is
still available through `--decision APPROVE`, but should only be used after every remaining row has
already been inspected.

The first RMI discovery identified a waiting-state label rather than the outbound action and was
rejected. Before rediscovering that one operation, review the corrected request corpus:

```bash
uv run lexstab review requests \
  --input dataset/requests/candidate/rmi-contract-v0.2.0.jsonl \
  --reviewer phillip \
  --interactive
```

The corrected contract keeps the current support team and tier, requires an explicit public
reporter message, marks the incident as awaiting its original reporter, and records a reporter
notification. A request that identifies the incident and operation but omits the message must
clarify. After approving the request candidates, run only the revised 50-call discovery:

```bash
uv run lexstab discover renderings \
  --operations REQUEST_MORE_INFORMATION \
  --execution-model-role execution_primary \
  --samples 50 \
  --models config/models.local.yaml \
  --domain-root dataset/domain/v0.2.0 \
  --output dataset/renderings/candidate/discovery-opus-v0.2.0-rmi-corrected.jsonl

uv run lexstab review renderings \
  --input dataset/renderings/candidate/discovery-opus-v0.2.0-rmi-corrected.jsonl \
  --reviewer phillip \
  --domain-root dataset/domain/v0.2.0 \
  --cases-root dataset/cases/support-v0.2.0 \
  --interactive
```

The original 50 RMI samples and rejected `await-info` rendering remain as audit evidence. Do not
reuse their checkpoint for the corrected discovery card.

### 17.2 Freeze and verify

```bash
uv run lexstab benchmark freeze \
  --version 0.2.0 \
  --changelog-file dataset/manifests/changelog-v0.2.0.json

uv run lexstab benchmark verify \
  --manifest dataset/manifests/benchmark-v0.2.0.json
```

The corrected freeze rejects any mock-derived discovered rendering, any operation without exactly
one active discovered rendering, and any discovered template that changes canonical placeholders
or text outside the lexical label.

### 17.3 Targeted provider checks

The development provider check covers B/C/F, P2/P3/P4, LP0B/LP1/LP3, explicit refusal and
clarification requests, the hidden-state grounding case, and the corrected ownership stimuli.
Explicit case and request IDs are now audited against the selected split. A cross-split mismatch
fails before any provider call instead of silently removing stimuli.

```bash
uv run lexstab run \
  --config config/run.v0.2-provider-check.yaml \
  --run-id run-v0.2-provider-check

jq '{status,healthy,baseline_eligible,provider_error_calls,length_terminated_calls,aborted_cells}' \
  runs/run-v0.2-provider-check/run-summary.json

uv run lexstab evaluate --run runs/run-v0.2-provider-check
uv run lexstab report --run runs/run-v0.2-provider-check --formats markdown,html,csv,parquet
```

Do not proceed unless provider errors, length terminations, and aborted cells are zero. Any length
termination sets `status: length_terminated`, `healthy: false`, and `baseline_eligible: false`.
Inspect the P3 and LP3 headline rows and require schema validity of 1.0 in this targeted check.

Run the corrected request-more-information contract separately because `RMI_001` and `CLOSE_001`
belong to the validation split:

```bash
uv run lexstab run \
  --config config/run.v0.2-rmi-check.yaml \
  --dry-run

uv run lexstab run \
  --config config/run.v0.2-rmi-check.yaml \
  --run-id run-v0.2-rmi-check

jq '{status,healthy,baseline_eligible,provider_error_calls,length_terminated_calls,aborted_cells}' \
  runs/run-v0.2-rmi-check/run-summary.json

uv run lexstab evaluate --run runs/run-v0.2-rmi-check
uv run lexstab report --run runs/run-v0.2-rmi-check --formats markdown,html,csv,parquet
```

The policy and planner stages use their v2 contracts in current harness runs. These contracts
distinguish `NO_POLICY_REQUIRED` from missing information and give the planner the same known state
available to triage, policy, and the final executor. The run manifest records the hashes of these
prompt versions. The original v1 prompt files remain unchanged for historical verification.

### 17.4 Canonical-envelope diagnostic

This diagnostic is separate from the benchmark matrix and never enters headline metrics.

```bash
uv run lexstab experiment canonical-envelope \
  --manifest dataset/manifests/benchmark-v0.2.0.json \
  --models config/models.local.yaml \
  --output runs/canonical-envelope-v0.2.0.jsonl
```

Compare its three conditions directly. Preserve the artifact even if the original
`status: RESOLVED` condition remains better or worse.

### 17.5 One-repetition frozen run before scaling

After updating `config/run.local.yaml` to the `v0.2.0` manifest and procedure path:

```bash
uv run lexstab run \
  --config config/run.local.yaml \
  --split development \
  --repetitions 1 \
  --run-id run-v0.2-frozen-1x

uv run lexstab evaluate --run runs/run-v0.2-frozen-1x
uv run lexstab report --run runs/run-v0.2-frozen-1x --formats markdown,html,csv,parquet
```

Read `measurement_warnings`, cohort-separated headline rows, and `rendering_contrast` before any
larger run. Confirm that F-Model-Discovered has coverage for all operations and that the distinct
subset is non-empty if a lexical comparison is claimed.

Only after the one-repetition report is interpretable:

```bash
uv run lexstab run \
  --config config/run.local.yaml \
  --split development \
  --repetitions 5 \
  --run-id run-v0.2-frozen-5x
```

## 18. v0.2.1 corrective release sequence

This sequence is intentionally gated. Do not run a real provider command until the two request
candidates are approved and the v0.2.1 benchmark has frozen and verified.

### 18.1 Human review gate

```bash
uv run lexstab review requests \
  --input dataset/requests/candidate/corrective-v0.2.1.jsonl \
  --reviewer phillip \
  --interactive
```

Approve the ownership candidate only if Tier 1 to Tier 2 is escalation. Approve the contrast only
if its exact reporter question and RMI operation are correct. Approval supersedes the named active
source row. It does not edit a frozen v0.2.0 file.

### 18.2 Local validation, freeze, and historical verification

After both candidates are approved:

```bash
uv run lexstab schema generate
uv run lexstab schema validate --all
uv run pytest -q

uv run lexstab domain validate --root dataset/domain/v0.2.1
uv run lexstab cases validate \
  --root dataset/cases/support-v0.2.1 \
  --domain-root dataset/domain/v0.2.1
uv run lexstab interfaces compare \
  --domain-root dataset/domain/v0.2.1 \
  --generic dataset/interfaces/v0.2.1/generic-action-proposal.json \
  --typed dataset/interfaces/v0.2.1/typed-tools/support.jsonl

uv run lexstab prompt-size-report \
  --output runs/prompt-size-v0.2.1.json

uv run lexstab benchmark freeze \
  --version 0.2.1 \
  --changelog-file dataset/manifests/changelog-v0.2.1.json

uv run lexstab benchmark verify \
  --manifest dataset/manifests/benchmark-v0.1.0.json
uv run lexstab benchmark verify \
  --manifest dataset/manifests/benchmark-v0.2.0.json
uv run lexstab benchmark verify \
  --manifest dataset/manifests/benchmark-v0.2.1.json
```

Never use `--dev-overwrite` for this release. The prompt-size command makes zero model calls and
writes exact character and UTF-8 byte counts plus an explicitly labeled four-bytes-per-token
estimate. The current fixed fixture targets a median increase below 2 percent and warns on any
stage above 5 percent.

### 18.3 Doctor and mock smoke

```bash
uv run lexstab doctor \
  --models config/models.mock.yaml \
  --run config/run.smoke.yaml

uv run lexstab run \
  --config config/run.v0.2.1-provider-check.yaml \
  --dry-run
```

The dry run requires the frozen v0.2.1 manifest. It reports matrix size and estimated calls but
does not invoke providers.

### 18.4 Targeted real-provider checks

These commands are operator-run steps and are not part of the corrective coding pass:

```bash
uv run lexstab run \
  --config config/run.v0.2.1-provider-check.yaml \
  --run-id run-v0.2.1-provider-check

jq '{status,healthy,baseline_eligible,provider_error_calls,length_terminated_calls,aborted_cells}' \
  runs/run-v0.2.1-provider-check/run-summary.json

uv run lexstab evaluate --run runs/run-v0.2.1-provider-check
uv run lexstab report \
  --run runs/run-v0.2.1-provider-check \
  --formats markdown,html,csv,parquet

uv run lexstab run \
  --config config/run.v0.2.1-rmi-check.yaml \
  --run-id run-v0.2.1-rmi-check

jq '{status,healthy,baseline_eligible,provider_error_calls,length_terminated_calls,aborted_cells}' \
  runs/run-v0.2.1-rmi-check/run-summary.json

uv run lexstab evaluate --run runs/run-v0.2.1-rmi-check
uv run lexstab report \
  --run runs/run-v0.2.1-rmi-check \
  --formats markdown,html,csv,parquet
```

Stop if either health summary reports a provider error, length termination, or aborted cell.
Require schema validity 1.0 for P3, P4, and LP3. Inspect actual runtime rendering and procedure IDs,
the ownership request's escalation result, the replacement contrast's RMI result, and the exact
first protected-message divergence.

### 18.5 Frozen one-repetition run, then optional five-repetition run

Do not begin this step during the corrective patch. After both targeted reports pass review:

```bash
uv run lexstab run \
  --config config/run.v0.2.1-frozen-1x.yaml \
  --run-id run-v0.2.1-frozen-1x
uv run lexstab evaluate --run runs/run-v0.2.1-frozen-1x
uv run lexstab report \
  --run runs/run-v0.2.1-frozen-1x \
  --formats markdown,html,csv,parquet
```

Only after that report is healthy and interpretable:

```bash
uv run lexstab run \
  --config config/run.v0.2.1-frozen-5x.yaml \
  --run-id run-v0.2.1-frozen-5x
```

## 19. Focused RMI replication release sequence

The focused replication is benchmark v0.3.0. It adds eight independent RMI cases and 24
human-reviewed request variants without changing any historical benchmark. The construction steps
make zero provider calls. Do not run the focused real-provider matrix until the review, freeze,
verification, and dry-run gates below pass.

### 19.1 Interactively review and scaffold case cards

```bash
uv run lexstab replication scaffold-rmi \
  --seed dataset/replication/seeds/rmi-v0.3.0.json \
  --creator phillip
```

Review the unique state and exact public message on each of eight cards. Accept or edit each
message, then type `CREATE`. The command stages and validates everything before writing versioned
source artifacts. It does not create a manifest and refuses to overwrite any v0.3.0 source or
frozen target.

### 19.2 Interactively author the 24 language variants

```bash
uv run lexstab replication author-rmi-variants \
  --version 0.3.0 \
  --creator phillip
```

For each case, enter or accept one canonical, one natural, and one high-lexical-distance request.
The incident ID and exact public message are protected. Type `WRITE` after reviewing the full
summary. This creates the candidate JSONL and focused one-repetition run config, but still no
manifest.

### 19.3 Review candidates and validate source artifacts

```bash
uv run lexstab review requests \
  --input dataset/requests/candidate/rmi-replication-v0.3.0.jsonl \
  --reviewer phillip \
  --interactive

uv run lexstab schema generate
uv run lexstab schema validate --all
uv run pytest -q

uv run lexstab domain validate --root dataset/domain/v0.3.0
uv run lexstab cases validate \
  --root dataset/cases/support-v0.3.0 \
  --domain-root dataset/domain/v0.3.0
uv run lexstab interfaces compare \
  --domain-root dataset/domain/v0.3.0 \
  --generic dataset/interfaces/v0.3.0/generic-action-proposal.json \
  --typed dataset/interfaces/v0.3.0/typed-tools/support.jsonl
```

All 24 requests must be approved or deliberately excluded before freeze. Approval must be based on
the frozen case meaning and protected message, not on any model result.

### 19.4 Freeze and verify v0.3.0

```bash
uv run lexstab benchmark freeze \
  --version 0.3.0 \
  --split-config dataset/splits/v0.3.0 \
  --changelog-file dataset/manifests/changelog-v0.3.0.json

uv run lexstab benchmark verify \
  --manifest dataset/manifests/benchmark-v0.1.0.json
uv run lexstab benchmark verify \
  --manifest dataset/manifests/benchmark-v0.2.0.json
uv run lexstab benchmark verify \
  --manifest dataset/manifests/benchmark-v0.2.1.json
uv run lexstab benchmark verify \
  --manifest dataset/manifests/benchmark-v0.3.0.json
```

Never use `--dev-overwrite`. The explicit split path is required because the eight new cases live
in the versioned v0.3.0 validation split.

### 19.5 Dry run before any paid execution

```bash
uv run lexstab doctor \
  --models config/models.local.yaml \
  --run config/run.v0.3.0-rmi-replication-1x.yaml

uv run lexstab run \
  --config config/run.v0.3.0-rmi-replication-1x.yaml \
  --dry-run
```

Confirm that the selected set contains exactly eight cases and 24 request IDs. Confirm that LP0B,
LP0BV, and LP1 each use only `intent_mode: gold`. Review the estimated call and token counts before
assigning a real run ID. The focused matrix uses deterministic evaluation and the configured
execution model; it does not require an LLM judge.

Only after those checks should the operator run, evaluate, and report:

```bash
uv run lexstab run \
  --config config/run.v0.3.0-rmi-replication-1x.yaml \
  --run-id run-v0.3.0-rmi-replication-1x

jq '{status,healthy,baseline_eligible,provider_error_calls,length_terminated_calls,aborted_cells}' \
  runs/run-v0.3.0-rmi-replication-1x/run-summary.json

uv run lexstab evaluate --run runs/run-v0.3.0-rmi-replication-1x
uv run lexstab report \
  --run runs/run-v0.3.0-rmi-replication-1x \
  --formats markdown,html,csv,parquet
```

Stop on any provider error, length termination, aborted cell, or schema-invalid output. Read the
paired LP0B versus LP1 and LP0BV versus LP1 comparisons at the canonical-case level. Eight
independent canonical cases permit a bounded RMI-family interpretation if the quality gates pass.
One operation family does not permit generalization across the broader ontology.

## 20. Cross-model persistence comparison

Use `docs/MODEL_TIER_COMPARISON_PROTOCOL.md` for the complete provider-free preparation, Sonnet 5
health check, frozen run, and analysis sequence. The checked-in health configuration is
`config/run.v0.3.0-model-comparison-health.yaml`. It intentionally selects two complete RMI cases,
all three approved request rows for each case, and all three call-balanced persistence conditions.

The cross-model analysis command makes no provider calls:

```bash
uv run lexstab compare-runs \
  --runs <opus-run>,<comparison-run> \
  --baseline-model claude-opus-4-8 \
  --bootstrap-samples 2000 \
  --output runs/model-comparison.json
```

The command fails closed on mismatched matrices, frozen inputs, execution parameters, invoked role
counts or configurations, run health, completion, or evaluator source hashes. Configuration
differences for roles not invoked in either run are retained as warnings. Its primary result is the
paired cross-model difference in differences for LP1 relative to LP0B and LP0BV. Raw per-model
accuracy is secondary.
