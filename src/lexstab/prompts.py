"""Versioned prompt artifact management (spec §22).

Prompts are text files with the §22.1 header convention. Rendering fails when
required variables are missing or unexpected variables are supplied. Every
prompt exposes its content hash for manifests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lexstab.hashing import sha256_bytes


class PromptError(Exception):
    pass


@dataclass(frozen=True)
class Prompt:
    prompt_id: str
    purpose: str
    required_variables: tuple[str, ...]
    response_schema: str
    body: str
    content_hash: str
    path: str

    def render(self, **variables: str) -> str:
        supplied = set(variables)
        required = set(self.required_variables)
        missing = required - supplied
        if missing:
            raise PromptError(
                f"{self.prompt_id}: missing required variables {sorted(missing)}"
            )
        unexpected = supplied - required
        if unexpected:
            raise PromptError(
                f"{self.prompt_id}: unexpected variables {sorted(unexpected)}"
            )
        rendered = self.body
        for name, value in variables.items():
            rendered = rendered.replace("{" + name + "}", str(value))
        return rendered


_HEADER_RE = re.compile(
    r"^PROMPT_ID:\s*(?P<prompt_id>\S+)\s*\n"
    r"PURPOSE:\s*(?P<purpose>.*?)\n"
    r"REQUIRED_VARIABLES:\s*(?P<variables>.*?)\n"
    r"RESPONSE_SCHEMA:\s*(?P<schema>.*?)\n"
    r"\n?---\n",
    re.DOTALL,
)


def load_prompt(path: str | Path) -> Prompt:
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    match = _HEADER_RE.match(text)
    if not match:
        raise PromptError(f"{path}: missing or malformed §22.1 prompt header")
    variables = tuple(
        var.strip()
        for var in match.group("variables").split(",")
        if var.strip() and var.strip().lower() != "none"
    )
    body = text[match.end():].lstrip("\n")
    return Prompt(
        prompt_id=match.group("prompt_id"),
        purpose=match.group("purpose").strip(),
        required_variables=variables,
        response_schema=match.group("schema").strip(),
        body=body,
        content_hash=sha256_bytes(raw),
        path=str(path),
    )


class PromptLibrary:
    def __init__(self, prompts_dir: str | Path):
        self.prompts_dir = Path(prompts_dir)
        self._cache: dict[str, Prompt] = {}
        self._index: dict[str, Path] = {}
        for file in sorted(self.prompts_dir.rglob("*.txt")):
            self._index[file.stem] = file

    def get(self, prompt_id: str) -> Prompt:
        if prompt_id not in self._cache:
            path = self._index.get(prompt_id)
            if path is None:
                raise PromptError(f"unknown prompt {prompt_id!r}")
            prompt = load_prompt(path)
            if prompt.prompt_id != prompt_id:
                raise PromptError(
                    f"{path}: header PROMPT_ID {prompt.prompt_id!r} != filename {prompt_id!r}"
                )
            self._cache[prompt_id] = prompt
        return self._cache[prompt_id]

    def all_ids(self) -> list[str]:
        return sorted(self._index)

    def hashes(self) -> dict[str, str]:
        return {prompt_id: self.get(prompt_id).content_hash for prompt_id in self.all_ids()}

    def validate_all(self) -> list[str]:
        """Return errors for prompts whose headers/bodies are inconsistent."""
        errors = []
        for prompt_id in self.all_ids():
            try:
                prompt = self.get(prompt_id)
            except PromptError as exc:
                errors.append(str(exc))
                continue
            placeholders = set(re.findall(r"\{([a-z_][a-z0-9_]*)\}", prompt.body))
            declared = set(prompt.required_variables)
            undeclared = placeholders - declared
            if undeclared:
                errors.append(
                    f"{prompt_id}: body placeholders {sorted(undeclared)} not declared "
                    "in REQUIRED_VARIABLES"
                )
        return errors
