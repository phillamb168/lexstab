# Implementation status

Tracks progress against `llm-lexical-stability-harness-implementation-spec.md`
(spec 1.2.0) and its Definition of Done (§49).

Legend: ✅ complete · 🔶 partial (details noted) · 🔒 externally blocked

Verification evidence: full offline test suite (`uv run pytest tests/` with 138 passed,
1 skipped, mocked providers only), the §49.16 acceptance demonstration
(`uv run python scripts/acceptance_demo.py` — all 16 steps pass offline), and the CI
workflow (`.github/workflows/ci.yml`). Full-suite line coverage is 71%.

## Phase status (spec §48)

| Phase | Scope | Status |
|---|---|---|
| 1 | Deterministic foundation (schemas, domain, simulator, hashing, A0/A1, scorers, traces, smoke report) | ✅ |
| 2 | Dataset construction (authoring graph, request CLI, review, contexts, renderings, freeze) | ✅ |
| 3 | Architecture matrix (A/B/C, gates, M0–M4, P0–P4, LP0–LP3, procedures, interfaces, role separation) | ✅ |
| 4 | Evaluation & reporting (metrics, bootstrap, equivalence, tables, charts, md/html/csv/parquet) | ✅ |
| 5 | Advanced experiments (agent loop, grammar, code, cross-model, modality, elicitation, memory, P/LP, red team, regression) | ✅ (grammar/code/modality ship demonstration corpora per D-014; research-grade corpora are operator work) |
| 6 | Operationalization (LangSmith, CI, scheduled regression, cost estimation, drift path, export) | 🔶 (drift sentinel = scheduled workflow + cross-run comparison; live verification needs credentials) |

## Definition of Done (spec §49) — item-by-item

### 49.1 Core architecture — ✅
- ✅ Six independently runnable workflows: authoring (`lexstab author` / Graph A), execution (`lexstab run` / Graph B + procedural baseline), intent elicitation (`--track intent_elicitation` / §18.5 subgraph), progressive formalization (`--track progressive_formalization` / Graph E), evaluation (`lexstab evaluate` / Graph C), red team (`lexstab redteam` / Graph D).
- ✅ `lexstab run` never invokes authoring (no code path exists; authoring lives in `lexstab.authoring`, imported only by author/redteam commands).
- ✅ Cases, requests, contexts, renderings, memory records, procedures, and action interfaces are separate artifact types with separate schemas and directories.
- ✅ Five tracks independently runnable via `--track` (boundary, intent_elicitation, post_canonical, memory_ablation, progressive_formalization; plus agent_loop for Experiment 3).
- ✅ Primary H1 selection: `NLRequest.is_primary_h1()` requires frozen ADEQUATE/UNAMBIGUOUS/EXECUTE/INVARIANT (tested).
- ✅ Falsification capability: practical-equivalence verdicts include `practically_equivalent`/`practically_worse`; report generates "not justified" conclusions mechanically (reporting tests assert this).
- ✅ B-Gold/C-Gold inject `gold_canonical_resolution` from the case artifact; no canonicalizer output can enter (runner code path).
- ✅ Simulator has no external side effects (pure in-memory state; tested).
- ✅ Deterministic globally unique cell IDs (sha256 of cell coordinates; tested via matrix hash).
- ✅ Fresh simulator + fresh model context per cell (constructed per `run_cell`).

### 49.2 Schemas and artifacts — ✅
- ✅ 17 JSON Schema Draft 2020-12 files (the 15 required + elicitation-case + representation-ledger).
- ✅ Pydantic models are the source the schemas are generated from (D-025); contract test enforces sync.
- ✅ Rejection tests for unknown IDs, undefined arguments, illegal transitions, unapproved frozen artifacts.
- ✅ Requests stored as JSONL with exact original text (tested).
- ✅ SHA-256 content hash on every frozen artifact; benchmark manifest root hash (D-006).
- ✅ Freeze refuses to overwrite an existing version without `--dev-overwrite` (tested).
- ✅ Referential-integrity sweep (`lexstab integrity`, CI, tests).

### 49.3 Dataset authoring — ✅
- ✅ `lexstab request add` requires no model. ✅ Synthetic generation with explicit axes.
- ✅ Independent adequacy/ambiguity/semantic-role/expected-behavior/lexical-equivalence labels with consistency validators.
- ✅ Context-dependent labels require a frozen context (validator; tested).
- ✅ Generator/equivalence-critic/adversarial-critic separately configurable roles; role-separation policy blocks generator-as-sole-critic.
- ✅ Generator cannot approve candidates (approval requires reviewer records; tested).
- ✅ Disagreement routes to NEEDS_REVIEW. ✅ Full CANDIDATE/NEEDS_REVIEW/APPROVED/FROZEN/REJECTED/SUPERSEDED lifecycle.
- ✅ Reviewer approve/edit/reject/notes (batch + interactive). ✅ Frozen requests immutable (read-only + hash verification).
- ✅ Reviewer agreement export (`authoring.reviewer_agreement_export`).
- ✅ Source and provenance preserved.

### 49.4 Renderings, procedures, interfaces — ✅
- ✅ All six rendering categories shipped for ESCALATE_INCIDENT + canonical for all 8 operations.
- ✅ Blind discovery prompt shows no candidate labels; fresh sample per invocation; convergence rate/entropy recorded.
- ✅ Discovered renderings enter CANDIDATE status and are frozen before testing (acceptance demo step 4/6).
- ✅ Discovery restricted to development material (`discovered_on_split` recorded).
- ✅ Template placeholders validated against operation contracts (tested).
- ✅ Procedures versioned, hashed, reviewed, stored separately; required inputs validated (§15.4 constraints).
- ✅ Both interfaces generated from the one operation registry; `lexstab interfaces compare` verifies coverage/arguments/simulator mapping and measures terminology overlap.
- ✅ P3/P4 share identical frozen procedure bytes (same artifact, verified by matrix construction).
- ✅ P2F supplies unordered procedure facts without the procedure name or sequence; P2-to-P2F and
  P2F-to-P3 separate information addition from structured-procedure effects.
- ✅ MCP-style capability export with recorded hashes (D-023); packaging metadata recorded per cell.

### 49.5 Model and provider configuration — ✅
- ✅ Eleven explicit roles. ✅ Exact model IDs from config/env only; no aliases in code.
- ✅ Credentials from environment only; never logged; redaction helper for exports. Required roles
  resolve strictly, and no missing real-model ID can silently become a mock invocation.
- ✅ Role-separation defaults (MUT≠judge, generator≠sole critic, MUT≠generator) enforced pre-run; `allow_role_overlap` override recorded in run manifest and report.
- ✅ Common adapter contract (mock/anthropic/openai/openrouter); requested + accepted parameters recorded.
  Any mocked role used by a run makes the whole run baseline-ineligible.

### 49.6 Execution behavior — ✅
- ✅ A0/A1/B-Runtime/B-Gold/C-Runtime/C-Gold all run (acceptance demo).
- ✅ A1 receives equivalent domain/tool/state/context (same `_common_vars` assembly).
- ✅ Mock/smoke models are `baseline_eligible: false` in run manifests; reports label them.
- ✅ M0–M4, P0–P4, LP0/LP0G/LP1–LP3 supported. ✅ P0–P3 share one generic proposal schema.
- ✅ P3 vs P4 differ only in the action interface (graph parity node verifies).
- ✅ Gold and runtime procedure selection; local typed tool before MCP.
- ✅ Definition-only and organization-term controls.
- ✅ Randomized matrix order with recorded seed. ✅ No response cache exists; every call fresh.
- ✅ Bounded, logged transport retries; semantic retries hard-locked to 0 (D-018); invalid first attempts scored and visible (tested).
- ✅ Fixed tool order/schema across lexical conditions. ✅ Dry-run with matrix size and cost estimate.

### 49.7 Deterministic evaluation — ✅
All listed scorers implemented in `lexstab.evaluators.deterministic` and exercised by
tests: schema validity, decision class, tool, per-argument + full set, preconditions/
effects (simulator events), final state (with D-026 clock substitution), refusal
correctness + refusal false action, clarification P/R/F1 + false action + unnecessary
clarification, adequacy/ambiguity/missing-info/turns/unresolved (elicitation),
contrast + over-normalization, raw vs normalized scores (versioned normalizer),
procedure selection/adherence/forbidden actions (observable-only), generic-proposal
errors distinct from typed-tool validation errors, no judge where a deterministic
oracle exists (judge is optional and separate).

### 49.8 Robustness and trajectory metrics — ✅
Base/mean/worst-variant accuracy, robustness gap and best-to-worst spread (separately
named), within-case consistency, operational invariance, semantic discrimination,
first-divergence stage, final-state accuracy for loops, set-based trajectory scoring
via final-state primacy, cost/latency/tokens/errors separated from quality,
architecture bill of materials (D-029), persistence depth/reinterpretation/
representation-change/intermediate consistency, paired deltas for every adjacent
P transition with safety/cost.

### 49.9 LLM judge and human review — ✅ (calibration itself is 🔒 human work)
- ✅ Judge optional; blinded (opaque IDs, no architecture/model identity in prompt).
- ✅ Calibration gate: scores are `exploratory` unless a ≥2-rater calibration record exists (D-016). 🔒 Producing the calibration record requires human raters.
- ✅ UNCERTAIN → human review queue; `lexstab review human` records rubric/reviewer/timestamp/notes.
- ✅ LangSmith annotation queues optional; local operation complete.

### 49.10 Statistics — ✅
Case-clustered bootstrap (primary unit = canonical case), configurable comparisons and
margins, practical equivalence via interval-in-margin against A1 (never
non-significance), P-ladder equivalence vs P1 and vs predecessor, BH correction for
exploratory families, missing cells and completion rates reported, held-out split
sealed behind the frozen analysis plan (`docs/ANALYSIS_PLAN.md`, hash in run
manifest), primary/secondary/exploratory labels in metrics and report.

### 49.11 Experiments 1–10 — ✅ with scoped corpora
- ✅ Exp 1 (lexical substitution): primary H1 stratum restriction + separate clarification reporting.
- ✅ Exp 2 (baseline ladder): A0/A1/boundary/gold-injection/complexity comparisons.
- ✅ Exp 3 (agent loop): 4-stage workflow, typed state per stage, AL_RAW/AL_CANONICAL/AL_RENDERED/AL_DRIFT conditions.
- ✅ Agent-loop gold and runtime intent modes are separate cells; drift labels are generated by an
  independent authoring role and validated against canonical IDs and previously used labels.
- ✅ Exp 4 (grammar): discovery + 4 terminology conditions + deterministic span scoring. 🔶 4-item demonstration corpus (D-014).
- ✅ Exp 5 (code): mechanical pre-mutation equivalence + executable test scoring; real model output
  runs only in a network-disabled, read-only, resource-limited container. 🔶 one program family shipped (D-014).
- ✅ Exp 6 (portability): frozen benchmark reused across model configs; `lexstab compare-runs` computes rendering ranks, Spearman correlation, version deltas. 🔒 Real multi-model runs need credentials.
- ✅ Exp 7 (modality): separate typed/human-transcript/ASR artifacts, mutation-stage detection, canonical-resolution scoring. 🔒 Audio/ASR corpus needs participants and consent (§30.10).
- ✅ Exp 8 (elicitation): adequacy assessment, scripted multi-turn loop with turn-limit-before-invocation, false action, turns to resolution.
- ✅ Exp 9 (memory): M0–M4 with deterministic retrieval, scope/staleness validation, retrieval events (D-028).
- ✅ Exp 10 (formalization/persistence): cumulative ladder, gold-injected component ablations, packaging + selection ablations, LP conditions, representation ledger.
- ✅ Each experiment's primary metric and confounds documented (docs/METHODOLOGY.md).

### 49.12 Logging and tracing — ✅
- ✅ Fully local JSONL tracing; run manifests read-only after write; prompts, tool defs, procedure selections, ledgers, raw responses, normalized outputs, state transitions, scores, and errors retained; secrets redacted (never enter prompts; defensive scrubber for exports).
- ✅ LangSmith enabled via config/env with §23.4 metadata fields. 🔒 Live verification needs a LangSmith account.
- ✅ Stored runs rescore without any model (tested: provider construction is monkeypatch-forbidden during evaluation).

### 49.13 Runbook and documentation — ✅
README, docs/RUNBOOK.md, docs/DATASET_AUTHORING.md, docs/PROCEDURES_AND_INTERFACES.md,
docs/RESULTS_GUIDE.md, docs/METHODOLOGY.md, plus docs/DECISIONS.md and
docs/ANALYSIS_PLAN.md. `.env.example` and all four config examples present. Every
documented command has an automated `--help` test (35 commands, parameterized test).

### 49.14 Reports — ✅
Markdown, HTML, CSV, JSON, Parquet outputs; headline table with denominators + CIs;
paired B-Gold/C-Gold table and chart; per-transition marginal-delta tables and chart;
LP0G-vs-LP1 primary + LP0-vs-LP1 secondary; procedure/packaging/selection/typed/MCP
separately labeled; invariance and discrimination shown together; clarification and
false action prominent; worst variants and first-divergence views; hash/ID headers;
null results never suppressed ("Null and negative results" section); the exact
"Does the added architecture earn its complexity?" section with mechanically chosen
§44.8 conclusion including the A1-sufficient and no-transition-cleared outcomes.

### 49.15 CI and regression — ✅
- ✅ PR checks: schemas, prompts, domain state, hashes, tests, integrity, interface equivalence, no-secret scan, frozen-artifact verification — no paid calls.
- ✅ Mocked smoke check in CI. ✅ Scheduled regression workflow gated on secrets (paid path) and
  blocks on configured threshold failures. Promoted suites execute as verified overlays on their pinned base
  benchmark. 🔒 Verifying against a live provider needs credentials.
- ✅ Baselines = immutable run-manifest hashes; threshold config (`config/thresholds.example.yaml`).
- ✅ Red-team output goes only to the candidate corpus (tested: report/scores hashes unchanged).
- ✅ Regression promotion requires human approval and creates a new version with provenance (tested).

### 49.16 Acceptance demonstration — ✅
`scripts/acceptance_demo.py` performs all 16 steps offline against the mock provider
and asserts every outcome; it runs in CI. Steps: human + inadequate request →
synthetic variants (non-MUT model) → review/freeze → rendering discovery/freeze →
procedure + interface artifacts → benchmark freeze 0.1.0 (refreeze refused) →
role-separated models → dry run with cost → A0..C-Gold on 5 cases × 2 reps →
P0–P4 + LP conditions with ledger → deterministic scores + traces → full report →
rescore without providers (byte-identical) → red team without score mutation →
regression promotion v0.1.0 → M1-vs-M2 smoke ablation with frozen primary intact.

## Externally blocked items

| Item | Blocker |
|---|---|
| Paid benchmark execution against real providers | Operator credentials + explicit run command (never automatic) |
| Publication-grade human review (two independent reviewers, adjudication, IAA reporting) | Human reviewers; harness records decisions and exports agreement data |
| Judge calibration record (≥2 human raters, paraphrase robustness) | Human raters (spec §35.5); until then judge output is labeled exploratory |
| Research-grade grammar/code corpora (beyond shipped demonstrations) | Operator authoring/labeling effort (D-014) |
| Experiment 7 audio + ASR corpus | Participants, consent, ASR provider (spec §30.10) |
| Hosted-model drift sentinel results | Scheduled paid runs over time (workflow exists) |
| LangSmith live tracing verification | LangSmith account/key |
| Cross-model portability results (Experiment 6 data) | Paid runs across ≥3 model families (tooling complete) |

## Honest limitations (not blockers)

- The mock provider is a deterministic keyword interpreter. Mocked results validate
  wiring, never hypotheses; every mocked run manifest and report says so.
- The starter dataset (12 cases, 75+ requests after the demo) is smoke/development
  scale; spec §50 recommends ≥20 cases for a research pilot and 100 for the full
  design.
- Hierarchical modeling is exported (analysis-table.parquet + frozen formula), not
  fit in-process (D-010).
- The §19.6 cross-over study is an operator workflow (three runs with role-swapped
  configs over the unchanged frozen benchmark), not a single command.
