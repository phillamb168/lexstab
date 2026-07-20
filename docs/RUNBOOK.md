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
LEXSTAB_CACHE_DIR=./.cache/lexstab
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
- `--manifest <path>` — override the benchmark manifest (used for regression suites, step 14).

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

Only requests whose candidate record carries an approving reviewer decision can be promoted. Run
the regression suite (fewer repetitions is normal for CI, spec §17.3):

```bash
uv run pytest tests/regression
uv run lexstab run \
  --config config/run.local.yaml \
  --manifest dataset/manifests/regression-v0.2.0.json \
  --repetitions 3
```

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
