# Dataset authoring

How natural-language requests, contexts, and model-facing renderings are created, labeled,
reviewed, frozen, and versioned. Authoring is a separate executable workflow from benchmark
execution: `lexstab run` never invokes authoring (spec §G7, §14), and authoring models only ever
propose candidates — humans approve gold (spec §9.4).

## 1. Manual request creation (spec §14.4, §42.5)

Human authorship is first-class. Add a request without invoking any model:

```bash
uv run lexstab request add \
  --case ESCALATE_001 \
  --text "Kick INC-1047 upstairs to Tier 2." \
  --semantic-role INVARIANT \
  --adequacy ADEQUATE \
  --ambiguity UNAMBIGUOUS \
  --expected-behavior EXECUTE \
  --lexical-equivalence INVARIANT \
  --axes idiomatic,operation_synonym,conversational \
  --source human
```

The request enters CANDIDATE status in `dataset/requests/candidate/manual.jsonl` (change with
`--output`) and follows the same validation and approval flow as synthetic requests. Additional
options:

- `--creator <id>` — recorded in provenance (default `operator`).
- `--context-id <CTX-…>` — required whenever adequacy depends on context (spec §13.5).
- `--missing-information entity_reference,destination_tier` — required (comma-separated) for
  INADEQUATE requests unless contradiction, not absence, is the reason.
- `--contrast-operation <OP_ID>` — for CONTRAST requests, the distinct gold operation.
- `--refusal-operation <OP_ID>` and `--refusal-policy <POLICY_ID>` — REFUSAL requests must
  identify the prohibited operation and the controlling policy or failed precondition.

## 2. Synthetic generation (spec §14, §42.6)

```bash
uv run lexstab author requests \
  --cases dataset/cases/support \
  --models config/models.local.yaml \
  --axes entity_synonym,operation_synonym,indirect_request,idiomatic \
  --count-per-axis 10 \
  --output dataset/requests/candidate/authoring-run-001.jsonl
```

Options: `--case-ids ESCALATE_001,CLOSE_001` restricts cases; `--models` also accepts the alias
`--config`; `--procedural` uses the procedural runner instead of the LangGraph authoring graph
(both run identical node functions, D-008). This command is never invoked implicitly by
`lexstab run`.

The authoring graph (spec §14.1) plans axis coverage, generates candidates, then passes each
through an independent semantic-equivalence critic, an adversarial interpretation critic, adequacy
and ambiguity classifiers, and deduplication. Critic disagreement routes the candidate to human
review; the generator can never approve its own candidates (spec §7.9, §49.3). Under the mock
configuration the generator produces deterministic template candidates marked
`source.type: "synthetic"`, `model_id: "mock"`, used for tests and demos only (D-022).

## 3. Candidate lifecycle (spec §14.3)

```
CANDIDATE -> NEEDS_REVIEW -> APPROVED -> FROZEN -> SUPERSEDED
     \______________\__________-> REJECTED
```

- **CANDIDATE** — written by `request add`, `author requests`, or `redteam`.
- **NEEDS_REVIEW** — flagged by critics or a reviewer deferral; awaits (second) human review.
- **APPROVED** — carries at least one recorded reviewer decision (the schema forbids APPROVED or
  FROZEN without one, spec §13.5).
- **FROZEN** — hash-stamped into a versioned frozen JSONL by benchmark freeze. **Only FROZEN
  requests may enter a benchmark manifest.**
- **SUPERSEDED / REJECTED** — terminal. Frozen artifacts are never edited in place; a change
  produces a successor in a new benchmark version (spec §41).

## 4. Review workflows (spec §42.7, §14.5)

Batch mode applies one decision to every row of a candidate file:

```bash
uv run lexstab review requests \
  --input dataset/requests/candidate/authoring-run-001.jsonl \
  --reviewer phillip \
  --decision APPROVE \
  --notes "pilot batch, obvious invariants"
```

Interactive mode shows each candidate's text and labels and prompts per request —
`[a]pprove / [r]eject / [s]econd-review / [k]eep`:

```bash
uv run lexstab review requests \
  --input dataset/requests/candidate/authoring-run-001.jsonl \
  --reviewer phillip \
  --interactive
```

Approved rows append to `dataset/requests/approved/support.jsonl`; rejected rows to
`dataset/requests/rejected/rejected.jsonl`; deferred rows remain in the candidate file awaiting a
second review. Every decision is recorded on the request's `validation.reviewers` list.

## 5. Label semantics (spec §13.2)

Every request carries five independent labels. They are never inferred from each other.

**Semantic role**
- `INVARIANT` — same entity, operation, arguments, constraints, and resulting state as the linked
  canonical case.
- `CLARIFICATION` — information is missing, contradictory, or insufficiently discriminating; gold
  behavior is clarification.
- `CONTRAST` — a real semantic difference requires a different operation, argument, or final
  state.
- `REFUSAL` — exactly one requested operation is understood, but a domain rule or state
  precondition prohibits it; gold behavior is refusal without action.

**Adequacy**
- `ADEQUATE` — the request plus frozen context contain enough noncontradictory information to
  identify one formal action and its required arguments (or one policy-grounded refusal) at the
  current turn.
- `INADEQUATE` — at least one required entity, operation, argument, referent, discriminating
  fact, or constraint cannot be recovered.

**Ambiguity**
- `UNAMBIGUOUS` — exactly one canonical interpretation is reasonably supported.
- `AMBIGUOUS` — two or more canonical interpretations remain reasonably supported.

**Adequacy and ambiguity must never be collapsed** (spec §13.2): a request may unambiguously
identify `ESCALATE_INCIDENT` yet be inadequate because the destination tier is missing.

**Expected behavior** — `EXECUTE`, `CLARIFY`, or `REFUSE`.

**Lexical equivalence**
- `INVARIANT` — wording varies while the fully specified application meaning stays fixed.
- `CONTRAST` — wording contains a real semantic change.
- `NOT_APPLICABLE` — the request primarily tests inadequacy, contradiction, or elicitation.

Only requests labeled `ADEQUATE` + `UNAMBIGUOUS` + `EXECUTE` + lexical `INVARIANT` enter the
primary H1 stratum (spec §13.5). The §9.2 adequacy-matrix cell is derived from these frozen labels
plus lexical-distance metadata, not stored as a separate label (D-017).

## 6. Variation axes (spec §13.4)

At least one axis per request, from the controlled vocabulary:

`canonical_terminology`, `entity_synonym`, `operation_synonym`, `syntactic_paraphrase`,
`conversational`, `formal`, `organizational_jargon`, `idiomatic`, `indirect_request`,
`question_form`, `passive_voice`, `self_correction`, `disfluency_preserved`,
`plausible_substitution`, `pronoun_or_coreference`, `implicit_argument`, `missing_entity`,
`missing_operation`, `missing_required_argument`, `contradictory_constraints`, `overloaded_term`,
`context_insufficient`, `policy_prohibited`, `high_lexical_distance`, `minimal_semantic_contrast`,
`typed`, `spoken_human_transcript`, `spoken_asr_transcript`.

New axes require a schema-compatible taxonomy version bump.

## 7. Frozen contexts (spec §13.6)

Adequacy is always relative to available context, so that context is a separate immutable artifact
in `dataset/contexts/`, referenced by `labels.context_id` and hash-verified at freeze. Every
compared boundary architecture must receive equivalent context (spec §46.23). Requests whose
adequacy does not depend on context use the frozen empty context `CTX-EMPTY-001`, so every matrix
cell still records a context hash (D-019). Validate with:

```bash
uv run lexstab contexts validate --root dataset/contexts/frozen
```

## 8. Deduplication (spec §14.6)

The authoring graph applies exact normalized-text matching, case/punctuation-normalized matching,
and token-level similarity. Similarity only *flags* candidates — near-duplicates are routed to
human confirmation, and no similarity measure ever determines semantic equivalence by itself.
Duplicate groups are recorded in the authoring state for review.

## 9. Approval policy (spec §14.5)

For exploratory pilot data: one human reviewer may approve obvious adequate, unambiguous invariant
and contrast cases; every unclear case gets a second review.

For publication-grade data: every invariant/contrast request needs at least two independent
reviews of semantic role, adequacy, ambiguity, and expected behavior; every clarification request
two independent reviews identifying the missing/contradictory/discriminating information; every
refusal request two independent reviews identifying the controlling policy or precondition;
disagreements adjudicated by a third reviewer; reviewers blinded to MUT results; inter-annotator
agreement reported per label dimension.

The two-reviewer flow is **operator process, not automation**: the harness records every reviewer
decision on the artifact (`validation.reviewers`) and exports the decisions for agreement analysis
via `lexstab.authoring.reviewer_agreement_export`, which flattens
request/reviewer/decision/label rows for external inter-annotator statistics. Run reviews under
different `--reviewer` IDs and use deferral (`[s]econd-review` or omitting a batch decision) to
hold candidates for the second reviewer.

## 10. Rendering discovery, review, and freezing (spec §15, §42.8)

Discovery is blind naming: the prompt shows definitions and positive/negative examples, never
candidate labels; each sample runs in a fresh context; only development material is used
(spec §22.2), and discovered renderings are frozen before any downstream testing (spec §49.4).

```bash
uv run lexstab discover renderings \
  --operations ESCALATE_INCIDENT,REASSIGN_INCIDENT,CLOSE_INCIDENT \
  --execution-model-role execution_primary \
  --samples 50 \
  --models config/models.local.yaml \
  --output dataset/renderings/candidate/discovery-001.jsonl
```

The command prints, per operation, the modal normalized term, convergence rate, and term entropy
(normalization rules per spec §38.8), and writes candidate rendering artifacts with full discovery
provenance (model ID, prompt, sample counts). Review candidates into the approved corpus
(`dataset/renderings/approved/support.jsonl`) separately from requests:

```bash
uv run lexstab review renderings \
  --input dataset/renderings/candidate/discovery-001.jsonl \
  --reviewer phillip \
  --decision APPROVE
```

Renderings reference canonical IDs but never redefine them, must not add or omit required
arguments, and are frozen into the benchmark by the freeze step below (spec §15.3).

## 11. Benchmark freeze (spec §16.2, §42.10)

Freezing turns the approved corpora (`dataset/requests/approved/`,
`dataset/renderings/approved/`, `dataset/procedures/approved/`, plus domain, cases, contexts, and
interfaces) into an immutable versioned manifest:

```bash
uv run lexstab benchmark freeze \
  --version 0.1.0 \
  --split-config dataset/splits \
  --output dataset/manifests/benchmark-v0.1.0.json

uv run lexstab benchmark verify --manifest dataset/manifests/benchmark-v0.1.0.json
```

Freeze validates every schema and cross-reference, recomputes gold state transitions in the
simulator, confirms every selected artifact is APPROVED and every context-dependent adequacy label
references a frozen context, stamps SHA-256 content hashes and a root hash over the sorted
inventory, writes frozen copies read-only, and **refuses to overwrite an existing version** unless
the development-only `--dev-overwrite` flag is passed (recorded in the manifest; D-006, D-007).
Note the harness derives the freeze source from the repository's `dataset/` tree; there is no
`--source` flag (deviation from the illustrative command in spec §42.10, which §42 permits).

## 12. Versioning rules (spec §41)

Benchmark artifacts use semantic versioning:

- **Major** — canonical ontology changes incompatibly; metric definitions change materially;
  adequacy/ambiguity/semantic-role/lexical-equivalence labels change meaning; primary task or gold
  behavior changes; the meaning of a P/LP condition changes.
- **Minor** — new approved cases or requests; compatible new operation families; promoted
  regression cases; new renderings; new compatible procedures or action interfaces. A gold-label
  change requires at least a minor bump and a list of affected IDs.
- **Patch** — metadata/documentation corrections and hash or provenance repairs that do not change
  executable meaning.

Each version records a changelog (added/removed/changed artifacts, reasons, reviewer approvals,
comparability impact; spec §41.1). **No retroactive score replacement** (spec §41.2): when a
benchmark error is found, publish a corrected version, mark old results as affected, recompute or
re-run under the new version, and never replace the old artifact while keeping its version number.
