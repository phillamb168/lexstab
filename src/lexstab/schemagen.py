"""Generate JSON Schema Draft 2020-12 files from the Pydantic models (D-025).

The committed files under ``schemas/`` are the language-neutral contract; a
contract test asserts they exactly match regeneration from the models, which
guarantees the two validation layers are equivalent (spec §49.2).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema

from lexstab import models

SCHEMA_ID_BASE = "https://lexstab.invalid/schemas/"

SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "domain.schema.json": models.DomainFile,
    "operation.schema.json": models.Operation,
    "case.schema.json": models.CanonicalCase,
    "canonical-resolution.schema.json": models.CanonicalResolution,
    "lexical-name.schema.json": models.LexicalNameResponse,
    "context.schema.json": models.FrozenContext,
    "request.schema.json": models.NLRequest,
    "rendering.schema.json": models.Rendering,
    "semantic-memory.schema.json": models.SemanticMemoryRecord,
    "procedure.schema.json": models.Procedure,
    "action-interface.schema.json": models.ActionInterface,
    "action-proposal.schema.json": models.ActionProposal,
    "complexity-profile.schema.json": models.ComplexityProfile,
    "benchmark-manifest.schema.json": models.BenchmarkManifest,
    "run-manifest.schema.json": models.RunManifest,
    "invocation.schema.json": models.InvocationRecord,
    "score.schema.json": models.ScoreRecord,
    "elicitation-case.schema.json": models.ElicitationCase,
    "representation-ledger.schema.json": models.RepresentationLedgerRecord,
}


class _Draft202012(GenerateJsonSchema):
    schema_dialect = "https://json-schema.org/draft/2020-12/schema"


def generate_schema(model: type[BaseModel], filename: str) -> dict:
    schema = model.model_json_schema(schema_generator=_Draft202012, mode="validation")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID_BASE + filename,
        **schema,
    }
    return schema


def render_schema_text(model: type[BaseModel], filename: str) -> str:
    return json.dumps(generate_schema(model, filename), indent=2, sort_keys=False) + "\n"


def write_all(schemas_dir: str | Path) -> list[str]:
    schemas_dir = Path(schemas_dir)
    schemas_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, model in SCHEMA_MAP.items():
        (schemas_dir / filename).write_text(render_schema_text(model, filename))
        written.append(filename)
    return written


def check_all(schemas_dir: str | Path) -> list[str]:
    """Return filenames whose committed schema differs from regeneration."""
    schemas_dir = Path(schemas_dir)
    stale = []
    for filename, model in SCHEMA_MAP.items():
        path = schemas_dir / filename
        expected = render_schema_text(model, filename)
        if not path.exists() or path.read_text() != expected:
            stale.append(filename)
    return stale
