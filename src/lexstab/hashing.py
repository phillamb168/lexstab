"""Content-addressed hashing for artifacts (spec §16.2, §40.2; decision D-006).

JSON artifacts hash their canonical JSON form with any embedded content-hash
fields removed, so a stored artifact's recorded hash is reproducible from the
file itself. Text artifacts hash raw bytes. The manifest root hash covers the
sorted (path, hash) inventory.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

HASH_PREFIX = "sha256:"
PLACEHOLDER = "sha256:replace-at-freeze-time"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return HASH_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(data).hexdigest()


def _strip_hash_fields(obj: Any) -> Any:
    """Remove content_hash fields (top level and under provenance/validation)."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key == "content_hash":
                continue
            out[key] = _strip_hash_fields(value)
        return out
    if isinstance(obj, list):
        return [_strip_hash_fields(item) for item in obj]
    return obj


def hash_json_artifact(obj: Any) -> str:
    """Hash a JSON artifact, ignoring embedded content_hash fields."""
    return sha256_text(canonical_json(_strip_hash_fields(obj)))


def stamp_content_hash(obj: dict) -> dict:
    """Return a copy with content_hash fields filled in wherever they exist."""
    stamped = copy.deepcopy(obj)
    digest = hash_json_artifact(stamped)

    def _stamp(node: Any) -> None:
        if isinstance(node, dict):
            if "content_hash" in node:
                node["content_hash"] = digest
            for value in node.values():
                _stamp(value)
        elif isinstance(node, list):
            for item in node:
                _stamp(item)

    _stamp(stamped)
    return stamped


def verify_content_hash(obj: dict) -> bool:
    """True when every embedded content_hash matches the artifact's content."""
    digest = hash_json_artifact(obj)
    found: list[str] = []

    def _collect(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "content_hash" and isinstance(value, str):
                    found.append(value)
                else:
                    _collect(value)
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    _collect(obj)
    return all(item == digest for item in found)


def hash_file(path: str | Path) -> str:
    """Hash a file: JSON artifacts canonically, everything else as raw bytes."""
    path = Path(path)
    data = path.read_bytes()
    if path.suffix == ".json":
        try:
            return hash_json_artifact(json.loads(data.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            pass
    if path.suffix == ".jsonl":
        try:
            rows = [
                json.loads(line)
                for line in data.decode("utf-8").splitlines()
                if line.strip()
            ]
            return sha256_text("\n".join(hash_json_artifact(row) for row in rows))
        except (ValueError, UnicodeDecodeError):
            pass
    return sha256_bytes(data)


def root_hash(inventory: dict[str, str]) -> str:
    """Root hash over a {relative_path: sha256} inventory (sorted)."""
    return sha256_text(canonical_json(sorted(inventory.items())))
