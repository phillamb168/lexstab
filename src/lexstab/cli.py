"""lexstab command-line interface (spec §42).

Every documented command lives here. Authoring commands never run benchmarks;
`lexstab run` never invokes authoring (§G7). Paid provider calls happen only
when the operator explicitly configures real providers and runs a command
that requires them.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import typer

from lexstab import models
from lexstab.artifacts import (
    ArtifactError,
    DomainStore,
    find_repo_root,
    json_read,
    jsonl_read,
    jsonl_write,
    json_write,
    load_cases,
    load_contexts,
    load_elicitation_cases,
    load_interfaces,
    load_memory,
    load_procedures,
    load_renderings,
    load_requests,
    make_read_only,
    referential_integrity,
)
from lexstab.config import (
    load_env_file,
    load_models_config,
    load_run_config,
    validate_role_separation,
)

app = typer.Typer(help="LLM lexical stability and canonical ontology testing harness")
schema_app = typer.Typer(help="JSON Schema management")
benchmark_app = typer.Typer(help="Benchmark freeze and verification")
request_app = typer.Typer(help="Manual request management")
author_app = typer.Typer(help="Dataset authoring (separate from benchmark execution)")
review_app = typer.Typer(help="Human review workflows")
discover_app = typer.Typer(help="Model-facing rendering discovery")
procedure_app = typer.Typer(help="Reusable procedure management")
interfaces_app = typer.Typer(help="Action-interface artifacts")
regression_app = typer.Typer(help="Regression suite management")
experiment_app = typer.Typer(help="Auxiliary experiments (grammar, code, modality)")
app.add_typer(schema_app, name="schema")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(request_app, name="request")
app.add_typer(author_app, name="author")
app.add_typer(review_app, name="review")
app.add_typer(discover_app, name="discover")
app.add_typer(procedure_app, name="procedure")
app.add_typer(interfaces_app, name="interfaces")
app.add_typer(regression_app, name="regression")
app.add_typer(experiment_app, name="experiment")


def _root() -> Path:
    root = find_repo_root()
    load_env_file(root / ".env")
    return root


def _runs_root(root: Path) -> Path:
    configured = Path(os.environ.get("LEXSTAB_RUNS_DIR", "runs"))
    return configured if configured.is_absolute() else root / configured


def _fail(message: str) -> None:
    typer.secho(f"ERROR: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _ok(message: str) -> None:
    typer.secho(message, fg=typer.colors.GREEN)


@app.command("prompt-size-report")
def prompt_size_report_cmd(
    output: str = typer.Option(
        "runs/prompt-size-v0.2.1.json", "--output",
        help="JSON report path; a Markdown companion is written beside it",
    ),
    target_median_percent: float = typer.Option(2.0, "--target-median-percent"),
    warning_percent: float = typer.Option(5.0, "--warning-percent"),
) -> None:
    """Measure LP0B reminder overhead from a fixed fixture without model calls."""
    root = _root()
    from lexstab.promptsize import build_prompt_size_report, render_prompt_size_markdown

    report = build_prompt_size_report(
        root,
        target_median_percent=target_median_percent,
        per_stage_warning_percent=warning_percent,
    )
    destination = root / output
    json_write(destination, report)
    markdown_path = destination.with_suffix(".md")
    markdown_path.write_text(render_prompt_size_markdown(report), encoding="utf-8")
    summary = report["summary"]
    _ok(
        f"prompt-size report: median delta {summary['median_delta_percent']:.2f}% "
        f"with {len(summary['stages_above_warning'])} stage warning(s); "
        "provider calls: 0"
    )
    typer.echo(f"  JSON: {destination}")
    typer.echo(f"  Markdown: {markdown_path}")


# ---------------------------------------------------------------- doctor (§42.3)


@app.command()
def doctor(
    models_path: str = typer.Option("config/models.mock.yaml", "--models"),
    run_path: str = typer.Option("config/run.smoke.yaml", "--run"),
    ping: bool = typer.Option(False, "--ping", help="Send one minimal non-benchmark request per configured real provider"),
) -> None:
    """Verify configuration, role separation, schemas, and output directories."""
    root = _root()
    problems: list[str] = []
    try:
        run_config = load_run_config(root / run_path)
        from lexstab.run import required_model_roles

        needed_roles = required_model_roles(run_config)
        models_config = load_models_config(
            root / models_path,
            strict_env=True,
            strict_roles=needed_roles,
        )
    except Exception as exc:
        _fail(f"model or run config: {exc}")
        return
    violations = validate_role_separation(models_config)
    if violations and not models_config.separation_policy.allow_role_overlap:
        problems.extend(violations)
    for name in sorted(needed_roles):
        role = models_config.roles.get(name)
        if role is None or not role.enabled:
            problems.append(f"required role {name}: not enabled")
        elif not role.model_id:
            problems.append(f"role {name}: model ID unresolved (set its environment variable)")
    try:
        manifest_path = root / run_config.benchmark_manifest
        if not manifest_path.exists():
            problems.append(f"benchmark manifest missing: {run_config.benchmark_manifest}")
    except Exception as exc:
        problems.append(f"run config: {exc}")
    from lexstab.schemagen import check_all

    stale = check_all(root / "schemas")
    if stale:
        problems.append(f"schemas out of date with models: {stale} (run `lexstab schema generate`)")
    from lexstab.prompts import PromptLibrary

    prompt_errors = PromptLibrary(root / "prompts").validate_all()
    problems.extend(prompt_errors)
    runs_dir = root / "runs"
    if not os.access(runs_dir, os.W_OK):
        problems.append(f"runs directory not writable: {runs_dir}")
    if ping:
        from lexstab.providers.registry import build_provider

        for name in ("execution_primary",):
            role = models_config.roles.get(name)
            if role and role.enabled and role.provider != "mock" and role.model_id:
                adapter = build_provider(role)
                record = adapter.invoke(
                    role=name, model_id=role.model_id,
                    messages=[{"role": "system", "content": "Reply with OK."}],
                    tools=None, response_schema=None,
                    parameters={
                        **role.parameters,
                        "max_tokens": min(int(role.parameters.get("max_tokens", 8)), 16),
                    },
                    metadata={"run_id": "doctor", "cell_id": "doctor-ping",
                              "timestamp": "", "response_kind": "ping"},
                )
                if record.parse_status == "error":
                    problems.append(f"provider ping failed for {name}: {record.parse_error}")
                else:
                    _ok(f"provider ping ok for {name} ({record.provider}:{record.requested_model_id})")
    if os.environ.get("LANGSMITH_TRACING", "").lower() == "true" and not os.environ.get("LANGSMITH_API_KEY"):
        problems.append("LANGSMITH_TRACING=true but LANGSMITH_API_KEY is empty")
    if problems:
        for problem in problems:
            typer.secho(f"  ✗ {problem}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    _ok("doctor: all checks passed")


# ---------------------------------------------------------------- schema commands


@schema_app.command("validate")
def schema_validate(all_: bool = typer.Option(True, "--all")) -> None:
    """Validate that committed schemas are valid Draft 2020-12 and match models."""
    root = _root()
    import jsonschema

    from lexstab.schemagen import SCHEMA_MAP, check_all

    for filename in SCHEMA_MAP:
        schema = json_read(root / "schemas" / filename)
        jsonschema.Draft202012Validator.check_schema(schema)
    stale = check_all(root / "schemas")
    if stale:
        _fail(f"schemas differ from Pydantic models: {stale}")
    _ok(f"{len(SCHEMA_MAP)} schemas valid and in sync with runtime models")


@schema_app.command("generate")
def schema_generate() -> None:
    root = _root()
    from lexstab.schemagen import write_all

    written = write_all(root / "schemas")
    _ok(f"wrote {len(written)} schemas")


# ---------------------------------------------------------------- validate commands (§42.4)


@app.command("domain")
def domain_validate(
    action: str = typer.Argument("validate"),
    root_dir: str = typer.Option("dataset/domain", "--root"),
) -> None:
    root = _root()
    try:
        domain = DomainStore.load(root, root_dir)
    except ArtifactError as exc:
        _fail(str(exc))
        return
    _ok(f"domain valid: {len(domain.entities)} entities, {len(domain.operations)} operations, "
        f"{len(domain.policies)} policies")


@app.command("cases")
def cases_validate(
    action: str = typer.Argument("validate"),
    root_dir: str = typer.Option("dataset/cases/support", "--root"),
    domain_root: str = typer.Option("dataset/domain", "--domain-root"),
) -> None:
    root = _root()
    try:
        domain = DomainStore.load(root, domain_root)
        cases = load_cases(root, root_dir)
        from lexstab.artifacts import validate_case_against_domain

        for case in cases.values():
            validate_case_against_domain(case, domain)
    except ArtifactError as exc:
        _fail(str(exc))
        return
    _ok(f"{len(cases)} cases valid")


def _validate_jsonl(loader, root: Path, path: str, label: str) -> None:
    target = root / path
    if target.is_dir():
        files = sorted(target.glob("*.jsonl"))
    else:
        files = [target] if target.exists() else []
    if not files:
        _fail(f"no {label} files under {path}")
        return
    total = 0
    for file in files:
        try:
            total += len(loader(root, file.relative_to(root)))
        except ArtifactError as exc:
            _fail(str(exc))
            return
    _ok(f"{total} {label} valid across {len(files)} file(s)")


@app.command("requests")
def requests_validate(action: str = typer.Argument("validate"),
                      root_dir: str = typer.Option("dataset/requests/frozen", "--root")) -> None:
    _validate_jsonl(load_requests, _root(), root_dir, "requests")


@app.command("contexts")
def contexts_validate(action: str = typer.Argument("validate"),
                      root_dir: str = typer.Option("dataset/contexts/frozen", "--root")) -> None:
    _validate_jsonl(load_contexts, _root(), root_dir, "contexts")


@app.command("renderings")
def renderings_validate(action: str = typer.Argument("validate"),
                        root_dir: str = typer.Option("dataset/renderings/frozen", "--root")) -> None:
    _validate_jsonl(load_renderings, _root(), root_dir, "renderings")


@app.command("memory")
def memory_validate(action: str = typer.Argument("validate"),
                    root_dir: str = typer.Option("dataset/memory", "--root")) -> None:
    root = _root()
    files = sorted((root / root_dir).rglob("*.jsonl"))
    total = 0
    for file in files:
        try:
            total += len(load_memory(root, file.relative_to(root)))
        except ArtifactError as exc:
            _fail(str(exc))
            return
    _ok(f"{total} memory records valid across {len(files)} file(s)")


@app.command("procedures")
def procedures_validate(action: str = typer.Argument("validate"),
                        root_dir: str = typer.Option("dataset/procedures/frozen", "--root")) -> None:
    _validate_jsonl(load_procedures, _root(), root_dir, "procedures")


@interfaces_app.command("validate")
def interfaces_validate(root_dir: str = typer.Option("dataset/interfaces", "--root")) -> None:
    root = _root()
    paths = ["dataset/interfaces/generic-action-proposal.json",
             "dataset/interfaces/typed-tools/support.jsonl"]
    try:
        interfaces = load_interfaces(root, paths)
    except ArtifactError as exc:
        _fail(str(exc))
        return
    _ok(f"{len(interfaces)} interfaces valid")


@app.command("integrity")
def integrity_check(
    domain_root: str = typer.Option("dataset/domain", "--domain-root"),
    cases_root: str = typer.Option("dataset/cases/support", "--cases-root"),
    interfaces_root: str = typer.Option("dataset/interfaces", "--interfaces-root"),
) -> None:
    """Full referential-integrity sweep over approved artifacts."""
    root = _root()
    domain = DomainStore.load(root, domain_root)
    cases = load_cases(root, cases_root)
    requests = load_requests(root, "dataset/requests/approved/support.jsonl")
    contexts = load_contexts(root, "dataset/contexts/approved.jsonl")
    renderings = load_renderings(root, "dataset/renderings/approved/support.jsonl")
    procedures = load_procedures(root, "dataset/procedures/approved/support.jsonl")
    interfaces = load_interfaces(root, [
        str(Path(interfaces_root) / "generic-action-proposal.json"),
        str(Path(interfaces_root) / "typed-tools/support.jsonl"),
    ])
    errors = referential_integrity(domain, cases, requests, contexts, renderings, procedures, interfaces)
    if errors:
        for error in errors:
            typer.secho(f"  ✗ {error}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    _ok("referential integrity valid")


# ---------------------------------------------------------------- request add (§42.5)


@request_app.command("add")
def request_add(
    case: str = typer.Option(..., "--case"),
    text: str = typer.Option(..., "--text"),
    semantic_role: str = typer.Option(..., "--semantic-role"),
    adequacy: str = typer.Option(..., "--adequacy"),
    ambiguity: str = typer.Option(..., "--ambiguity"),
    expected_behavior: str = typer.Option(..., "--expected-behavior"),
    lexical_equivalence: str = typer.Option(..., "--lexical-equivalence"),
    axes: str = typer.Option(..., "--axes", help="comma-separated variation axes"),
    source: str = typer.Option("human", "--source"),
    creator: str = typer.Option("operator", "--creator"),
    context_id: str = typer.Option(None, "--context-id"),
    missing_information: str = typer.Option("", "--missing-information", help="comma-separated"),
    contrast_operation: str = typer.Option(None, "--contrast-operation"),
    refusal_operation: str = typer.Option(None, "--refusal-operation"),
    refusal_policy: str = typer.Option(None, "--refusal-policy"),
    output: str = typer.Option("dataset/requests/candidate/manual.jsonl", "--output"),
) -> None:
    """Add a human-authored request without invoking any model (§14.4)."""
    root = _root()
    from lexstab.authoring import add_human_request

    try:
        record = add_human_request(
            root,
            case_id=case, text=text, semantic_role=semantic_role, adequacy=adequacy,
            ambiguity=ambiguity, expected_behavior=expected_behavior,
            lexical_equivalence=lexical_equivalence,
            axes=[axis.strip() for axis in axes.split(",") if axis.strip()],
            creator=creator, context_id=context_id,
            missing_information=[item.strip() for item in missing_information.split(",") if item.strip()],
            contrast_operation_id=contrast_operation,
            refusal_operation_id=refusal_operation,
            refusal_policy_reference=refusal_policy,
            output=root / output,
        )
    except Exception as exc:
        _fail(str(exc))
        return
    _ok(f"added {record['request_id']} (status CANDIDATE) -> {output}")


# ---------------------------------------------------------------- author (§42.6)


def _authoring_context(root: Path, models_path: str, run_id: str):
    from lexstab.authoring import AuthoringContext
    from lexstab.prompts import PromptLibrary
    from lexstab.providers.registry import build_provider

    authoring_roles = {
        "authoring_generator", "authoring_equivalence_critic",
        "authoring_adversarial_critic", "failure_analyst",
    }
    models_config = load_models_config(
        root / models_path, strict_env=True, strict_roles=authoring_roles
    )
    violations = validate_role_separation(models_config)
    if violations and not models_config.separation_policy.allow_role_overlap:
        _fail("role separation policy violated:\n" + "\n".join(violations))
    providers = {}
    for name in ("authoring_generator", "authoring_equivalence_critic",
                 "authoring_adversarial_critic", "failure_analyst"):
        role = models_config.roles.get(name)
        if role and role.enabled:
            providers[name] = build_provider(role)
    return AuthoringContext(
        root=root,
        domain=DomainStore.load(root),
        cases=load_cases(root),
        prompts=PromptLibrary(root / "prompts"),
        models_config=models_config,
        providers=providers,
        authoring_run_id=run_id,
    )


@author_app.command("requests")
def author_requests_cmd(
    cases: str = typer.Option("dataset/cases/support", "--cases"),
    models_path: str = typer.Option("config/models.mock.yaml", "--models", "--config"),
    axes: str = typer.Option("entity_synonym,operation_synonym,indirect_request,idiomatic", "--axes"),
    count_per_axis: int = typer.Option(4, "--count-per-axis"),
    case_ids: str = typer.Option("", "--case-ids", help="comma-separated; default all"),
    output: str = typer.Option(..., "--output"),
    use_graph: bool = typer.Option(True, "--graph/--procedural"),
) -> None:
    """Generate synthetic candidate requests (never invoked by `lexstab run`)."""
    root = _root()
    run_id = f"authoring-{uuid.uuid4().hex[:8]}"
    ctx = _authoring_context(root, models_path, run_id)
    existing_path = root / "dataset" / "requests" / "approved" / "support.jsonl"
    existing = jsonl_read(existing_path) if existing_path.exists() else []
    selected = [cid.strip() for cid in case_ids.split(",") if cid.strip()] or sorted(ctx.cases)
    axis_list = [axis.strip() for axis in axes.split(",") if axis.strip()]
    if use_graph:
        from lexstab.graphs.authoring import author_with_graph

        state = author_with_graph(ctx, case_ids=selected, axes=axis_list,
                                  count_per_axis=count_per_axis, existing=existing)
    else:
        from lexstab.authoring import author_requests

        state = author_requests(ctx, case_ids=selected, axes=axis_list,
                                count_per_axis=count_per_axis, existing=existing)
    from lexstab.authoring import write_candidates

    count = write_candidates(state, root / output)
    _ok(f"wrote {count} candidates to {output} "
        f"({len(state['human_review_required'])} need human review, "
        f"{len(state['rejected_candidates'])} rejected by critics)")


# ---------------------------------------------------------------- review (§42.7)


@review_app.command("requests")
def review_requests_cmd(
    input_path: str = typer.Option(..., "--input"),
    reviewer: str = typer.Option("operator", "--reviewer"),
    decision: str = typer.Option(None, "--decision", help="Batch decision for all rows: APPROVE/REJECT"),
    notes: str = typer.Option("", "--notes"),
    interactive: bool = typer.Option(False, "--interactive"),
) -> None:
    """Review candidate requests: approve, edit, reject, or defer."""
    root = _root()
    from lexstab.authoring import review_candidates

    path = root / input_path
    if not path.exists():
        _fail(f"no candidate file at {input_path}")
        return
    decisions: dict[str, str] = {}
    if interactive:
        for row in jsonl_read(path):
            labels = row["labels"]
            provenance = row.get("provenance") or {}
            typer.echo(f"\n[{row['request_id']}] case {row['case_id']}")
            typer.echo(f"  text: {row['text']}")
            typer.echo("  proposed labels:")
            typer.echo(f"    semantic role: {labels.get('semantic_role')}")
            typer.echo(f"    expected behavior: {labels.get('expected_behavior')}")
            typer.echo(f"    lexical equivalence: {labels.get('lexical_equivalence')}")
            typer.echo(f"    adequacy: {labels.get('adequacy')}")
            typer.echo(f"    ambiguity: {labels.get('ambiguity')}")
            typer.echo(
                "    variation axes: "
                + (", ".join(labels.get("variation_axes") or []) or "none")
            )
            if labels.get("missing_information"):
                typer.echo(
                    "    missing information: "
                    + ", ".join(labels["missing_information"])
                )
            if labels.get("contrast_operation_id"):
                typer.echo(
                    f"    contrast operation: {labels['contrast_operation_id']}"
                )
                typer.echo(
                    "    contrast arguments: "
                    + json.dumps(
                        labels.get("contrast_arguments") or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            supersedes = provenance.get("supersedes_request_ids") or []
            if supersedes:
                typer.echo("  supersedes on approval: " + ", ".join(supersedes))
            answer = typer.prompt(
                "  decision [a]pprove / [r]eject / [s]econd-review / [d]efer",
                default="d",
            )
            decisions[row["request_id"]] = {
                "a": "APPROVE",
                "r": "REJECT",
                "s": "NEEDS_SECOND_REVIEW",
                "d": "NEEDS_SECOND_REVIEW",
            }.get(answer.strip().lower(), None) or "NEEDS_SECOND_REVIEW"
    result = review_candidates(
        path,
        reviewer_id=reviewer,
        decisions=decisions or None,
        default_decision=decision,
        notes=notes,
        approved_output=root / "dataset" / "requests" / "approved" / "support.jsonl",
        rejected_output=root / "dataset" / "requests" / "rejected" / "rejected.jsonl",
    )
    _ok(f"review complete: {result}")


# ---------------------------------------------------------------- discovery (§42.8)


@discover_app.command("renderings")
def discover_renderings_cmd(
    operations: str = typer.Option(..., "--operations"),
    models_path: str = typer.Option("config/models.mock.yaml", "--models"),
    samples: int = typer.Option(50, "--samples"),
    role: str = typer.Option("execution_primary", "--execution-model-role"),
    output: str = typer.Option(..., "--output"),
    domain_root: str = typer.Option("dataset/domain", "--domain-root"),
    checkpoint: str = typer.Option(
        None,
        "--checkpoint",
        help="Optional resumable per-sample JSONL path; defaults beside --output",
    ),
) -> None:
    """Blind lexical-convergence discovery (development material only, §22.2)."""
    root = _root()
    from lexstab.discovery import DiscoveryError, discover_renderings
    from lexstab.providers.registry import build_provider

    models_config = load_models_config(
        root / models_path, strict_env=True, strict_roles={role}
    )
    provider = build_provider(models_config.role(role))
    try:
        renderings = discover_renderings(
            root, DomainStore.load(root, domain_root), models_config, provider,
            operation_ids=[op.strip() for op in operations.split(",") if op.strip()],
            samples=samples, role=role, output=root / output,
            checkpoint=(root / checkpoint if checkpoint else None),
            progress=typer.echo,
        )
    except DiscoveryError as exc:
        _fail(str(exc))
        return
    for rendering in renderings:
        dist = rendering["_distribution"]
        typer.echo(
            f"  {rendering['operation_id']}: modal={dist['modal_term']!r} "
            f"convergence={dist['convergence_rate']} entropy={dist['term_entropy']} "
            f"definition_only={dist['definition_only_rate']}"
        )
    _ok(f"wrote {len(renderings)} candidate renderings to {output}")


@review_app.command("renderings")
def review_renderings_cmd(
    input_path: str = typer.Option(..., "--input"),
    reviewer: str = typer.Option("operator", "--reviewer"),
    decision: str = typer.Option(
        None,
        "--decision",
        help="Batch decision for all rows: APPROVE, REJECT, or DEFER",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        help="Review each rendering independently",
    ),
    show_request_variants: bool = typer.Option(
        True,
        "--show-request-variants/--hide-request-variants",
        help="Show approved human-language variants for the same canonical operation",
    ),
    max_request_variants: int = typer.Option(
        8,
        "--max-request-variants",
        min=1,
        help="Maximum equivalent human-language examples displayed per operation",
    ),
    domain_root: str = typer.Option("dataset/domain", "--domain-root"),
    cases_root: str = typer.Option("dataset/cases/support", "--cases-root"),
) -> None:
    """Review discovered renderings individually or with an explicit batch decision."""
    root = _root()
    from lexstab.discovery import DiscoveryError, review_rendering_candidates

    source = root / input_path
    if not source.exists():
        _fail(f"no candidate file at {input_path}")
        return
    if not interactive and decision is None:
        _fail("choose --interactive or provide an explicit --decision")
        return

    decisions = {}
    if interactive:
        domain = DomainStore.load(root, domain_root)
        cases = load_cases(root, cases_root)
        approved_request_rows = []
        for request_file in sorted((root / "dataset" / "requests" / "approved").glob("*.jsonl")):
            approved_request_rows.extend(jsonl_read(request_file))
        active_requests = [
            request
            for request in approved_request_rows
            if (request.get("validation") or {}).get("status") in ("APPROVED", "FROZEN")
        ]
        approved_rendering_rows = jsonl_read(
            root / "dataset" / "renderings" / "approved" / "support.jsonl"
        )
        for row in jsonl_read(source):
            discovery = row.get("discovery") or {}
            distribution = row.get("_distribution") or {}
            operation_id = row["operation_id"]
            operation = domain.operations[operation_id]
            canonical_rendering = next(
                (
                    rendering
                    for rendering in approved_rendering_rows
                    if rendering.get("operation_id") == operation_id
                    and rendering.get("category") == "CANONICAL_LABEL"
                    and (rendering.get("validation") or {}).get("status")
                    in ("APPROVED", "FROZEN")
                ),
                None,
            )
            operation_case_ids = {
                case_id
                for case_id, case in cases.items()
                if case.canonical.operation_id == operation_id
            }
            operation_requests = [
                request for request in active_requests
                if request.get("case_id") in operation_case_ids
            ]
            equivalent_requests = [
                request for request in operation_requests
                if (request.get("labels") or {}).get("expected_behavior") == "EXECUTE"
                and (request.get("labels") or {}).get("lexical_equivalence") == "INVARIANT"
                and (request.get("labels") or {}).get("adequacy") == "ADEQUATE"
                and (request.get("labels") or {}).get("ambiguity") == "UNAMBIGUOUS"
            ]
            control_counts = {}
            for request in operation_requests:
                behavior = (request.get("labels") or {}).get("expected_behavior", "UNKNOWN")
                control_counts[behavior] = control_counts.get(behavior, 0) + 1
            typer.echo(f"\n[{row['operation_id']}] {row['rendering_id']}")
            typer.echo(f"  operation: {operation.description or operation.display_name}")
            if canonical_rendering:
                typer.echo(f"  canonical label: {canonical_rendering.get('label')}")
                typer.echo(f"  canonical template: {canonical_rendering.get('template')}")
            typer.echo(f"  label: {row.get('label')}")
            typer.echo(f"  template: {row.get('template')}")
            typer.echo(
                "  convergence: "
                f"{discovery.get('convergence_rate')}  "
                f"entropy: {discovery.get('term_entropy')}  "
                f"definition-only: {discovery.get('definition_only_rate')}"
            )
            typer.echo(
                "  term counts: "
                + json.dumps(discovery.get("term_counts") or distribution.get("alternatives") or {})
            )
            if show_request_variants:
                typer.echo(
                    f"  approved request corpus: {len(operation_requests)} total "
                    f"{json.dumps(control_counts, sort_keys=True)}"
                )
                typer.echo(
                    f"  equivalent human-language variants: {len(equivalent_requests)}"
                )
                for request in equivalent_requests[:max_request_variants]:
                    labels = request.get("labels") or {}
                    axes = ", ".join(labels.get("variation_axes") or [])
                    typer.echo(
                        f"    - [{request['case_id']} | {axes}] {request['text']}"
                    )
                hidden = len(equivalent_requests) - max_request_variants
                if hidden > 0:
                    typer.echo(f"    ... {hidden} more equivalent variants not shown")
                typer.echo(
                    "  Review scope: this decision changes only the discovered model-facing "
                    "rendering; the requests above are unchanged reference stimuli."
                )
            answer = typer.prompt(
                "  decision [a]pprove / [r]eject / [d]efer",
                default="d",
            )
            decisions[row["rendering_id"]] = {
                "a": "APPROVE",
                "r": "REJECT",
                "d": "DEFER",
            }.get(answer.strip().lower(), "DEFER")
    try:
        result = review_rendering_candidates(
            source,
            root / "dataset" / "renderings" / "approved" / "support.jsonl",
            root / "dataset" / "renderings" / "rejected" / "rejected.jsonl",
            reviewer=reviewer,
            decisions=decisions or None,
            default_decision=decision,
        )
    except DiscoveryError as exc:
        _fail(str(exc))
        return
    _ok(f"rendering review complete: {result}")


# ---------------------------------------------------------------- procedures (§42.9)


@procedure_app.command("add")
def procedure_add(
    operation: str = typer.Option(..., "--operation"),
    input_path: str = typer.Option(None, "--input", help="Markdown/JSON procedure source"),
    output: str = typer.Option(..., "--output"),
    reviewer: str = typer.Option("operator", "--reviewer"),
) -> None:
    """Create a procedure artifact for one canonical operation."""
    root = _root()
    domain = DomainStore.load(root)
    if operation not in domain.operations:
        _fail(f"unknown operation {operation}")
        return
    op = domain.operations[operation]
    steps = [
        {"step_id": "CHECK_PRECONDITIONS",
         "instruction": "Confirm every registered precondition of the resolved operation against the known state before proposing action."},
        {"step_id": "PROPOSE_ACTION",
         "instruction": f"Propose {operation} using exactly the resolved entity and arguments without changing unrelated state."},
    ]
    if input_path:
        source = (root / input_path).read_text()
        steps = [{"step_id": f"STEP_{index}", "instruction": line.strip("-# ").strip()}
                 for index, line in enumerate(source.splitlines(), 1)
                 if line.strip() and not line.startswith("#")] or steps
        steps = [{"step_id": f"S{index:02d}_" + step["step_id"], "instruction": step["instruction"]}
                 for index, step in enumerate(steps, 1)]
    import datetime as _dt

    record = {
        "schema_version": models.SCHEMA_VERSION,
        "procedure_id": f"SKILL_{operation}_V1",
        "procedure_version": "1.0.0",
        "title": f"{op.display_name} procedure",
        "applies_to_operation_ids": [operation],
        "required_inputs": ["entity_id", "known_state"] + sorted(
            name for name, spec in op.arguments.items()
            if spec.required and not name.endswith("_id")
        ),
        "steps": steps,
        "forbidden_behaviors": ["invent_missing_arguments", "change_canonical_operation",
                                "bypass_failed_preconditions"],
        "evaluation_contract": {
            "registered_checks": ["PRECONDITIONS_ENFORCED", "CANONICAL_ARGUMENTS_PRESERVED",
                                  "UNRELATED_STATE_UNCHANGED"],
            "forbidden_operation_ids": [op.primary_contrast] if op.primary_contrast else [],
            "required_observable_events": ["single_action_proposal"],
        },
        "output_contract": "generic-action-proposal.v1",
        "validation": {"status": "APPROVED", "reviewed_by": [reviewer],
                       "approved_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "provenance": {"source_type": "human_authored", "content_hash": None},
    }
    models.Procedure.model_validate(record)
    json_write(root / output, record)
    _ok(f"wrote procedure {record['procedure_id']} to {output}")


@procedure_app.command("freeze")
def procedure_freeze(
    input_dir: str = typer.Option("dataset/procedures/approved", "--input"),
    output: str = typer.Option(..., "--output"),
) -> None:
    """Merge approved procedure files into one frozen JSONL (hashes stamped)."""
    root = _root()
    from lexstab.hashing import stamp_content_hash

    rows: list[dict] = []
    source = root / input_dir
    for file in sorted(source.glob("*.jsonl")):
        rows.extend(jsonl_read(file))
    for file in sorted(source.glob("*.json")):
        rows.append(json_read(file))
    frozen = []
    seen = set()
    for row in rows:
        if row["procedure_id"] in seen:
            continue
        seen.add(row["procedure_id"])
        row = dict(row)
        row["validation"] = {**row["validation"], "status": "FROZEN"}
        frozen.append(stamp_content_hash(row))
    for row in frozen:
        models.Procedure.model_validate(row)
    target = root / output
    if target.exists() and not os.access(target, os.W_OK):
        _fail(f"frozen procedure file already exists and is immutable: {output}")
        return
    jsonl_write(target, frozen)
    make_read_only(target)
    _ok(f"froze {len(frozen)} procedures to {output}")


# ---------------------------------------------------------------- interfaces (§42.9)


@interfaces_app.command("build")
def interfaces_build(
    operations: str = typer.Option("dataset/domain/operations.json", "--operations"),
    generic_output: str = typer.Option("dataset/interfaces/generic-action-proposal.json", "--generic-output"),
    typed_output: str = typer.Option("dataset/interfaces/typed-tools/support.jsonl", "--typed-output"),
    mcp_output: str = typer.Option(None, "--mcp-output"),
) -> None:
    """Generate both action boundaries from the canonical operation registry."""
    root = _root()
    from lexstab.interfaces import build_generic_interface, build_mcp_interface, build_typed_interface

    operations_path = Path(operations)
    if operations_path.name != "operations.json":
        _fail("--operations must name an operations.json inside a complete domain directory")
        return
    domain = DomainStore.load(root, operations_path.parent)
    json_write(root / generic_output, build_generic_interface(domain))
    jsonl_write(root / typed_output, [build_typed_interface(domain)])
    if mcp_output:
        jsonl_write(root / mcp_output, [build_mcp_interface(domain)])
    _ok("interfaces built from operation registry")


@interfaces_app.command("compare")
def interfaces_compare(
    generic: str = typer.Option("dataset/interfaces/generic-action-proposal.json", "--generic"),
    typed: str = typer.Option("dataset/interfaces/typed-tools/support.jsonl", "--typed"),
    domain_root: str = typer.Option("dataset/domain", "--domain-root"),
) -> None:
    """Verify generic/typed equivalence: coverage, arguments, simulator mapping."""
    root = _root()
    from lexstab.interfaces import compare_interfaces

    domain = DomainStore.load(root, domain_root)
    generic_doc = json_read(root / generic)
    typed_doc = jsonl_read(root / typed)[0]
    report = compare_interfaces(domain, generic_doc, typed_doc)
    typer.echo(json.dumps(report, indent=2))
    if not report["equivalent"]:
        raise typer.Exit(code=1)
    _ok("interfaces equivalent")


# ---------------------------------------------------------------- benchmark freeze (§42.10)


@benchmark_app.command("freeze")
def benchmark_freeze(
    version: str = typer.Option(..., "--version"),
    split_config: str = typer.Option("dataset/splits", "--split-config"),
    output: str = typer.Option(None, "--output"),
    changelog_path: str = typer.Option(None, "--changelog-file"),
    dev_overwrite: bool = typer.Option(False, "--dev-overwrite",
                                       help="DEVELOPMENT ONLY: allow re-freezing an existing version"),
) -> None:
    root = _root()
    from lexstab.freeze import FreezeError, freeze_benchmark

    try:
        changelog = json_read(root / changelog_path) if changelog_path else None
        if changelog is not None and not isinstance(changelog, list):
            raise FreezeError("changelog file must contain a JSON list")
        path = freeze_benchmark(
            root, version, dev_overwrite=dev_overwrite, changelog=changelog
        )
    except (FreezeError, ArtifactError) as exc:
        _fail(str(exc))
        return
    manifest = json_read(path)
    _ok(f"froze benchmark v{version} -> {path.relative_to(root)}")
    typer.echo(f"  root hash: {manifest['artifact_root_hash']}")
    typer.echo(f"  cases: {len(manifest['cases']['ids'])}, requests: {len(manifest['requests']['ids'])}")


@benchmark_app.command("verify")
def benchmark_verify(manifest: str = typer.Option(..., "--manifest")) -> None:
    root = _root()
    from lexstab.freeze import FrozenBenchmark

    try:
        bench = FrozenBenchmark(root, root / manifest)
    except ArtifactError as exc:
        _fail(str(exc))
        return
    _ok(f"benchmark verified: {bench.manifest.benchmark_id} v{bench.manifest.benchmark_version} "
        f"root {bench.manifest.artifact_root_hash[:23]}")


# ---------------------------------------------------------------- run (§42.11-42.14)


@app.command("run")
def run_cmd(
    config: str = typer.Option("config/run.smoke.yaml", "--config"),
    manifest: str = typer.Option(None, "--manifest", help="Override benchmark manifest (e.g. regression suite)"),
    split: str = typer.Option(None, "--split"),
    track: str = typer.Option(None, "--track", help="Enable only this track"),
    conditions: str = typer.Option(None, "--conditions", help="Comma list for progressive_formalization"),
    limit_cases: int = typer.Option(None, "--limit-cases"),
    repetitions: int = typer.Option(None, "--repetitions"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    runner: str = typer.Option("procedural", "--runner", help="procedural | graph"),
    run_id: str = typer.Option(None, "--run-id"),
) -> None:
    """Execute the frozen benchmark matrix (consumes frozen artifacts only)."""
    root = _root()
    from lexstab.config import RunConfig
    from lexstab.run import RunError, build_run_context, dry_run_report, execute_run

    run_config = load_run_config(root / config)
    raw = run_config.raw
    if manifest:
        raw["benchmark_manifest"] = manifest
    if split:
        raw.setdefault("selection", {})["split"] = split
    if limit_cases is not None:
        raw.setdefault("selection", {})["limit_cases"] = limit_cases
    if repetitions is not None:
        raw.setdefault("execution", {})["repetitions"] = repetitions
    if track:
        for name, spec in raw.get("tracks", {}).items():
            spec["enabled"] = name == track
    if conditions:
        wanted = [item.strip() for item in conditions.split(",") if item.strip()]
        formal = raw.setdefault("tracks", {}).setdefault("progressive_formalization", {})
        formal["enabled"] = True
        formal["conditions"] = [c for c in wanted if c.startswith("P")]
        formal["persistence_conditions"] = [c for c in wanted if c.startswith("LP")]
    run_config = RunConfig(
        run_name=raw.get("run_name", "run"), benchmark_manifest=raw["benchmark_manifest"],
        model_config_path=raw.get("model_config", ""), tracks=raw.get("tracks", {}),
        selection=raw.get("selection", {}), execution=raw.get("execution", {}),
        evaluation=raw.get("evaluation", {}), tracing=raw.get("tracing", {}), raw=raw,
    )
    try:
        if dry_run:
            ctx, matrix, _mc = build_run_context(root, run_config)
            report = dry_run_report(matrix, run_config)
            report["benchmark_root_hash"] = ctx.bench.manifest.artifact_root_hash
            report["resolved_execution_model"] = ctx.models_config.role("execution_primary").model_id
            if run_config.tracks.get("progressive_formalization", {}).get("enabled"):
                from lexstab.hashing import sha256_text

                report["procedure_hashes"] = {
                    procedure_id: sha256_text(procedure.model_dump_json())
                    for procedure_id, procedure in sorted(ctx.bench.procedures.items())
                }
                report["interface_hashes"] = {
                    interface_id: sha256_text(interface.model_dump_json())
                    for interface_id, interface in sorted(ctx.bench.interfaces.items())
                }
                report["intent_modes"] = sorted({
                    f"{cell.architecture}:{cell.intent_mode}" for cell in matrix.cells
                    if cell.track == "progressive_formalization"
                })
                transition_costs = {}
                by_arch: dict[str, int] = {}
                for cell in matrix.cells:
                    if cell.track == "progressive_formalization":
                        by_arch[cell.architecture] = by_arch.get(cell.architecture, 0) + 1
                from lexstab.run import INVOCATIONS_PER_ARCH

                ladder = ["P0_RAW_PROPOSAL", "P1_CLARIFY_PROPOSAL", "P2_CANONICAL_PROPOSAL",
                          "P3_CANONICAL_PROCEDURE_PROPOSAL", "P4_CANONICAL_PROCEDURE_TOOL"]
                for arch_a, arch_b in zip(ladder, ladder[1:]):
                    transition_costs[f"{arch_a} -> {arch_b}"] = {
                        "marginal_calls_per_cell": INVOCATIONS_PER_ARCH.get(arch_b, 2)
                        - INVOCATIONS_PER_ARCH.get(arch_a, 2),
                    }
                report["estimated_marginal_transition_costs"] = transition_costs
            typer.echo(json.dumps(report, indent=2))
            return
        cell_runner = None
        if runner == "graph":
            from lexstab.graphs.execution import graph_run_cell

            cell_runner = graph_run_cell
        else:
            from lexstab.runner import run_cell as cell_runner  # type: ignore[assignment]
        run_dir = execute_run(root, run_config, runs_dir=_runs_root(root),
                              run_id=run_id, cell_runner=cell_runner,
                              progress=lambda msg: typer.echo(f"  {msg}"))
    except (RunError, ArtifactError) as exc:
        _fail(str(exc))
        return
    manifest_doc = json_read(run_dir / "run-manifest.json")
    summary_doc = json_read(run_dir / "run-summary.json")
    if not summary_doc.get("healthy", False):
        typer.secho(f"run stopped with {summary_doc.get('status')}: {run_dir}", fg=typer.colors.RED)
        typer.echo(
            f"  provider error calls: {summary_doc.get('provider_error_calls', 0)}  "
            f"length terminations: {summary_doc.get('length_terminated_calls', 0)}  "
            f"aborted cells: {summary_doc.get('aborted_cells', 0)}"
        )
        typer.echo("  artifacts were retained for diagnosis; this run is not baseline-eligible")
        raise typer.Exit(code=1)
    _ok(f"run complete: {run_dir}")
    typer.echo(f"  run id: {manifest_doc['run_id']}")
    typer.echo(f"  benchmark hash: {manifest_doc['benchmark_root_hash'][:23]}")
    typer.echo(f"  matrix cells: {manifest_doc['matrix_cell_count']}")
    typer.echo(
        f"  mocked: {manifest_doc['mocked']}  "
        f"baseline_eligible: {summary_doc['baseline_eligible']}"
    )
    if summary_doc.get("length_terminated_calls"):
        typer.secho(
            f"  warning: {summary_doc['length_terminated_calls']} invocation(s) reached max_tokens",
            fg=typer.colors.YELLOW,
        )
    typer.echo(f"  execution model: {manifest_doc['resolved_roles']['execution_primary']['model_id']}")


# ---------------------------------------------------------------- evaluate / report (§42.15-42.16)


@app.command("evaluate")
def evaluate_cmd(
    run: str = typer.Option(..., "--run"),
    config: str = typer.Option(None, "--config"),
    bootstrap_samples: int = typer.Option(None, "--bootstrap-samples"),
) -> None:
    """Score a stored run without invoking any model."""
    root = _root()
    from lexstab.evaluate import EvaluationError, evaluate_run

    samples = bootstrap_samples
    if samples is None and config:
        samples = int(load_run_config(root / config).evaluation.get("bootstrap_samples", 2000))
    try:
        metrics = evaluate_run(root, root / run, bootstrap_samples=samples)
    except (EvaluationError, ArtifactError) as exc:
        _fail(str(exc))
        return
    _ok(f"evaluated {metrics['run_id']}: {metrics['completion']['scored_cells']} cells scored")


@app.command("report")
def report_cmd(
    run: str = typer.Option(..., "--run"),
    formats: str = typer.Option("markdown,html,csv,parquet,json", "--formats"),
) -> None:
    root = _root()
    from lexstab.reporting.report import generate_report

    paths = generate_report(root, root / run,
                            formats=tuple(f.strip() for f in formats.split(",")))
    _ok(f"generated {len(paths)} report artifacts under {run}")


@app.command("judge")
def judge_cmd(
    run: str = typer.Option(..., "--run"),
    models_path: str = typer.Option("config/models.mock.yaml", "--models"),
    limit: int = typer.Option(None, "--limit"),
) -> None:
    """Optional blinded judge pass over clarification questions (§35.3)."""
    root = _root()
    from lexstab.evaluators.llm_judge import calibration_status, judge_clarifications

    models_config = load_models_config(
        root / models_path, strict_env=True, strict_roles={"evaluation_judge"}
    )
    judged = judge_clarifications(root, root / run, models_config, limit=limit)
    status = calibration_status(root / run)
    label = "calibrated" if status["calibrated"] else f"EXPLORATORY ({status['reason']})"
    _ok(f"judged {len(judged)} clarification questions [{label}]")


@app.command("compare-runs")
def compare_runs_cmd(runs: str = typer.Option(..., "--runs", help="Comma-separated run dirs")) -> None:
    """Experiment 6: compare completed runs of one frozen benchmark across models."""
    root = _root()
    from lexstab.metrics.crossmodel import compare_runs

    run_dirs = [root / item.strip() for item in runs.split(",") if item.strip()]
    try:
        report = compare_runs(run_dirs)
    except ValueError as exc:
        _fail(str(exc))
        return
    typer.echo(json.dumps(report, indent=2))


@review_app.command("human")
def review_human_cmd(
    run: str = typer.Option(..., "--run"),
    cell: str = typer.Option(None, "--cell"),
    decision: str = typer.Option(None, "--decision", help="PASS/FAIL/ESCALATE"),
    reviewer: str = typer.Option("operator", "--reviewer"),
    notes: str = typer.Option("", "--notes"),
    list_queue: bool = typer.Option(False, "--queue", help="List cells awaiting adjudication"),
) -> None:
    """Human adjudication of judge-uncertain cells (§35.5, §49.9)."""
    root = _root()
    from lexstab.evaluators.human_review import pending_review_queue, record_human_review
    from lexstab.evaluators.llm_judge import CLARIFICATION_RUBRIC

    run_dir = root / run
    if list_queue or not cell:
        queue = pending_review_queue(run_dir)
        for row in queue:
            typer.echo(f"  {row['cell_id']}: {row.get('criterion')} -> {row.get('judge')}")
        _ok(f"{len(queue)} cells awaiting human adjudication")
        return
    if not decision:
        _fail("--decision is required when recording a review")
        return
    record = record_human_review(
        run_dir, cell_id=cell, criterion="clarification_usefulness",
        rubric=CLARIFICATION_RUBRIC, reviewer_id=reviewer, decision=decision, notes=notes,
    )
    _ok(f"recorded human review for {record['cell_id']}")


@app.command("langsmith-export")
def langsmith_export_cmd(run: str = typer.Option(..., "--run"),
                         project: str = typer.Option(None, "--project")) -> None:
    root = _root()
    from lexstab.tracing.langsmith import export_run

    result = export_run(root / run, project=project)
    typer.echo(json.dumps(result))


# ---------------------------------------------------------------- redteam (§42.17)


@app.command("redteam")
def redteam_cmd(
    run: str = typer.Option(..., "--run"),
    models_path: str = typer.Option("config/models.mock.yaml", "--models"),
    max_candidates: int = typer.Option(200, "--max-candidates"),
    output: str = typer.Option(..., "--output"),
) -> None:
    """Generate adversarial candidates from a frozen run's failures."""
    root = _root()
    from lexstab.redteam import WARNING, run_redteam

    typer.secho(f"WARNING: {WARNING}", fg=typer.colors.YELLOW)
    ctx = _authoring_context(root, models_path, f"redteam-{uuid.uuid4().hex[:8]}")
    report = run_redteam(ctx, root / run, max_candidates=max_candidates, output=root / output)
    json_write(root / run / "redteam-report.json", report)
    _ok(f"wrote {report['candidates_written']} candidates to {output} "
        f"(frozen run results unchanged)")


# ---------------------------------------------------------------- regression (§42.18, §45.5)


@regression_app.command("promote")
def regression_promote(
    version: str = typer.Option(..., "--version"),
    request_ids: str = typer.Option(..., "--request-ids"),
    corpus: str = typer.Option(..., "--corpus"),
    run_id: str = typer.Option(..., "--run-id"),
    reason: str = typer.Option(..., "--reason"),
    approved_by: str = typer.Option("operator", "--approved-by"),
    base_manifest: str = typer.Option("dataset/manifests/benchmark-v0.1.0.json", "--base-manifest"),
) -> None:
    root = _root()
    from lexstab.regression import RegressionError, promote_to_regression

    try:
        path = promote_to_regression(
            root, version=version,
            request_ids=[rid.strip() for rid in request_ids.split(",") if rid.strip()],
            candidate_corpus=root / corpus, discovering_run_id=run_id,
            reason=reason, approved_by=approved_by, base_benchmark_manifest=base_manifest,
        )
    except (RegressionError, ArtifactError) as exc:
        _fail(str(exc))
        return
    _ok(f"promoted regression suite v{version} -> {path.relative_to(root)}")


@regression_app.command("verify")
def regression_verify(version: str = typer.Option(..., "--version")) -> None:
    root = _root()
    from lexstab.regression import load_regression_suite

    suite = load_regression_suite(root, version)
    _ok(f"regression suite v{version} valid: {len(suite['request_ids'])} promoted requests")


@regression_app.command("check")
def regression_check(
    run: str = typer.Option(..., "--run"),
    thresholds: str = typer.Option("config/thresholds.example.yaml", "--thresholds"),
) -> None:
    """Apply blocking regression gates to a completed, evaluated run."""
    root = _root()
    from lexstab.config import load_thresholds
    from lexstab.regression import check_run_thresholds

    report = check_run_thresholds(root / run, load_thresholds(root / thresholds))
    typer.echo(json.dumps(report, indent=2))
    if not report["passed"]:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------- auxiliary experiments


@experiment_app.command("grammar")
def experiment_grammar(
    dataset: str = typer.Option("dataset/grammar/editing-corpus.jsonl", "--dataset"),
    models_path: str = typer.Option("config/models.mock.yaml", "--models"),
    condition: str = typer.Option("definition_only", "--condition"),
    output: str = typer.Option("runs/grammar-latest.jsonl", "--output"),
) -> None:
    """Experiment 4: grammatical terminology conditions with span scoring."""
    root = _root()
    from lexstab.experiments.grammar import run_grammar_experiment

    result = run_grammar_experiment(root, root / dataset, models_path, condition, root / output)
    typer.echo(json.dumps(result, indent=2))


@experiment_app.command("code")
def experiment_code(
    dataset: str = typer.Option("dataset/code/families.jsonl", "--dataset"),
    models_path: str = typer.Option("config/models.mock.yaml", "--models"),
    output: str = typer.Option("runs/code-latest.jsonl", "--output"),
) -> None:
    """Experiment 5: identifier variants with executable test scoring."""
    root = _root()
    from lexstab.experiments.code import run_code_experiment

    result = run_code_experiment(root, root / dataset, models_path, root / output)
    typer.echo(json.dumps(result, indent=2))


@experiment_app.command("modality")
def experiment_modality(
    dataset: str = typer.Option("dataset/modality/artifact-chains.jsonl", "--dataset"),
    models_path: str = typer.Option("config/models.mock.yaml", "--models"),
    output: str = typer.Option("runs/modality-latest.jsonl", "--output"),
) -> None:
    """Experiment 7: canonical resolution across typed/transcript/ASR artifacts."""
    root = _root()
    from lexstab.experiments.modality import run_modality_experiment

    result = run_modality_experiment(root, root / dataset, models_path, root / output)
    typer.echo(json.dumps(result, indent=2))


@experiment_app.command("canonical-envelope")
def experiment_canonical_envelope(
    manifest: str = typer.Option("dataset/manifests/benchmark-v0.1.0.json", "--manifest"),
    models_path: str = typer.Option("config/models.mock.yaml", "--models"),
    output: str = typer.Option("runs/canonical-envelope-latest.jsonl", "--output"),
    case_ids: str = typer.Option("", "--case-ids"),
) -> None:
    """Diagnostic: vary only the canonical-envelope outcome field label."""
    root = _root()
    from lexstab.experiments.canonical_envelope import run_canonical_envelope_diagnostic

    result = run_canonical_envelope_diagnostic(
        root,
        root / manifest,
        root / models_path,
        root / output,
        case_ids=[item.strip() for item in case_ids.split(",") if item.strip()] or None,
    )
    typer.echo(json.dumps(result, indent=2))


if __name__ == "__main__":
    app()
