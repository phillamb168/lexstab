# Implementation decisions

This log records interpretations and engineering choices made while implementing
`llm-lexical-stability-harness-implementation-spec.md` (spec version 1.2.0).
The specification remains authoritative and unchanged; entries here document how
underspecified details were resolved. Each entry states the decision, the reason,
and the spec sections it interprets.

## D-001: Project root and package name

**Decision.** The harness is implemented at the root of `/Users/phil/Work/lexical-harness`
(the existing workspace), with the Python package at `src/lexstab/`. The spec's
illustrative top-level directory name `lexical-stability-harness/` is treated as the
repository itself, not a required nested directory.

**Reason.** Spec §10 says "The exact package names may change, but the boundaries …
must remain." The workspace root is the repository.

## D-002: Python version

**Decision.** `requires-python = ">=3.12"`. Development and testing use CPython 3.13
(the newest interpreter on this host with broad wheel coverage; 3.12 is not installed).

**Reason.** Spec §8 requires "Python 3.12 or later". 3.13 satisfies it.

## D-003: JSONL handling

**Decision.** JSONL reading/writing uses the standard library (`json` per line) via
`lexstab.artifacts.jsonl_read/jsonl_write` instead of the `jsonlines` package.

**Reason.** Spec §8 lists "`jsonlines` or equivalent". The stdlib is equivalent and
removes a dependency.

## D-004: Provider adapters use direct REST via httpx

**Decision.** Anthropic, OpenAI, and OpenRouter adapters call the providers' HTTP APIs
directly through `httpx` rather than vendor SDKs. All adapters implement the common
`ModelProvider` protocol from spec §20 and return complete `InvocationRecord`s.

**Reason.** Spec §8 lists "Provider SDKs behind a common adapter interface" as a
recommendation; the load-bearing requirement is the common adapter contract (§20).
Direct REST keeps the dependency tree small, keeps request/response bytes fully
observable for tracing, and avoids SDK-version drift. Exact model IDs always come from
configuration (§19.4); no marketing aliases appear in code.

## D-005: Safe expression language for preconditions and effects

**Decision.** Operation `preconditions`, `effects`, and `invalid_when` strings are parsed
by a restricted evaluator (`lexstab.simulators.safe_expr`) supporting only:

- attribute paths rooted at the operation's entity (`incident.status`) or arguments
  (`destination_tier`), plus the reserved `run_clock`;
- comparisons `==, !=, <, <=, >, >=` against literals or other paths;
- effects of the form `path = <literal|path|run_clock>` and `path += <number>`;
- string, integer, float, and boolean literals.

Anything else fails validation at load time. No `eval`, no function calls.

**Reason.** Spec §11.4: "The production schema should replace unconstrained string
expressions with a small safe expression language … The harness must not execute
arbitrary expressions from dataset files." The grammar above covers every expression
used by the spec's own examples.

## D-006: Content hashing convention

**Decision.** `sha256:<hex>` hashes are computed as follows:

- JSON artifacts: canonical JSON (UTF-8, sorted keys, `,`/`:` separators, no trailing
  whitespace) with any `content_hash` field (top-level or under `provenance`) removed
  before hashing, so the recorded hash is reproducible from the stored file.
- Text artifacts (prompts, procedures-as-markdown): raw file bytes.
- Manifest root hash: sha256 over the canonical JSON of the sorted
  `[[relative_path, sha256], …]` inventory.

**Reason.** Spec §16.2 and §40.2 require SHA-256 artifact and root hashes but do not fix
a serialization; canonical JSON makes hashes stable across formatting.

## D-007: Freeze immutability mechanism

**Decision.** Freezing (a) validates, (b) computes hashes, (c) writes frozen files and the
manifest, then (d) chmods frozen artifacts and the manifest to read-only (0o444).
`lexstab benchmark freeze` refuses to overwrite an existing manifest version unless
`--dev-overwrite` is passed (recorded in the manifest as a development-only override).
Every consumer re-verifies hashes before use and aborts on mismatch.

**Reason.** Spec §16.2 items 8–9 and §49.2 ("Freezing an existing version without an
explicit development override fails", "frozen artifacts cannot be silently mutated").
Hash verification is the load-bearing control; the read-only bit is defense in depth.

## D-008: Graph engine

**Decision.** The six workflows are implemented on LangGraph (`StateGraph`) as spec §18
recommends, with a minimal procedural baseline runner (`lexstab.graphs.procedural`)
that shares the same node functions, provider adapters, and evaluators (§18.7).
Node logic lives in plain functions so both runners execute identical code.

**Reason.** Spec §8/§18 recommend LangGraph but require that the graph must not be able
to create the observed effect; sharing node functions makes the baseline comparison
meaningful.

## D-009: Mock provider and offline fixtures

**Decision.** A deterministic `mock` provider (`lexstab.providers.local`) implements the
full adapter contract without network access. It resolves responses from an explicit
scripted-response table (fixtures) or from a deterministic heuristic interpreter over
the assembled prompt, and stamps every invocation with `provider="mock"`. Runs whose
execution role uses the mock provider are marked `baseline_eligible: false` in the run
manifest, and reports label them as smoke/mocked, never as research evidence.

**Reason.** The operator instruction requires mocked fixtures so all local tests and
smoke workflows run without credentials, and spec §17.4/§46.26 require smoke results
never be reported as hypothesis evidence. Mock responses are clearly labeled and are
never presented as real provider output.

## D-010: Statistics scope

**Decision.** Primary statistics are implemented in code: case-clustered bootstrap CIs
(10,000 resamples default, seeded), paired-delta CIs, McNemar's exact test (secondary),
Benjamini–Hochberg FDR for exploratory families, and practical-equivalence interval
checks against A1 margins. The §39.5 hierarchical/mixed-effects model is provided as a
frozen model formula in the analysis plan plus an exported per-call analysis table
(CSV/Parquet) for external fitting; it is not fit inside the harness.

**Reason.** Spec §39.5 scopes hierarchical modeling to "publication-grade analysis";
no Python package fits clustered mixed-effects logistic models reliably enough to be a
CI-tested dependency. The harness's own primary analysis (§39.3) is the cluster
bootstrap, which is fully implemented and tested.

## D-011: Canonical case inventory for the pilot dataset

**Decision.** The shipped starter dataset contains 12 canonical cases across the eight
required operation families (§11.2), including escalation family variants ESCALATE_001–005
mirroring §12.3, plus contrast/refusal-bearing cases for REASSIGN, CLOSE,
REQUEST_MORE_INFORMATION, REFUND_DUPLICATE_CHARGE, REQUEST_MANAGER_REVIEW,
SUSPEND_ACCOUNT, and REQUEST_APPROVAL. Requests per case follow §17.4 smoke sizing, with
extra invariants for the escalation family. All shipped requests/labels are marked
`created_by: "human"`-reviewed fixtures authored with this implementation and are
suitable for smoke and development only; a research pilot should extend to ≥20 cases
per §24.7.

**Reason.** Spec §17.4 fixes the smoke set; §50 recommends 20 cases for a pilot but the
shipped dataset only needs to make every workflow executable and testable offline.

## D-012: Run clock

**Decision.** The simulator's deterministic run clock is the ISO-8601 string from
`execution.run_clock` in run config, stored in the run manifest and applied wherever an
effect assigns `run_clock`. Wall-clock timestamps appear only in provenance/trace
metadata, never in simulated state.

**Reason.** Spec §11.5 ("Use a deterministic run clock stored in the run manifest").

## D-013: Representation ledger placement

**Decision.** Every model-mediated stage in execution appends a ledger record
(spec §18.6 format) to `representation-ledger.jsonl`; single-stage architectures write
one record whose `stage_id` is `executor`. Persistence depth and reinterpretation
counts are computed by the evaluator from the ledger, never re-derived from prompts.

**Reason.** Spec §7.18, §18.6, §38.11 require observability of authoritative
representation at every stage, including single-stage conditions for comparability.

## D-014: Grammar, code-identifier, and modality experiments (4, 5, 7)

**Decision.** Experiments 4, 5, and 7 ship with: their schemas, prompt artifacts,
deterministic scorers (span P/R/F1 and unrelated-edit rate; code test-runner scoring in a
subprocess sandbox; modality artifact-chain records and canonical-resolution scoring),
CLI entry points, and mocked fixtures with tests. The shipped datasets are minimal
demonstrations; producing research-grade corpora (labeled editing corpus, multi-file
code families, human audio) is operator work flagged in IMPLEMENTATION_STATUS.md.

**Reason.** Spec Phase 5 requires executable manifests, prompts, scorers, and documented
limitations — not a full corpus. Audio collection requires human participants (§30.10).

## D-015: LangSmith integration

**Decision.** LangSmith support is a thin optional exporter: when
`LANGSMITH_TRACING=true` and the `langsmith` package plus API key are present, run
spans/metadata mirror to LangSmith with the §23.4 metadata fields. Local JSONL remains
the source of truth; all tests run with LangSmith disabled.

**Reason.** Spec §23.4 ("The harness must work without LangSmith"; upload "only as a
mirror").

## D-016: Judge calibration gate

**Decision.** LLM-judge scores are excluded from headline metrics unless a calibration
record (`runs/<id>/judge-calibration.json`) exists with ≥2 human raters and paraphrase
robustness stats; otherwise judge output is stored but labeled `exploratory`. The gate
is enforced in reporting code, not by convention.

**Reason.** Spec §35.5 and §49.9.

## D-017: Adequacy-matrix cell derivation

**Decision.** The four cells of §9.2 are derived, not stored: rows from the frozen
`adequacy`/`ambiguity` labels (`ADEQUATE`+`UNAMBIGUOUS` = top row), columns from
`labels.contains_canonical_operation_term`/`contains_canonical_entity_term` and
`lexical_distance_band` (`conventional` when the request contains the canonical
operation term and lexical distance band is LOW, else `varied`). The derivation is a
pure function with unit tests.

**Reason.** §9.2 requires every request to occupy one cell but defines no storage field;
deriving from independent frozen labels avoids a redundant, contradictable label.

## D-018: Semantic retries and parse repair

**Decision.** `semantic_retries` is hard-coded to 0 for all primary conditions; the run
config value is validated and a nonzero value fails validation unless the architecture
name is in an explicit `retry_policy_experiment` allowlist (none shipped). Parsing is
single-pass: a JSON extraction that fails is recorded as `parse_status: "error"` and
scored incorrect; no re-prompting occurs anywhere in execution.

**Reason.** Spec §7.11, §20.1, §49.6.

## D-019: Contexts for context-free requests

**Decision.** Requests whose adequacy does not depend on conversational context have
`labels.context_id: null` and execute with the frozen empty context `CTX-EMPTY-001`,
which is itself a frozen artifact, so every matrix cell still records a context hash.

**Reason.** §13.6 requires frozen context whenever adequacy depends on it; a frozen
empty context keeps the "equivalent context across architectures" invariant checkable
in all cells.

## D-020: Charts

**Decision.** Charts are rendered with matplotlib to PNG and SVG under
`runs/<id>/charts/`, using deterministic ordering and fixed seeds; chart tests assert
file creation and data inputs, not pixel equality.

**Reason.** §44.6 requires the visualizations; pixel-exact snapshot testing of
matplotlib output is fragile across platforms.

## D-021: The `uv.lock` file

**Decision.** `uv` manages dependencies; `uv.lock` is committed. CI uses
`uv sync --frozen`.

**Reason.** Spec §10 layout and §42.2.

## D-022: Scripted authoring/critic models in offline mode

**Decision.** The authoring graph runs against any configured provider role. In offline
mode the mock provider produces deterministic template-based candidates and judgments
clearly marked `source.type: "synthetic"`, `model_id: "mock"`. These candidates flow
through the same validation and human-review lifecycle as real ones and are used only
in tests and the acceptance demo.

**Reason.** The operator instruction requires the full workflow demonstrable offline;
spec §7.2 requires creativity before freezing, which the lifecycle preserves regardless
of generator quality.

## D-023: MCP interface condition

**Decision.** The P4 typed action interface ships as a local registered typed-tool
contract backed by the simulator (spec's stated default). An MCP-compatible capability
export (`lexstab interfaces build --mcp-output`) emits MCP-style capability definitions
with recorded hashes, and the adapter can consume them through the same validation
path, but no live MCP server is shipped or required.

**Reason.** Spec §15.5/§33.5: "The default implementation may use local native tool
calling. A live MCP server is optional."

## D-024: Report format for "native tool calling" under the mock provider

**Decision.** Tool-call capture is normalized to a provider-neutral structure
(`{"tool": name, "arguments": {...}}`). Providers with native tool APIs populate it from
native tool-call blocks; the mock provider and no-native-tool providers use the §24.3
fallback JSON structure. The normalization layer records which mechanism produced the
call (`tool_call_mode`), and compared lexical conditions always share one mechanism
(§20.2).

**Reason.** §20.2 and §24.3 explicitly define the fallback and require recording the
capability difference.

## D-025: JSON Schemas generated from Pydantic models

**Decision.** The Draft 2020-12 files in `schemas/` are generated from the Pydantic
models by `lexstab schema generate` and committed. A contract test
(`tests/contract/test_schemas_and_artifacts.py::test_committed_schemas_match_models`)
fails whenever the committed schemas drift from regeneration.

**Reason.** Spec §49.2 requires "Pydantic models enforce equivalent runtime
validation"; generating one layer from the other makes equivalence structural rather
than a maintenance promise. The generated `operation.schema.json` is equivalent to
(§11.4's example, extended with the D-005 safe-expression validation performed at
load time).

## D-026: Deterministic run-clock placeholder in gold states

**Decision.** Case artifacts store `"<run_clock>"` wherever an operation effect
assigns `run_clock` (e.g. `updated_at`). Freeze-time recomputation runs the simulator
with the literal placeholder as its clock, so stored gold states compare exactly. At
evaluation time the comparator substitutes the run manifest's actual `run_clock`
before comparing final states.

**Reason.** Spec §11.5 requires a deterministic run clock from the run manifest and
§16.2 requires freeze-time recomputation of gold transitions; the placeholder keeps
case artifacts run-independent while both checks stay exact.

## D-027: LP1 runs in both gold and runtime intent modes

**Decision.** `LP1_CANONICAL_ONCE` matrix cells are generated twice: `intent_mode:
gold` (paired with LP0G for the primary controlled persistence comparison, both
starting from the same resolved gold intent) and `intent_mode: runtime` (paired with
LP0 for the practical end-to-end comparison, which includes user-language
interpretation). Reports label the gold pairing primary and the runtime pairing
secondary/practical.

**Reason.** Spec §33.6 defines LP1 as starting from the user request, but §33.13 and
§44.3 pair it against gold-start LP0G "after starting meaning is fixed". Running both
modes keeps each comparison clean instead of mixing canonicalizer error into the
controlled persistence estimate.

## D-028: Semantic-memory retrieval is deterministic lexical retrieval

**Decision.** M2/M4 retrieval ranks frozen memory records by surface-form token
overlap with the request (top-k=2), after scope/status/effective-date validation, and
records per-record retrieval events (rank, validity, injected). No embedding model is
used in the starter implementation.

**Reason.** Spec §32.6 requires a deterministic lexical retrieval baseline before
vector retrieval; it is the reproducible default, and a vector retriever can be added
later as a named condition without changing the comparison design.

## D-029: Complexity bill of materials is static-plus-measured

**Decision.** Each architecture's BOM (spec §38.10) combines a static inventory
(mutable model stages, external services, persisted stores, NL handoffs — declared in
`lexstab.metrics.aggregate.ARCHITECTURE_BOM`) with measured runtime aggregates (model
calls, tokens, latency percentiles) from the run. No default weighted score is
computed (spec §44.8 forbids collapsing dimensions by default).

## D-030: Canonical control-plane outcome is separated from canonical intent

**Decision.** `canonicalizer.v2` returns `mapping_outcome` plus a nested `canonical_intent`.
Only that nested intent reaches acting prompts. Legacy `status` envelopes are accepted only by an
explicit compatibility parser for historical artifacts. The prior `status: RESOLVED` shape remains
a standalone diagnostic variable, not a benchmark condition.

**Reason.** A control-plane label can act as unintended model-facing vocabulary when it shares the
same flat object as the task. Separating the objects removes that collision without assuming why
the original word affected behavior.

## D-031: Grounding is deterministic and source-provenanced

**Decision.** Entity IDs must occur in the request or frozen shared context, including visible
context state. Hidden singleton state cannot originate an entity. Required arguments may come from
request, shared context, or an explicit state-derivation registry. The first registry contains only
the confirmed duplicate-charge amount for an anchored order.

**Reason.** This tests language resolution without granting the canonicalizer an unrealistic hidden
database shortcut, and it makes each completed field auditable.

## D-032: Runtime, gold, procedure selection, and procedure packaging are separate cohorts

**Decision.** Headline and persistence aggregation keys include track, architecture, intent mode,
procedure selection, and procedure packaging. Paired comparisons select exact cohorts. Gold cells
use case gold and retain source request labels only as audit metadata. Safety and adequacy metrics
exclude gold injection.

**Reason.** Averaging those conditions confounds interpretation error, execution error, procedure
selection, and packaging. The corrected structure makes such averaging impossible by construction.

## D-033: P3 and typed non-action outputs use exact versioned boundaries

**Decision.** P3 uses a complete flat generic proposal schema. P4 and LP3 use one native tool call
for ACT and an exact three-field JSON decision for CLARIFY or REFUSE. Nested proposal wrappers,
missing fields, extra fields, multiple tool calls, and free-form prose are invalid.

**Reason.** Output-contract ambiguity is a measurement failure, not evidence against the tested
architecture.

## D-034: Discovered rendering comparison uses real blind operation naming

**Decision.** The execution model receives a neutral card for each of eight operations in 50 fresh
contexts. Candidate artifacts record requested and reported model identity, prompt hash, term
counts, convergence, entropy, definition-only rate, and canonical-reference provenance. The
canonical template frame is preserved exactly while only the lexical label changes. Human review
is required before activation.

**Reason.** A mock or grammar-oriented naming prompt cannot operationalize a model-discovered
operation vocabulary. Identical instantiated text provides no lexical contrast and is labeled as
such.

## D-035: LP0B is the primary persistence control

**Decision.** LP0B uses three exact stage envelopes and one final proposal call. Only each
`handoff_text` continues to the next stage. LP0B gold and LP1 gold each use four execution-model
calls. LP0G remains the realistic secondary condition with additional language rewrite calls.

**Reason.** Call balancing separates representation persistence from the independent effect of
more model-mediated translations.

## D-036: Schema validity gates interpretation, not raw evidence

**Decision.** Every cohort below the configured schema-validity threshold remains in raw scores,
failure tables, and estimates. Comparisons touching that exact cohort receive
`interpretation_allowed: false`; report prose withholds causal attribution. Missing pairs receive
the same treatment.

**Reason.** Removing failures would bias scores, while interpreting an underspecified or broken
contract would misattribute a measurement defect to the architecture.

## D-037: Corrective changes create benchmark `v0.2.0`

**Decision.** `v0.1.0`, its frozen artifacts, and existing run outputs remain immutable. The
ownership wording is superseded rather than deleted, corrected request candidates require Phillip's
review, and `v0.2.0+` freezes require one active non-mock discovered rendering per operation.

**Reason.** Corrected scores must be comparable without rewriting the historical record.

## D-038: Corrected ontologies use manifest-declared versioned source paths

**Decision.** `v0.1.0` retains the live paths and hashes recorded in its immutable manifest.
Corrected `v0.2.0` domain, case, interface, and elicitation inputs live under versioned sources.
Freeze selects matching versioned sources when present, writes those paths into the new
manifest, and the benchmark loader verifies and loads the manifest-declared paths rather than
hardcoded repository defaults.

**Reason.** Changing a shared ontology or case path after freezing made historical verification
correctly report tampering. Versioned source paths preserve reproducibility while allowing an
incompatible domain correction to coexist with the first benchmark.

## D-039: Requesting information pauses for the reporter without transferring support ownership

**Decision.** `REQUEST_MORE_INFORMATION` requires an explicit public reporter message. Execution
keeps the current support team and tier, changes the incident to `PENDING_INFO`, sets
`awaiting_party` to `REPORTER`, stores the public comment, and records that the reporter
notification was sent. If the message is missing, the boundary returns clarification and the
elicitation track asks what the service desk needs from the reporter.

**Reason.** Waiting on an external participant is a process pause, not an ownership transfer. The
original operation modeled only the waiting state and allowed action without specifying what the
reporter should provide.

## D-040: Explicit selections fail closed and policy absence is not ambiguity

**Decision.** Explicit case and request selections must be contained by the configured split and
label filters. Any mismatch stops matrix construction with an audit error. Validation-split RMI
stimuli run through their own checked-in configuration. Policy stage v2 adds
`NO_POLICY_REQUIRED`, and planner stage v2 receives known state directly.

Gold injection also preserves case-level clarification. A CLARIFY gold case produces a
`NEEDS_CLARIFICATION` envelope and never exposes a fully mapped intent to an executor.

**Reason.** Silently dropping selected stimuli misstates coverage. Treating an inapplicable policy
as missing information creates false clarification, while mapping a gold clarification case creates
an impossible scoring condition. Each is a harness defect rather than model behavior.

## D-041: Runtime artifacts are selected from the resolved operation

**Decision.** Runtime matrix cells carry a rendering category or procedure selector rather than a
parent-case artifact ID. After canonicalization, the harness looks up the rendering and procedure
for the resolved operation. Cell results record the actual rendering ID, instantiated text, and
actual procedure ID. Gold post-canonical conditions may still prebind known artifacts.

**Reason.** A semantic contrast can resolve to an operation different from its parent case. Using
the parent artifact after resolution leaks the wrong task back into execution and invalidates the
comparison.

## D-042: Persisted operational arguments have explicit preservation modes

**Decision.** Operation arguments declare `VERBATIM`, `CANONICAL`, or `SEMANTIC` preservation.
The RMI public `message` is `VERBATIM`; IDs, enums, and numeric arguments are `CANONICAL` in
v0.2.1. Exact protected literals are checked with a versioned deterministic token-sequence
comparison at each authoritative prose handoff and with exact value comparison at the action
boundary. An LLM judge is not part of this primary metric.

**Reason.** Approximate semantic continuity is insufficient when a value is persisted publicly or
sent externally. The preservation contract distinguishes acceptable normalization from operational
data corruption.

## D-043: Sample gates limit interpretation without removing observations

**Decision.** Causal report prose requires at least six independent canonical cases. Broader
generalization requires at least three operation families. Requests and repetitions derived from
one case do not increase the independent sample count. Below a gate, raw scores, deltas, failures,
and intervals remain available with an `exploratory` or `tested_operation_families_only` scope.

**Reason.** Three wording variants from one canonical task are repeated measurements, not three
independent confirmations. The gate prevents a small targeted check from becoming an article-level
causal claim.

## D-044: The visible preservation reminder is a call-balanced ablation

**Decision.** LP0B remains the no-reminder prose condition. LP0BV uses the same four execution
calls and the same authoritative free-form handoffs while naming protected fields at every mutable
stage. LP1 remains the four-call canonical-once condition. Prompt overhead is measured from a
fixed fixture without provider calls.

**Reason.** This separates the value of a small explicit instruction from the value of preserving
canonical structure. The fixed-fixture report keeps token-overhead discussion empirical.

## D-045: Inference and lexical claims use canonical-case and effective-input audits

**Decision.** Paired effect intervals continue to bootstrap at the canonical-case level. Exact
directional inference first reduces every case's variants and repetitions to one mean paired
direction and applies a two-sided sign test over independent cases. Cell-level McNemar remains a
descriptive compatibility metric and is excluded from exploratory FDR whenever cells share cases.

Every evaluated run also records an `effective_input_audit` over the first model-visible invocation
inside each exact cohort and case. Multiple frozen source requests that produce one identical model
input are reported as repetitions, not as evidence about lexical distance. Persistence reports
distinguish earliest divergence, later exact recovery, pristine success, and unrecovered failure.

**Reason.** Request variants and repetitions are correlated observations. Treating them as
independent produces artificially small p-values. Source-corpus labels also do not establish that
source wording survived a gold-injection or formalization boundary. The harness must verify the
actual stimulus before attaching a lexical interpretation to a result.

## D-046: Recovery composes only a complete compatible track

**Decision.** A completed broad run that fails global health because one track contains provider
response-limit failures may be recovered without repeating healthy cells only by replacing that
entire track from a separate healthy run. Composition is provider-free and writes a new run
directory. It requires exact equality of the benchmark root, code revision, lockfile, prompt,
procedure and interface hashes, run clock, matrix seed, provider identities, model identities, and
every matrix row in the replaced track. The replacement may differ only by increased `max_tokens`
budgets. The composite records all source hashes, replacement cell IDs, row counts, and parameter
differences, and the report identifies itself as a provenance-linked composite.

Source runs remain immutable. Selected failed rows may not be rerun and spliced individually. A
partial replacement, changed model, changed prompt, changed sampling parameter, unhealthy repair,
or mixed benchmark is rejected.

**Reason.** The original v0.2.1 broad run retained 814 completed cells but three
intent-elicitation invocations reached their response limits. Repeating the other 806 cells would
add cost without changing their treatment. Whole-track replacement preserves the experimental
cohort boundary while making the response-budget change visible and auditable.

## D-047: Model-tier persistence uses a paired difference in differences

**Decision.** The first execution-model comparison reuses the complete frozen v0.3.0 persistence
matrix and changes only `execution_primary`. `claude-opus-4-8` is the baseline and
`claude-sonnet-5` is the first comparison model. The primary cross-model estimand is:

```text
(comparison model LP1-minus-prose benefit) - (baseline model LP1-minus-prose benefit)
```

The comparison is computed for LP0B and LP0BV baselines, with final-state correctness and exact
protected-argument preservation as outcomes. Runs must match on benchmark root, exact matrix,
seed, clock, prompt, procedure, interface, non-execution roles, and evaluator source hash. Raw
per-model condition accuracy remains descriptive. The initial response budget remains 1,024
tokens, matching the Opus run.

**Reason.** A raw model-accuracy difference cannot show whether canonical-state persistence is
more valuable for one model tier. The paired difference in differences isolates the change in the
architecture benefit while preserving case-level pairing. The strict compatibility gate prevents
model-tier conclusions from absorbing changes in test stimuli, evaluator code, or other model
roles.
