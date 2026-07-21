# lexstab — LLM lexical stability and canonical ontology testing harness

A reproducible, provider-agnostic evaluation system implementing
`llm-lexical-stability-harness-implementation-spec.md` (spec version 1.2.0). The research question
the harness exists to test is (spec §1):

> Where should linguistic flexibility end in an agentic system?

The architectural maxim under investigation is:

> Flexible language. Stable ontology. Formal action.

That maxim is a **design hypothesis, not a conclusion the harness is allowed to assume**. The
system is required to be capable of producing evidence against it (spec §1, §2).

## What the harness is

`lexstab` measures whether application-equivalent natural-language requests produce repeatably
different downstream behavior from a pinned language model, and — more distinctively — whether a
stable model-facing lexical rendering still matters *after* the application meaning has been fixed
as canonical state (the B-Gold versus C-Gold comparison, spec §47.7). Around that core it runs:

- a request-adequacy and intent-elicitation track, so missing information is never miscounted as
  lexical instability (spec §9.2, R1);
- an architecture ladder from a strong direct baseline (A1) through runtime canonicalization and
  stable renderings (spec §9.3);
- a progressive-formalization ladder (P0–P4) and natural-language-persistence conditions
  (LP0/LP0B/LP0BV/LP0G/LP1-LP3) that locate where formalization earns its keep (spec §33);
- semantic-memory ablations, an adaptive red team, and a regression suite (spec §17, §32).

Execution is scored by a deterministic state simulator, not by string match or an LLM judge
(spec §35). Datasets, prompts, procedures, and interfaces are frozen, hashed, and versioned before
any benchmark run (spec §16).

## Epistemic posture

The project starts from practitioner observations, not an established theory of model cognition
(spec §2). Three commitments follow:

1. **The harness must be able to produce evidence against its own hypothesis.** It must be as
   capable of showing that a direct frontier model is sufficient (H10, the overengineering null) as
   of showing that canonicalization or lexical stabilization helps (spec §51).
2. **Null results are first-class.** Reports must publish negative and null results, may conclude
   "no tested formalization transition earned its complexity", and must not suppress Pattern G/L
   outcomes (spec §43.3, §44.4, §49.14).
3. **No claims about model internals.** "Model-native vocabulary" and similar phrases are
   operational shorthand for observable behavior, never mechanistic claims (spec §2.3, §47.8).

Rival explanations (request inadequacy, R1; procedure/interface dominance, R2) are tested as
genuine competitors, not error categories to be dismissed.

## Quick start (mocked, no credentials, no cost)

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) (docs/DECISIONS.md D-002, D-021).

```bash
export PATH="$HOME/.local/bin:$PATH"
uv sync --frozen
uv run lexstab doctor
```

A frozen starter benchmark already exists at `dataset/manifests/benchmark-v0.1.0.json`, so a full
end-to-end smoke run works immediately against the deterministic mock provider:

```bash
uv run lexstab run --config config/run.smoke.yaml
uv run lexstab evaluate --run runs/<id>
uv run lexstab report --run runs/<id>
```

`lexstab run` prints the generated run ID (`runs/run-<hex>` by default; pass `--run-id` to choose
one). The report lands at `runs/<id>/report.md` and `report.html`; an example run is checked in at
`runs/smoke-0001/`.

> **Mocked runs are wiring smoke tests. They are never research evidence.** Runs whose execution
> role uses the `mock` provider are stamped `mocked: true` and `baseline_eligible: false` in the
> run manifest, and every report is banner-labeled accordingly (spec §17.4, §46.26; decision
> D-009). Nothing produced by `config/models.mock.yaml` may be reported for or against any
> hypothesis.

## Configuring real providers

Paid model calls happen only when the operator supplies credentials and explicitly runs a command;
nothing in the harness calls a provider implicitly.

```bash
cp .env.example .env                                   # credentials + exact model IDs
cp config/models.example.yaml config/models.local.yaml # role -> provider/model mapping
cp config/run.example.yaml config/run.local.yaml       # run configuration
```

Fill `.env` with API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`) and
**exact provider model identifiers** (`EXECUTION_MODEL_ID`, `CANONICALIZER_MODEL_ID`, …). Model
IDs must be exact pinned identifiers, never marketing aliases such as "Opus" or "latest"
(spec §19.4). Secrets belong in `.env` (git-ignored), never in YAML (spec §19.3). Then verify and
estimate cost before spending anything:

```bash
uv run lexstab doctor --models config/models.local.yaml --run config/run.local.yaml --ping
uv run lexstab run --config config/run.local.yaml --dry-run
```

See `docs/RUNBOOK.md` for the complete operator sequence.

## Repository layout

| Path | Contents |
|---|---|
| `llm-lexical-stability-harness-implementation-spec.md` | The authoritative specification (v1.2.0) |
| `src/lexstab/` | Python package: CLI, providers, graphs, simulator, evaluators, metrics, reporting |
| `schemas/` | JSON Schemas (Draft 2020-12) for every artifact type |
| `prompts/` | Versioned prompt templates with `PROMPT_ID` headers (spec §22) |
| `dataset/domain/` | Canonical entities, operations, policies, plus versioned ontology sources such as `v0.2.0/` and `v0.2.1/` |
| `dataset/cases/` | Canonical cases with gold state transitions; corrected benchmark versions may use versioned source directories |
| `dataset/requests/` | `candidate/`, `approved/`, `frozen/`, `rejected/` request corpora |
| `dataset/contexts/`, `dataset/renderings/`, `dataset/procedures/`, `dataset/interfaces/` | Frozen contexts, model-facing renderings, reusable procedures, action interfaces |
| `dataset/memory/`, `dataset/grammar/`, `dataset/code/`, `dataset/modality/`, `dataset/elicitation/` | Memory-ablation and auxiliary-experiment corpora |
| `dataset/splits/` | `development` / `validation` / `test` case splits |
| `dataset/manifests/` | Immutable benchmark and regression-suite manifests |
| `config/` | Example and mock model/run/threshold configuration |
| `runs/` | One append-only directory per run (manifest, traces, scores, metrics, report, charts) |
| `docs/` | Operator documentation (below) and `DECISIONS.md` |
| `tests/` | Unit, contract, integration, and regression tests (all offline) |
| `scripts/` | Dataset build helpers |

## Documentation

- `docs/RUNBOOK.md` — installation, credentials, cost estimation, smoke/full/track runs,
  evaluation, reporting, red team, regression, recovery, LangSmith.
- `docs/DATASET_AUTHORING.md` — manual and synthetic request creation, review, labels, freezing,
  benchmark versioning.
- `docs/PROCEDURES_AND_INTERFACES.md` — reusable procedures, packaging controls, generic proposals
  versus typed tools, optional MCP, information parity.
- `docs/RESULTS_GUIDE.md` — every metric family, `metrics.json` keys, interpretation patterns A–L,
  the complexity decision.
- `docs/METHODOLOGY.md` — hypotheses H1–H12 and rivals R1/R2, tracks, statistics, the confound
  register, prior-art positioning.
- `docs/DECISIONS.md` — logged implementation decisions (D-001 … D-024) where the spec was
  underspecified.
- `IMPLEMENTATION_STATUS.md` — what is implemented versus operator work remaining.
