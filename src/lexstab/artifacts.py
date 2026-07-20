"""Artifact loading, validation, and lifecycle management.

Every artifact is validated twice: against its JSON Schema (language-neutral
contract) and its Pydantic model (runtime). Referential-integrity checks span
files (spec §12.2, §13.5, §16.2). Frozen artifacts verify hashes before use.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import jsonschema
from pydantic import BaseModel, ValidationError

from lexstab import models
from lexstab.hashing import hash_file, hash_json_artifact, verify_content_hash
from lexstab.simulators.safe_expr import SafeExprError, validate_expressions

REPO_ROOT_MARKERS = ("pyproject.toml",)


class ArtifactError(Exception):
    """Raised for any artifact validation, integrity, or immutability failure."""


def find_repo_root(start: str | Path | None = None) -> Path:
    node = Path(start or Path.cwd()).resolve()
    for candidate in (node, *node.parents):
        if all((candidate / marker).exists() for marker in REPO_ROOT_MARKERS):
            return candidate
    raise ArtifactError(f"repository root not found from {node}")


# ---------------------------------------------------------------- JSONL


def jsonl_read(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ArtifactError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return rows


def jsonl_write(path: str | Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def jsonl_append(path: str | Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def json_read(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def json_write(path: str | Path, obj: Any, indent: int = 2) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=indent, ensure_ascii=False, sort_keys=True) + "\n")


def make_read_only(path: str | Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def is_read_only(path: str | Path) -> bool:
    return not os.access(path, os.W_OK)


# ---------------------------------------------------------------- validation


_SCHEMA_CACHE: dict[str, jsonschema.Draft202012Validator] = {}


def _schema_validator(root: Path, schema_file: str) -> jsonschema.Draft202012Validator:
    key = str(root / "schemas" / schema_file)
    if key not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[key] = jsonschema.Draft202012Validator(json_read(key))
    return _SCHEMA_CACHE[key]


def validate_artifact(
    obj: dict, model: type[BaseModel], schema_file: str, root: Path, source: str = ""
) -> BaseModel:
    """Validate against JSON Schema and Pydantic; return the model instance."""
    validator = _schema_validator(root, schema_file)
    errors = sorted(validator.iter_errors(obj), key=lambda err: list(err.absolute_path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise ArtifactError(f"{source}: schema violation at {location}: {first.message}")
    try:
        return model.model_validate(obj)
    except ValidationError as exc:
        raise ArtifactError(f"{source}: {exc.errors()[0]['msg']}") from exc


# ---------------------------------------------------------------- domain store


@dataclass
class DomainStore:
    entities: dict[str, models.EntityType]
    operations: dict[str, models.Operation]
    policies: dict[str, models.Policy]
    initial_state: dict[str, Any]
    hashes: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path, domain_dir: str | Path = "dataset/domain") -> "DomainStore":
        directory = root / domain_dir
        ent_doc = json_read(directory / "entities.json")
        op_doc = json_read(directory / "operations.json")
        pol_doc = json_read(directory / "policies.json")
        for doc, name in ((ent_doc, "entities"), (op_doc, "operations"), (pol_doc, "policies")):
            validate_artifact(doc, models.DomainFile, "domain.schema.json", root, name)
        entities = {e["entity_type"]: models.EntityType.model_validate(e) for e in ent_doc["entities"]}
        operations = {o["operation_id"]: models.Operation.model_validate(o) for o in op_doc["operations"]}
        policies = {p["policy_id"]: models.Policy.model_validate(p) for p in pol_doc["policies"]}
        initial_state = json_read(directory / "initial-state.json")
        store = cls(
            entities=entities,
            operations=operations,
            policies=policies,
            initial_state=initial_state,
            hashes={
                "entities": hash_file(directory / "entities.json"),
                "operations": hash_file(directory / "operations.json"),
                "policies": hash_file(directory / "policies.json"),
                "initial_state": hash_file(directory / "initial-state.json"),
            },
        )
        store.validate_integrity()
        return store

    def validate_integrity(self) -> None:
        for op in self.operations.values():
            if op.entity_type not in self.entities:
                raise ArtifactError(
                    f"operation {op.operation_id}: unknown entity type {op.entity_type}"
                )
            if op.primary_contrast and op.primary_contrast not in self.operations:
                raise ArtifactError(
                    f"operation {op.operation_id}: unknown contrast {op.primary_contrast}"
                )
            try:
                validate_expressions(
                    op.preconditions + op.invalid_when, op.effects
                )
            except SafeExprError as exc:
                raise ArtifactError(f"operation {op.operation_id}: {exc}") from exc
        for pol in self.policies.values():
            for op_id in pol.applies_to_operation_ids:
                if op_id not in self.operations:
                    raise ArtifactError(
                        f"policy {pol.policy_id}: unknown operation {op_id}"
                    )

    def tool_to_operation(self) -> dict[str, str]:
        return {op.tool: op.operation_id for op in self.operations.values()}


# ---------------------------------------------------------------- case loading


def load_cases(root: Path, cases_dir: str | Path = "dataset/cases/support") -> dict[str, models.CanonicalCase]:
    directory = root / cases_dir
    cases: dict[str, models.CanonicalCase] = {}
    for path in sorted(directory.glob("*.json")):
        obj = json_read(path)
        case = validate_artifact(obj, models.CanonicalCase, "case.schema.json", root, str(path))
        if case.case_id in cases:
            raise ArtifactError(f"duplicate case_id {case.case_id}")
        cases[case.case_id] = case
    return cases


def validate_case_against_domain(
    case: models.CanonicalCase, domain: DomainStore
) -> None:
    """Reject unknown operations, undefined arguments, inconsistent gold tools
    (spec §12.2). State-transition recomputation lives in the simulator module."""
    op = domain.operations.get(case.canonical.operation_id)
    if op is None:
        raise ArtifactError(
            f"case {case.case_id}: unknown operation {case.canonical.operation_id}"
        )
    if case.canonical.entity_type != op.entity_type:
        raise ArtifactError(
            f"case {case.case_id}: entity type {case.canonical.entity_type} does not "
            f"match operation entity type {op.entity_type}"
        )
    entity = domain.entities[op.entity_type]
    import re as _re

    if not _re.match(entity.id_pattern, case.canonical.entity_id):
        raise ArtifactError(
            f"case {case.case_id}: entity id {case.canonical.entity_id} does not match "
            f"pattern {entity.id_pattern}"
        )
    for arg_name in case.canonical.arguments:
        if arg_name not in op.arguments:
            raise ArtifactError(
                f"case {case.case_id}: argument {arg_name} not defined by "
                f"{op.operation_id}"
            )
    if case.gold.decision == models.GoldDecision.ACT:
        if case.gold.tool != op.tool:
            raise ArtifactError(
                f"case {case.case_id}: gold tool {case.gold.tool} inconsistent with "
                f"operation tool {op.tool}"
            )
        for arg_name in (case.gold.arguments or {}):
            if arg_name not in op.arguments:
                raise ArtifactError(
                    f"case {case.case_id}: gold argument {arg_name} not defined by "
                    f"{op.operation_id}"
                )
        for arg_name, spec in op.arguments.items():
            if spec.required and arg_name not in (case.gold.arguments or {}):
                raise ArtifactError(
                    f"case {case.case_id}: gold arguments missing required {arg_name}"
                )
    collection = entity.collection
    entity_states = case.initial_state.get(collection, {})
    if case.canonical.entity_id not in entity_states:
        raise ArtifactError(
            f"case {case.case_id}: initial_state has no {collection} entry for "
            f"{case.canonical.entity_id}"
        )
    for entity_id, state in entity_states.items():
        for field_name, spec in entity.required_state.items():
            if spec.required and field_name not in state:
                raise ArtifactError(
                    f"case {case.case_id}: {entity_id} missing required state field "
                    f"{field_name}"
                )


# ---------------------------------------------------------------- collections


def load_requests(root: Path, path: str | Path) -> dict[str, models.NLRequest]:
    requests: dict[str, models.NLRequest] = {}
    for row in jsonl_read(root / path):
        request = validate_artifact(
            row, models.NLRequest, "request.schema.json", root, f"{path}:{row.get('request_id')}"
        )
        if request.request_id in requests:
            raise ArtifactError(f"duplicate request_id {request.request_id}")
        requests[request.request_id] = request
    return requests


def load_contexts(root: Path, path: str | Path) -> dict[str, models.FrozenContext]:
    contexts: dict[str, models.FrozenContext] = {}
    for row in jsonl_read(root / path):
        ctx = validate_artifact(
            row, models.FrozenContext, "context.schema.json", root, f"{path}:{row.get('context_id')}"
        )
        contexts[ctx.context_id] = ctx
    return contexts


def load_renderings(root: Path, path: str | Path) -> dict[str, models.Rendering]:
    renderings: dict[str, models.Rendering] = {}
    for row in jsonl_read(root / path):
        ren = validate_artifact(
            row, models.Rendering, "rendering.schema.json", root, f"{path}:{row.get('rendering_id')}"
        )
        renderings[ren.rendering_id] = ren
    return renderings


def load_procedures(root: Path, path: str | Path) -> dict[str, models.Procedure]:
    procedures: dict[str, models.Procedure] = {}
    for row in jsonl_read(root / path):
        proc = validate_artifact(
            row, models.Procedure, "procedure.schema.json", root, f"{path}:{row.get('procedure_id')}"
        )
        procedures[proc.procedure_id] = proc
    return procedures


def load_interfaces(root: Path, paths: list[str | Path]) -> dict[str, models.ActionInterface]:
    interfaces: dict[str, models.ActionInterface] = {}
    for path in paths:
        full = root / path
        rows = jsonl_read(full) if str(path).endswith(".jsonl") else [json_read(full)]
        for row in rows:
            iface = validate_artifact(
                row, models.ActionInterface, "action-interface.schema.json", root,
                f"{path}:{row.get('interface_id')}",
            )
            interfaces[iface.interface_id] = iface
    return interfaces


def load_memory(root: Path, path: str | Path) -> dict[str, models.SemanticMemoryRecord]:
    records: dict[str, models.SemanticMemoryRecord] = {}
    for row in jsonl_read(root / path):
        rec = validate_artifact(
            row, models.SemanticMemoryRecord, "semantic-memory.schema.json", root,
            f"{path}:{row.get('memory_id')}",
        )
        records[rec.memory_id] = rec
    return records


def load_elicitation_cases(root: Path, path: str | Path) -> dict[str, models.ElicitationCase]:
    records: dict[str, models.ElicitationCase] = {}
    for row in jsonl_read(root / path):
        rec = validate_artifact(
            row, models.ElicitationCase, "elicitation-case.schema.json", root,
            f"{path}:{row.get('elicitation_case_id')}",
        )
        records[rec.elicitation_case_id] = rec
    return records


# ---------------------------------------------------------------- rendering checks


def validate_rendering_against_operation(
    rendering: models.Rendering, operation: models.Operation
) -> None:
    """Template placeholders must match the operation contract (spec §15.3)."""
    import re as _re

    placeholders = set(_re.findall(r"\{([a-z_][a-z0-9_]*)\}", rendering.template))
    allowed = set(operation.arguments) | {"entity_id", "entity_type", "operation_id"}
    unknown = placeholders - allowed
    if unknown:
        raise ArtifactError(
            f"rendering {rendering.rendering_id}: placeholders {sorted(unknown)} not in "
            f"operation contract for {operation.operation_id}"
        )
    if rendering.operation_id != operation.operation_id:
        raise ArtifactError(
            f"rendering {rendering.rendering_id}: operation mismatch"
        )


def validate_procedure_against_domain(
    procedure: models.Procedure, domain: DomainStore
) -> None:
    """Procedure references must resolve; required inputs must be a subset of
    what comparison conditions can supply (spec §15.4)."""
    allowed_inputs = {"entity_id", "entity_type", "operation_id", "known_state"}
    for op_id in procedure.applies_to_operation_ids:
        op = domain.operations.get(op_id)
        if op is None:
            raise ArtifactError(
                f"procedure {procedure.procedure_id}: unknown operation {op_id}"
            )
        allowed_inputs |= set(op.arguments)
    unknown = set(procedure.required_inputs) - allowed_inputs
    if unknown:
        raise ArtifactError(
            f"procedure {procedure.procedure_id}: required inputs {sorted(unknown)} are "
            "not available from the canonical case, resolution, or known state"
        )
    for op_id in procedure.evaluation_contract.forbidden_operation_ids:
        if op_id not in domain.operations:
            raise ArtifactError(
                f"procedure {procedure.procedure_id}: unknown forbidden operation {op_id}"
            )


# ---------------------------------------------------------------- integrity sweep


def referential_integrity(
    domain: DomainStore,
    cases: dict[str, models.CanonicalCase],
    requests: dict[str, models.NLRequest],
    contexts: dict[str, models.FrozenContext],
    renderings: dict[str, models.Rendering],
    procedures: dict[str, models.Procedure],
    interfaces: dict[str, models.ActionInterface],
) -> list[str]:
    """Return a list of integrity errors (empty when clean)."""
    errors: list[str] = []
    for case in cases.values():
        try:
            validate_case_against_domain(case, domain)
        except ArtifactError as exc:
            errors.append(str(exc))
    for request in requests.values():
        if request.case_id not in cases:
            errors.append(f"request {request.request_id}: unknown case {request.case_id}")
        ctx_id = request.labels.context_id
        if ctx_id and ctx_id not in contexts:
            errors.append(f"request {request.request_id}: unknown context {ctx_id}")
        contrast_op = request.labels.contrast_operation_id
        if contrast_op and contrast_op not in domain.operations:
            errors.append(
                f"request {request.request_id}: unknown contrast operation {contrast_op}"
            )
    for rendering in renderings.values():
        op = domain.operations.get(rendering.operation_id)
        if op is None:
            errors.append(
                f"rendering {rendering.rendering_id}: unknown operation "
                f"{rendering.operation_id}"
            )
            continue
        try:
            validate_rendering_against_operation(rendering, op)
        except ArtifactError as exc:
            errors.append(str(exc))
    for procedure in procedures.values():
        try:
            validate_procedure_against_domain(procedure, domain)
        except ArtifactError as exc:
            errors.append(str(exc))
    for iface in interfaces.values():
        for op_id in iface.operation_ids:
            if op_id not in domain.operations:
                errors.append(f"interface {iface.interface_id}: unknown operation {op_id}")
    return errors


# ---------------------------------------------------------------- frozen hash verify


def verify_frozen_file(root: Path, relative: str, expected_hash: str) -> None:
    actual = hash_file(root / relative)
    if actual != expected_hash:
        raise ArtifactError(
            f"frozen artifact hash mismatch for {relative}: manifest {expected_hash} "
            f"!= actual {actual}"
        )


def verify_frozen_rows(rows: list[dict], source: str) -> None:
    for row in rows:
        if not verify_content_hash(row):
            identifier = (
                row.get("request_id")
                or row.get("rendering_id")
                or row.get("context_id")
                or row.get("procedure_id")
                or "?"
            )
            raise ArtifactError(f"{source}: content hash mismatch for {identifier}")
