"""Model-facing rendering discovery (spec §15, §27.2, §42.8).

Blind naming: the prompt shows definitions and examples, never candidate
labels. Each sample runs in a fresh context. Discovery must use development
material only (§22.2); the discovered rendering is frozen before any
downstream testing (§49.4).
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from lexstab import models
from lexstab.artifacts import DomainStore, jsonl_write
from lexstab.config import ModelsConfig
from lexstab.prompts import PromptLibrary
from lexstab.providers.base import BaseAdapter, extract_json_object

POSITIVE_EXAMPLES = {
    "ESCALATE_INCIDENT": "Ticket INC-1047 was moved from Tier 1 ownership to Tier 2 ownership while remaining open.",
    "REASSIGN_INCIDENT": "Ticket INC-1047 changed owning team from Service Desk to Billing while its tier stayed fixed.",
    "CLOSE_INCIDENT": "Ticket INC-2450, whose information was complete, was marked finished and left the open queue.",
    "REFUND_DUPLICATE_CHARGE": "Order ORD-0077 was charged twice; the second 120 USD charge was returned to the customer.",
}
NEGATIVE_EXAMPLES = {
    "ESCALATE_INCIDENT": "Ticket INC-1047 changed owning team at the same tier.",
    "REASSIGN_INCIDENT": "Ticket INC-1047 moved from Tier 1 to Tier 2 with the same owning team.",
    "CLOSE_INCIDENT": "Ticket INC-2450 was put on hold pending more information.",
    "REFUND_DUPLICATE_CHARGE": "Order ORD-0077's single legitimate charge was disputed and sent to a manager.",
}


def normalize_label(label: str) -> str:
    """Normalization rules reported with term entropy (§38.8): lowercase,
    strip punctuation, collapse whitespace, naive plural trim."""
    text = re.sub(r"[^a-z0-9 ]", "", label.lower()).strip()
    text = re.sub(r"\s+", " ", text)
    words = [word[:-1] if word.endswith("s") and len(word) > 3 else word for word in text.split()]
    return " ".join(words)


def term_entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def discover_renderings(
    root: Path,
    domain: DomainStore,
    models_config: ModelsConfig,
    provider: BaseAdapter,
    *,
    operation_ids: list[str],
    samples: int = 50,
    role: str = "execution_primary",
    output: Path | None = None,
) -> list[dict[str, Any]]:
    prompts = PromptLibrary(root / "prompts")
    prompt = prompts.get("lexical-convergence.v1")
    role_config = models_config.role(role)
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    renderings = []
    for op_id in operation_ids:
        op = domain.operations[op_id]
        raw_terms: list[str] = []
        for sample_index in range(samples):
            record = provider.invoke(
                role=role,
                model_id=role_config.model_id or "",
                messages=[{
                    "role": "system",
                    "content": prompt.render(
                        definition=op.description or op.display_name,
                        positive_examples=POSITIVE_EXAMPLES.get(op_id, op.display_name),
                        negative_examples=NEGATIVE_EXAMPLES.get(op_id, "(none)"),
                    ),
                }],
                tools=None,
                response_schema=None,
                parameters=role_config.parameters,
                metadata={
                    "run_id": "discovery",
                    "cell_id": f"discovery:{op_id}:{sample_index}",
                    "timestamp": now,
                    "response_kind": "lexical_name",
                    "sample_index": sample_index,
                },
            )
            obj, _err = extract_json_object(record.normalized_text)
            if obj and obj.get("preferred_term"):
                raw_terms.append(str(obj["preferred_term"]))
        normalized = Counter(normalize_label(term) for term in raw_terms if term != "DEFINITION_ONLY")
        definition_only = sum(1 for term in raw_terms if term == "DEFINITION_ONLY")
        if not normalized:
            continue
        modal_term, modal_count = normalized.most_common(1)[0]
        arg_placeholders = " ".join(
            "{" + name + "}" for name, spec in op.arguments.items()
            if spec.required and not name.endswith("_id")
        )
        template = f"{modal_term.capitalize()} {{entity_id}}" + (
            f" with {arg_placeholders}." if arg_placeholders else "."
        )
        renderings.append({
            "schema_version": models.SCHEMA_VERSION,
            "rendering_id": f"REN-{op_id.replace('_', '-')}-DISCOVERED-001",
            "operation_id": op_id,
            "entity_type": op.entity_type,
            "category": "MODEL_DISCOVERED",
            "label": modal_term,
            "template": template,
            "definition": op.description or op.display_name,
            "discovery": {
                "provider": role_config.provider,
                "model_id": role_config.model_id or "",
                "prompt_id": "lexical-convergence.v1",
                "sample_count": samples,
                "normalized_label_count": modal_count,
                "convergence_rate": round(modal_count / samples, 4),
                "seed_policy": "provider-supported-seeds-or-recorded-null",
                "term_entropy": round(term_entropy(normalized), 4),
                "discovered_on_split": "development",
            },
            "validation": {"status": "CANDIDATE", "reviewed_by": [], "approved_at": None},
            "provenance": {"created_at": now, "source_run_id": "discovery",
                           "parent_request_id": None, "content_hash": None},
            "_distribution": {
                "modal_term": modal_term,
                "convergence_rate": round(modal_count / samples, 4),
                "term_entropy": round(term_entropy(normalized), 4),
                "alternatives": dict(normalized.most_common(10)),
                "definition_only_rate": round(definition_only / samples, 4),
            },
        })
    if output:
        stripped = []
        for rendering in renderings:
            row = {key: value for key, value in rendering.items() if not key.startswith("_")}
            models.Rendering.model_validate(row)
            stripped.append({**row, "_distribution": rendering["_distribution"]})
        jsonl_write(output, stripped)
    return renderings
