# Procedures and action interfaces

Reusable procedures and the two action boundaries (generic proposal, typed tool) are independent
frozen artifacts of the progressive-formalization track (spec §15.4–15.6, §33). A procedure says
*how* to carry out an already-resolved operation; it never redefines *which* operation the user
requested.

## 1. Procedure authoring: `lexstab procedure add` (spec §42.9)

```bash
uv run lexstab procedure add \
  --operation ESCALATE_INCIDENT \
  --input docs/procedures/escalate-support.md \
  --output dataset/procedures/approved/SKILL_ESCALATE_INCIDENT_V1.json \
  --reviewer phillip
```

`--input` (optional) is a Markdown or JSON source whose non-heading lines become procedure steps;
without it the command generates the default two-step template (check preconditions, propose the
action) from the operation contract. The resulting artifact carries `procedure_id`
(`SKILL_<OPERATION>_V1`), version, `applies_to_operation_ids`, `required_inputs`, `steps`,
`forbidden_behaviors`, an `evaluation_contract` of registered observable checks, the
`generic-action-proposal.v1` output contract, and `human_authored` provenance. Model-generated
procedures require separate review and provenance (spec §15.4).

## 2. Review and freeze: `lexstab procedure freeze` (spec §42.9)

Procedures are created, reviewed, and frozen independently from request generation. The `add`
command records the reviewer and writes into the approved corpus; freezing merges approved files
into one frozen JSONL with stamped content hashes:

```bash
uv run lexstab procedure freeze \
  --input dataset/procedures/approved \
  --output dataset/procedures/frozen/support-v0.1.0.jsonl

uv run lexstab procedures validate --root dataset/procedures/frozen
```

The benchmark freeze then pins the frozen procedure file and its hashes into the manifest; every
run manifest additionally records per-procedure hashes so P3/P4 byte-identity is auditable.

## 3. Procedure constraints (spec §15.4)

- A procedure must reference one or more registered canonical operations.
- **Required inputs must be a subset** of the case, canonical resolution, shared context, or known
  state available to every relevant comparison condition.
- **No smuggled information**: a procedure must not carry organization knowledge, policy facts, or
  argument values the control condition does not receive, unless information addition is the named
  experimental variable (see §46.28 — procedures that supply case-specific missing information are
  rejected).
- **P3 and P4 must use the exact same frozen procedure bytes.** The harness enforces this by
  building both conditions from one frozen artifact and recording its hash in the run manifest.
- Procedure ID, version, content hash, selection logic, and prompt placement are logged per cell.
- Every claimed adherence metric maps to registered observable event/output/state predicates in
  `evaluation_contract`; the harness never infers that an unobserved internal reasoning step
  occurred (spec §38.11).
- Human-authored procedures are the default; the experimental object is the frozen content and
  invocation contract, not any product-specific skill packaging.

## 4. Packaging controls: inline versus packaged (spec §33.9 item 5, §46.29)

Whether procedure content is delivered inline in the prompt or through skill-style packaging is a
required ablation, because a packaging loader can change system prompts, context placement, or
metadata and have its effect misattributed to the procedure content. The decision is carried in
each matrix cell's `procedure_packaging` field (`"inline"`, `"packaged"`, or `"none"`), written to
`runs/<id>/matrix.jsonl` and echoed in score metadata. Primary paired comparisons use only inline
gold-selected cells; the packaged-versus-inline delta is reported separately in
`metrics.json → component_ablations` ("procedure packaging (inline vs packaged skill)") with
byte-equivalent instruction content where possible. Similarly, `procedure_selection`
(`"gold"` — deterministic registry lookup — versus `"runtime"` — router/MUT selection) is a cell
field, and the two modes are never averaged together (spec §33.8): gold-selected succeeding while
runtime-selected fails indicates a discovery/routing problem, not procedure content.

## 5. Generic proposals versus typed tools: `lexstab interfaces build` (spec §15.5, §42.9)

Both action boundaries are generated from the single canonical operation registry, so they cannot
drift apart (spec §46.30):

```bash
uv run lexstab interfaces build \
  --operations dataset/domain/operations.json \
  --generic-output dataset/interfaces/generic-action-proposal.json \
  --typed-output dataset/interfaces/typed-tools/support.jsonl
```

- The **generic action-proposal contract** (`GENERIC_ACTION_PROPOSAL_V1`,
  `generic-action-proposal.v1`) is the JSON schema
  `{decision: ACT|CLARIFY|REFUSE, operation_id, arguments, question, reason_code}` used by P0–P3
  (and LP0–LP2). It is a scoring boundary without native tool-selection affordances; a
  deterministic adapter validates the proposal, maps `operation_id` to the simulator function, and
  records parse, mapping, precondition, and state-transition results.
- The **typed tool contract** (`TYPED_SUPPORT_TOOLS_V1`) gives P4/LP3 a registered capability per
  operation whose name, argument schema, preconditions, and simulator effect match the generic
  proposal exactly; argument-schema and description hashes are recorded.

Comparability rules (spec §15.6): P0–P3 share identical proposal bytes and parsing logic; P3 and
P4 receive identical canonical state, procedure content, domain facts, and model parameters; the
typed interface must not contain extra examples, policy guidance, or hidden defaults;
generic-proposal parse errors and typed-tool validation errors remain distinct result categories;
both paths call the same deterministic simulator transition.

## 6. What `interfaces compare` verifies (spec §42.9)

```bash
uv run lexstab interfaces compare \
  --generic dataset/interfaces/generic-action-proposal.json \
  --typed dataset/interfaces/typed-tools/support.jsonl
```

The comparison verifies operation coverage (every registered operation appears in both
boundaries), argument equivalence (names, types, required fields, constraints), preconditions, and
simulator mappings, and measures description/terminology overlap between the two boundaries
(reported so tool-description wording effects can be separated, spec §46.7, §46.30). Run it after
every rebuild and before benchmark freeze.

## 7. Optional MCP configuration (spec §33.5; D-023)

The default P4 implementation is a **local registered typed-tool contract backed by the
simulator** — the spec's stated default; a live MCP server is optional and not shipped. An
MCP-style capability export can be produced alongside the local contracts:

```bash
uv run lexstab interfaces build \
  --operations dataset/domain/operations.json \
  --generic-output dataset/interfaces/generic-action-proposal.json \
  --typed-output dataset/interfaces/typed-tools/support.jsonl \
  --mcp-output dataset/interfaces/mcp/support-capabilities.jsonl
```

This emits MCP-style capability definitions (`MCP_SUPPORT_CAPABILITIES_V1`) with recorded hashes,
consumable through the same validation path. **The local typed-tool baseline is mandatory before
any MCP interpretation** (spec §33.5): an MCP condition may be added as a second interface
condition but must not replace the local baseline, and any MCP result must first be compared with
the equivalent local typed-tool contract before attributing anything to the protocol rather than
to schema exposure, transport, or capability discovery (spec §15.5, §46.31). Model selection
errors, capability-discovery errors, and transport/protocol errors are separate action-boundary
error categories (spec §38.11).

## 8. Information-parity checks (spec §33.10)

Every progressive-formalization condition must receive the same task-relevant domain facts unless
information addition is explicitly the named variable. Enforcement points:

- The progressive-formalization graph contains the node `verify_information_parity`
  (`src/lexstab/graphs/progressive_formalization.py`), which runs after artifact loading and
  before condition selection on every cell.
- Every P-ladder result records an `information_parity` stage containing a hash of the domain
  rules, known state, and shared context supplied to that condition. P3 and P4 receive the same
  shared context inside their known-state section, so parity can be verified from stored traces.
- `evaluation.formalization_accounting.require_information_parity_check: true` in the run config
  (`config/run.example.yaml`) and `progressive_formalization.require_information_parity_check` in
  the threshold config (`config/thresholds.example.yaml`) keep the check load-bearing for CI.
- The track dry-run (`lexstab run --track progressive_formalization --dry-run`) reports procedure
  and interface hashes and which conditions use runtime versus gold canonical intent, so parity
  can be audited before spending money (spec §42.14).
- `P2F_CANONICAL_FACTS_PROPOSAL` is the procedure information-parity control. It receives the
  procedure's required inputs, constraints, forbidden behaviors, and output contract in sorted,
  unordered form, with the procedure ID, title, step IDs, and step order removed. The P2-to-P2F
  comparison estimates the effect of added information; P2F-to-P3 estimates the incremental
  effect of the named procedure and sequential structure (spec §46.28).

Prompt tokens and placement are recorded per invocation because procedures and tool schemas change
context length (spec §33.10, §46.8).
