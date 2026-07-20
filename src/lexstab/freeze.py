"""Benchmark freeze: approved artifacts -> immutable versioned manifest (§16.2).

Freeze validates every schema and cross-reference, recomputes gold transitions
in the simulator, stamps content hashes, writes frozen copies read-only, and
refuses to overwrite an existing version without a development override.
"""

from __future__ import annotations

import copy
import datetime as _dt
from pathlib import Path
from typing import Any

from lexstab import models
from lexstab.artifacts import (
    ArtifactError,
    DomainStore,
    is_read_only,
    json_read,
    json_write,
    jsonl_read,
    jsonl_write,
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
    verify_frozen_file,
    verify_frozen_rows,
)
from lexstab.hashing import hash_file, hash_json_artifact, root_hash, stamp_content_hash
from lexstab.prompts import PromptLibrary
from lexstab.simulators.support_domain import recompute_gold_state

RUN_CLOCK_PLACEHOLDER = "<run_clock>"

PROMPT_VERSIONS = {
    "direct_executor": "direct-executor.v1",
    "direct_clarify_executor": "direct-clarify-executor.v1",
    "adequacy_assessor": "adequacy-assessor.v1",
    "clarification_resolver": "clarification-resolver.v1",
    "canonicalizer": "canonicalizer.v1",
    "canonical_executor": "canonical-executor.v1",
    "rendered_executor": "rendered-executor.v1",
    "action_proposal_executor": "action-proposal-executor.v1",
    "procedure_executor": "procedure-executor.v1",
    "language_handoff": "language-handoff.v1",
    "triage": "triage.v1",
    "policy": "policy.v1",
    "planner": "planner.v1",
    "executor": "executor.v1",
}


class FreezeError(Exception):
    pass


def _freeze_rows(rows: list[dict], status_field_path: str = "validation.status") -> list[dict]:
    """Set validation status FROZEN and stamp content hashes."""
    frozen = []
    for row in rows:
        row = copy.deepcopy(row)
        node = row
        *parents, leaf = status_field_path.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        if node.get(leaf) not in ("APPROVED", "FROZEN"):
            raise FreezeError(
                f"artifact {row.get('request_id') or row.get('rendering_id') or row.get('procedure_id')} "
                f"is not APPROVED (status={node.get(leaf)})"
            )
        node[leaf] = "FROZEN"
        frozen.append(stamp_content_hash(row))
    return frozen


def _stamp_rows(rows: list[dict]) -> list[dict]:
    return [stamp_content_hash(copy.deepcopy(row)) for row in rows]


def freeze_benchmark(
    root: Path,
    version: str,
    *,
    benchmark_id: str = "lexstab-support",
    description: str = "Support-domain lexical stability benchmark",
    dev_overwrite: bool = False,
    created_at: str | None = None,
) -> Path:
    manifest_path = root / "dataset" / "manifests" / f"benchmark-v{version}.json"
    if manifest_path.exists() and not dev_overwrite:
        raise FreezeError(
            f"manifest version {version} already exists; freezing requires a new "
            "version (development-only --dev-overwrite exists for local iteration)"
        )

    domain = DomainStore.load(root)
    cases = load_cases(root)

    def _approved_rows(directory: str) -> list[dict]:
        rows: list[dict] = []
        base = root / directory
        for file in sorted(base.glob("*.jsonl")):
            rows.extend(jsonl_read(file))
        for file in sorted(base.glob("*.json")):
            rows.append(json_read(file))
        return rows

    request_source_rows = _approved_rows("dataset/requests/approved")
    rendering_source_rows = _approved_rows("dataset/renderings/approved")
    procedure_source_rows = _approved_rows("dataset/procedures/approved")

    requests = {}
    for row in request_source_rows:
        request = models.NLRequest.model_validate(row)
        if request.request_id in requests:
            raise FreezeError(f"duplicate request_id {request.request_id}")
        requests[request.request_id] = request
    contexts = load_contexts(root, "dataset/contexts/approved.jsonl")
    renderings = {
        row["rendering_id"]: models.Rendering.model_validate(row)
        for row in rendering_source_rows
    }
    procedures = {}
    for row in procedure_source_rows:
        procedure = models.Procedure.model_validate(row)
        procedures[procedure.procedure_id] = procedure
    interfaces = load_interfaces(
        root,
        ["dataset/interfaces/generic-action-proposal.json", "dataset/interfaces/typed-tools/support.jsonl"],
    )
    memory_path = root / "dataset" / "memory" / "glossaries" / "support.jsonl"
    memory = load_memory(root, memory_path.relative_to(root)) if memory_path.exists() else {}
    elicitation_path = root / "dataset" / "elicitation" / "approved.jsonl"
    elicitation = (
        load_elicitation_cases(root, elicitation_path.relative_to(root))
        if elicitation_path.exists()
        else {}
    )

    errors = referential_integrity(domain, cases, requests, contexts, renderings, procedures, interfaces)
    for ecase in elicitation.values():
        if ecase.linked_case_id not in cases:
            errors.append(f"elicitation {ecase.elicitation_case_id}: unknown case {ecase.linked_case_id}")
        if ecase.initial_request_id not in requests:
            errors.append(
                f"elicitation {ecase.elicitation_case_id}: unknown request {ecase.initial_request_id}"
            )
    if errors:
        raise FreezeError("referential integrity failed:\n" + "\n".join(errors))

    # Recompute gold transitions (spec §16.2 item 3; run-clock placeholder D-026).
    for case in cases.values():
        if case.gold.decision == models.GoldDecision.ACT:
            accepted, resulting, detail = recompute_gold_state(
                domain, case.initial_state, case.gold.tool, case.gold.arguments, RUN_CLOCK_PLACEHOLDER
            )
            if not accepted:
                raise FreezeError(f"case {case.case_id}: gold transition rejected: {detail}")
            if resulting != case.gold.resulting_state:
                raise FreezeError(
                    f"case {case.case_id}: stored gold resulting_state does not match "
                    "the recomputed simulator transition"
                )

    # Confirm splits reference known cases and split at family level (§37.3).
    splits: dict[str, list[str]] = {}
    family_to_split: dict[str, str] = {}
    for split_name in ("development", "validation", "test"):
        split_doc = json_read(root / "dataset" / "splits" / f"{split_name}.json")
        ids = split_doc["case_ids"]
        for case_id in ids:
            if case_id not in cases:
                raise FreezeError(f"split {split_name}: unknown case {case_id}")
            family = cases[case_id].family_id
            if family_to_split.setdefault(family, split_name) != split_name:
                raise FreezeError(
                    f"family {family} appears in multiple splits "
                    f"({family_to_split[family]} and {split_name})"
                )
        splits[split_name] = ids
    assigned = {cid for ids in splits.values() for cid in ids}
    unassigned = set(cases) - assigned
    if unassigned:
        raise FreezeError(f"cases not assigned to any split: {sorted(unassigned)}")

    # Write frozen copies with FROZEN status and content hashes.
    frozen_dirs = {
        "requests": root / "dataset" / "requests" / "frozen",
        "contexts": root / "dataset" / "contexts" / "frozen",
        "renderings": root / "dataset" / "renderings" / "frozen",
        "procedures": root / "dataset" / "procedures" / "frozen",
    }
    suffix = f"support-v{version}.jsonl"

    def _write_frozen(path: Path, rows: list[dict]) -> None:
        if path.exists() and is_read_only(path) and not dev_overwrite:
            raise FreezeError(f"frozen artifact already exists: {path}")
        if path.exists():
            path.chmod(0o644)
        jsonl_write(path, rows)
        make_read_only(path)

    request_rows = _freeze_rows(request_source_rows)
    _write_frozen(frozen_dirs["requests"] / suffix, request_rows)

    context_rows = _stamp_rows(jsonl_read(root / "dataset" / "contexts" / "approved.jsonl"))
    _write_frozen(frozen_dirs["contexts"] / suffix, context_rows)

    rendering_rows = _freeze_rows(rendering_source_rows)
    _write_frozen(frozen_dirs["renderings"] / suffix, rendering_rows)

    procedure_rows = _freeze_rows(procedure_source_rows)
    _write_frozen(frozen_dirs["procedures"] / suffix, procedure_rows)

    interface_files = [
        "dataset/interfaces/generic-action-proposal.json",
        "dataset/interfaces/typed-tools/support.jsonl",
    ]
    memory_files = ["dataset/memory/glossaries/support.jsonl"] if memory else []
    elicitation_files = ["dataset/elicitation/approved.jsonl"] if elicitation else []

    prompts = PromptLibrary(root / "prompts")
    prompt_errors = prompts.validate_all()
    if prompt_errors:
        raise FreezeError("prompt validation failed:\n" + "\n".join(prompt_errors))

    inventory: dict[str, str] = {}
    tracked_files = [
        "dataset/domain/entities.json",
        "dataset/domain/operations.json",
        "dataset/domain/policies.json",
        "dataset/domain/initial-state.json",
        *[f"dataset/cases/support/{case_id}.json" for case_id in sorted(cases)],
        f"dataset/requests/frozen/{suffix}",
        f"dataset/contexts/frozen/{suffix}",
        f"dataset/renderings/frozen/{suffix}",
        f"dataset/procedures/frozen/{suffix}",
        *interface_files,
        *memory_files,
        *elicitation_files,
    ]
    for relative in tracked_files:
        inventory[relative] = hash_file(root / relative)

    manifest: dict[str, Any] = {
        "schema_version": models.SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "benchmark_version": version,
        "created_at": created_at or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "description": description,
        "artifact_root_hash": root_hash(inventory),
        "ontology": {
            "entities_file": "dataset/domain/entities.json",
            "operations_file": "dataset/domain/operations.json",
            "policies_file": "dataset/domain/policies.json",
            "initial_state_file": "dataset/domain/initial-state.json",
            "hashes": {
                "entities": inventory["dataset/domain/entities.json"],
                "operations": inventory["dataset/domain/operations.json"],
                "policies": inventory["dataset/domain/policies.json"],
                "initial_state": inventory["dataset/domain/initial-state.json"],
            },
        },
        "cases": {
            "files": [f"dataset/cases/support/{case_id}.json" for case_id in sorted(cases)],
            "ids": sorted(cases),
            "hashes": {
                case_id: inventory[f"dataset/cases/support/{case_id}.json"] for case_id in sorted(cases)
            },
        },
        "requests": {
            "files": [f"dataset/requests/frozen/{suffix}"],
            "ids": sorted(requests),
            "hashes": {f"dataset/requests/frozen/{suffix}": inventory[f"dataset/requests/frozen/{suffix}"]},
        },
        "renderings": {
            "files": [f"dataset/renderings/frozen/{suffix}"],
            "ids": sorted(renderings),
            "hashes": {f"dataset/renderings/frozen/{suffix}": inventory[f"dataset/renderings/frozen/{suffix}"]},
        },
        "procedures": {
            "files": [f"dataset/procedures/frozen/{suffix}"],
            "ids": sorted(procedures),
            "hashes": {f"dataset/procedures/frozen/{suffix}": inventory[f"dataset/procedures/frozen/{suffix}"]},
        },
        "action_interfaces": {
            "files": interface_files,
            "ids": sorted(interfaces),
            "hashes": {file: inventory[file] for file in interface_files},
        },
        "contexts": {
            "files": [f"dataset/contexts/frozen/{suffix}"],
            "ids": sorted(contexts),
            "hashes": {f"dataset/contexts/frozen/{suffix}": inventory[f"dataset/contexts/frozen/{suffix}"]},
        },
        "semantic_memory": {
            "files": memory_files,
            "ids": sorted(memory),
            "hashes": {file: inventory[file] for file in memory_files},
        },
        "elicitation_cases": {
            "files": elicitation_files,
            "ids": sorted(elicitation),
            "hashes": {file: inventory[file] for file in elicitation_files},
        },
        "prompt_versions": dict(PROMPT_VERSIONS),
        "prompt_hashes": prompts.hashes(),
        "splits": splits,
        "allowed_architectures": models.ARCHITECTURES,
        "validation": {
            "schema_valid": True,
            "referential_integrity_valid": True,
            "state_transitions_valid": True,
        },
        "development_overwrite": bool(dev_overwrite),
        "changelog": [
            {"version": version, "change": "frozen from approved artifacts", "approved_by": "operator"}
        ],
    }
    models.BenchmarkManifest.model_validate(manifest)
    if manifest_path.exists():
        manifest_path.chmod(0o644)
    json_write(manifest_path, manifest)
    make_read_only(manifest_path)
    return manifest_path


# ---------------------------------------------------------------- loading


class FrozenBenchmark:
    """Loaded, hash-verified frozen benchmark (all consumers go through this)."""

    def __init__(self, root: Path, manifest_path: Path):
        self.root = root
        self.manifest_path = manifest_path
        raw = json_read(manifest_path)
        if "suite_id" in raw:
            self._load_regression_overlay(raw)
            return
        self.manifest = models.BenchmarkManifest.model_validate(raw)

        # Verify every artifact hash before use (spec §13.7, §49.2).
        all_sections = [
            self.manifest.ontology["hashes"],
            self.manifest.cases.hashes,
            self.manifest.requests.hashes,
            self.manifest.renderings.hashes,
            self.manifest.procedures.hashes,
            self.manifest.action_interfaces.hashes,
            self.manifest.contexts.hashes,
            self.manifest.semantic_memory.hashes,
            self.manifest.elicitation_cases.hashes,
        ]
        ontology_files = {
            "entities": "dataset/domain/entities.json",
            "operations": "dataset/domain/operations.json",
            "policies": "dataset/domain/policies.json",
            "initial_state": "dataset/domain/initial-state.json",
        }
        for key, expected in self.manifest.ontology["hashes"].items():
            verify_frozen_file(root, ontology_files[key], expected)
        for case_id, expected in self.manifest.cases.hashes.items():
            verify_frozen_file(root, f"dataset/cases/support/{case_id}.json", expected)
        for section in all_sections[2:]:
            for relative, expected in section.items():
                verify_frozen_file(root, relative, expected)

        self.domain = DomainStore.load(root)
        self.cases = load_cases(root)
        self.cases = {cid: self.cases[cid] for cid in self.manifest.cases.ids}
        self.requests: dict[str, models.NLRequest] = {}
        for file in self.manifest.requests.files:
            rows = jsonl_read(root / file)
            verify_frozen_rows(rows, file)
            self.requests.update(load_requests(root, file))
        self.contexts: dict[str, models.FrozenContext] = {}
        for file in self.manifest.contexts.files:
            self.contexts.update(load_contexts(root, file))
        self.renderings: dict[str, models.Rendering] = {}
        for file in self.manifest.renderings.files:
            rows = jsonl_read(root / file)
            verify_frozen_rows(rows, file)
            self.renderings.update(load_renderings(root, file))
        self.procedures: dict[str, models.Procedure] = {}
        for file in self.manifest.procedures.files:
            rows = jsonl_read(root / file)
            verify_frozen_rows(rows, file)
            self.procedures.update(load_procedures(root, file))
        self.interfaces = load_interfaces(root, list(self.manifest.action_interfaces.files))
        self.memory: dict[str, models.SemanticMemoryRecord] = {}
        for file in self.manifest.semantic_memory.files:
            self.memory.update(load_memory(root, file))
        self.elicitation: dict[str, models.ElicitationCase] = {}
        for file in self.manifest.elicitation_cases.files:
            self.elicitation.update(load_elicitation_cases(root, file))

    def _load_regression_overlay(self, suite: dict[str, Any]) -> None:
        """Load a promoted regression suite over its frozen base benchmark.

        The embedded, human-approved requests become the only request stimuli,
        while cases, ontology, contexts, procedures, renderings, interfaces,
        and prompts remain hash-verified artifacts from the pinned base.
        """
        required = {
            "suite_id", "suite_version", "base_benchmark_manifest",
            "request_ids", "requests", "request_hashes",
        }
        missing = sorted(required - set(suite))
        if missing:
            raise ArtifactError(f"regression suite missing fields: {missing}")
        base_path = self.root / suite["base_benchmark_manifest"]
        if base_path.resolve() == self.manifest_path.resolve():
            raise ArtifactError("regression suite cannot use itself as its base benchmark")
        base = FrozenBenchmark(self.root, base_path)
        requests: dict[str, models.NLRequest] = {}
        for row in suite["requests"]:
            request_id = row.get("request_id")
            expected_hash = suite["request_hashes"].get(request_id)
            actual_hash = hash_json_artifact(row)
            if expected_hash != actual_hash:
                raise ArtifactError(
                    f"regression request {request_id} hash mismatch"
                )
            request = models.NLRequest.model_validate(row)
            if request.request_id not in suite["request_ids"]:
                raise ArtifactError(
                    f"regression request {request.request_id} is not listed in request_ids"
                )
            if request.case_id not in base.cases:
                raise ArtifactError(
                    f"regression request {request.request_id}: unknown case {request.case_id}"
                )
            if request.labels.context_id and request.labels.context_id not in base.contexts:
                raise ArtifactError(
                    f"regression request {request.request_id}: unknown context "
                    f"{request.labels.context_id}"
                )
            requests[request.request_id] = request
        if set(requests) != set(suite["request_ids"]):
            raise ArtifactError("regression suite request_ids do not match embedded requests")

        # Copy every verified base artifact, then replace only the stimulus set
        # and the split case lists. All split names resolve to the promoted case
        # set so CLI split selection remains deterministic for regression runs.
        self.domain = base.domain
        promoted_case_ids = sorted({request.case_id for request in requests.values()})
        self.cases = {case_id: base.cases[case_id] for case_id in promoted_case_ids}
        self.requests = requests
        self.contexts = base.contexts
        self.renderings = base.renderings
        self.procedures = base.procedures
        self.interfaces = base.interfaces
        self.memory = base.memory
        self.elicitation = {
            key: value for key, value in base.elicitation.items()
            if value.linked_case_id in self.cases
            and value.initial_request_id in self.requests
        }
        suite_hash = hash_json_artifact(suite)
        combined_hash = root_hash({
            "base_benchmark": base.manifest.artifact_root_hash,
            "regression_suite": suite_hash,
        })
        requests_section = base.manifest.requests.model_copy(
            update={"ids": sorted(requests)}
        )
        self.manifest = base.manifest.model_copy(
            deep=True,
            update={
                "benchmark_id": suite["suite_id"],
                "benchmark_version": suite["suite_version"],
                "artifact_root_hash": combined_hash,
                "cases": base.manifest.cases.model_copy(update={"ids": promoted_case_ids}),
                "requests": requests_section,
                "splits": {
                    name: list(promoted_case_ids)
                    for name in ("development", "validation", "test")
                },
                "changelog": [
                    *base.manifest.changelog,
                    {
                        "version": suite["suite_version"],
                        "change": "regression-suite overlay",
                        "approved_by": suite.get("promotion", {}).get("approved_by", "operator"),
                    },
                ],
            },
        )

    def requests_for_case(self, case_id: str) -> list[models.NLRequest]:
        return [req for req in self.requests.values() if req.case_id == case_id]

    def context_for_request(self, request: models.NLRequest) -> models.FrozenContext:
        ctx_id = request.labels.context_id or "CTX-EMPTY-001"
        ctx = self.contexts.get(ctx_id)
        if ctx is None:
            raise ArtifactError(f"request {request.request_id}: context {ctx_id} not in benchmark")
        return ctx

    def procedure_for_operation(self, operation_id: str) -> models.Procedure | None:
        for procedure in self.procedures.values():
            if operation_id in procedure.applies_to_operation_ids:
                return procedure
        return None

    def rendering_for_operation(
        self, operation_id: str, category: str = "CANONICAL_LABEL"
    ) -> models.Rendering | None:
        for rendering in sorted(self.renderings.values(), key=lambda r: r.rendering_id):
            if rendering.operation_id == operation_id and rendering.category.value == category:
                return rendering
        return None
