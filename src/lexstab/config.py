"""Configuration loading: model roles, run config, thresholds (spec §19, §21).

Model IDs come exclusively from configuration/environment — never from code
(spec §19.4, §49.5). ``${VAR}`` values substitute from the environment; missing
substitutions are an error at resolution time, not silently empty.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ENV_PATTERN = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)\}$")

ROLE_NAMES = [
    "execution_primary",
    "execution_comparison",
    "boundary_canonicalizer",
    "adequacy_assessor",
    "memory_retriever",
    "procedure_router",
    "authoring_generator",
    "authoring_equivalence_critic",
    "authoring_adversarial_critic",
    "evaluation_judge",
    "failure_analyst",
]


class ConfigError(Exception):
    pass


def load_env_file(path: str | Path = ".env") -> None:
    """Load a dotenv file into os.environ without overriding existing values."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def substitute_env(value: Any, *, strict: bool) -> Any:
    if isinstance(value, str):
        match = ENV_PATTERN.match(value)
        if match:
            name = match.group(1)
            resolved = os.environ.get(name)
            if resolved is None or resolved == "":
                if strict:
                    raise ConfigError(f"environment variable {name} is not set")
                return None
            return resolved
        return value
    if isinstance(value, dict):
        return {key: substitute_env(item, strict=strict) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute_env(item, strict=strict) for item in value]
    return value


@dataclass
class RoleConfig:
    name: str
    provider: str
    model_id: str | None
    purpose: str
    parameters: dict[str, Any]
    enabled: bool = True
    baseline_eligible: bool = False
    capabilities: dict[str, bool] = field(default_factory=dict)


@dataclass
class SeparationPolicy:
    forbid_execution_model_as_judge: bool = True
    forbid_generator_as_sole_critic: bool = True
    forbid_mut_as_primary_data_generator: bool = True
    allow_role_overlap: bool = False


@dataclass
class ModelsConfig:
    schema_version: str
    roles: dict[str, RoleConfig]
    separation_policy: SeparationPolicy
    raw: dict[str, Any]

    def role(self, name: str) -> RoleConfig:
        cfg = self.roles.get(name)
        if cfg is None or not cfg.enabled:
            raise ConfigError(f"model role {name!r} is not configured or not enabled")
        return cfg


def load_models_config(path: str | Path, *, strict_env: bool = False) -> ModelsConfig:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict) or "roles" not in raw:
        raise ConfigError(f"{path}: missing 'roles' section")
    roles: dict[str, RoleConfig] = {}
    for name, spec in raw["roles"].items():
        if name not in ROLE_NAMES:
            raise ConfigError(f"{path}: unknown role {name!r}")
        spec = substitute_env(spec, strict=strict_env)
        roles[name] = RoleConfig(
            name=name,
            provider=spec.get("provider", "mock"),
            model_id=spec.get("model"),
            purpose=spec.get("purpose", ""),
            parameters=spec.get("parameters", {}) or {},
            enabled=spec.get("enabled", True),
            baseline_eligible=bool(spec.get("baseline_eligible", False)),
            capabilities=spec.get("capabilities", {}) or {},
        )
    policy_raw = raw.get("separation_policy", {}) or {}
    policy = SeparationPolicy(
        forbid_execution_model_as_judge=policy_raw.get(
            "forbid_execution_model_as_judge", True
        ),
        forbid_generator_as_sole_critic=policy_raw.get(
            "forbid_generator_as_sole_critic", True
        ),
        forbid_mut_as_primary_data_generator=policy_raw.get(
            "forbid_mut_as_primary_data_generator", True
        ),
        allow_role_overlap=policy_raw.get("allow_role_overlap", False),
    )
    return ModelsConfig(
        schema_version=str(raw.get("schema_version", "")),
        roles=roles,
        separation_policy=policy,
        raw=raw,
    )


def validate_role_separation(config: ModelsConfig) -> list[str]:
    """Return violations of spec §9.4/§19; run fails before execution unless
    allow_role_overlap is set (which is then recorded)."""
    violations: list[str] = []
    policy = config.separation_policy

    def _model_key(role: RoleConfig) -> tuple[str, str] | None:
        if not role.enabled or not role.model_id:
            return None
        return (role.provider, role.model_id)

    execution = config.roles.get("execution_primary")
    judge = config.roles.get("evaluation_judge")
    generator = config.roles.get("authoring_generator")
    eq_critic = config.roles.get("authoring_equivalence_critic")
    adv_critic = config.roles.get("authoring_adversarial_critic")

    if policy.forbid_execution_model_as_judge and execution and judge:
        if _model_key(execution) and _model_key(execution) == _model_key(judge):
            violations.append(
                "execution_primary and evaluation_judge use the same model "
                "(MUT must not grade itself)"
            )
    if policy.forbid_mut_as_primary_data_generator and execution and generator:
        if _model_key(execution) and _model_key(execution) == _model_key(generator):
            violations.append(
                "execution_primary and authoring_generator use the same model "
                "(MUT must not generate primary benchmark data)"
            )
    if policy.forbid_generator_as_sole_critic and generator:
        critic_keys = {
            _model_key(critic)
            for critic in (eq_critic, adv_critic)
            if critic and _model_key(critic)
        }
        gen_key = _model_key(generator)
        if gen_key and critic_keys and critic_keys == {gen_key}:
            violations.append(
                "authoring_generator is the sole critic of its own candidates"
            )
    return violations


# ---------------------------------------------------------------- run config


@dataclass
class RunConfig:
    run_name: str
    benchmark_manifest: str
    model_config_path: str
    tracks: dict[str, Any]
    selection: dict[str, Any]
    execution: dict[str, Any]
    evaluation: dict[str, Any]
    tracing: dict[str, Any]
    raw: dict[str, Any]

    @property
    def repetitions(self) -> int:
        return int(self.execution.get("repetitions", 1))

    @property
    def run_clock(self) -> str:
        return str(self.execution.get("run_clock", "2026-07-20T12:00:00Z"))

    @property
    def random_seed(self) -> int:
        return int(self.execution.get("random_seed", 104729))

    @property
    def semantic_retries(self) -> int:
        return int(self.execution.get("semantic_retries", 0))


def load_run_config(path: str | Path) -> RunConfig:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: not a mapping")
    config = RunConfig(
        run_name=raw.get("run_name", "unnamed-run"),
        benchmark_manifest=raw.get("benchmark_manifest", ""),
        model_config_path=raw.get("model_config", ""),
        tracks=raw.get("tracks", {}) or {},
        selection=raw.get("selection", {}) or {},
        execution=raw.get("execution", {}) or {},
        evaluation=raw.get("evaluation", {}) or {},
        tracing=raw.get("tracing", {}) or {},
        raw=raw,
    )
    if config.semantic_retries != 0:
        # Spec §7.11 / D-018: semantic retries are prohibited in primary conditions.
        allowlist = raw.get("retry_policy_experiment", []) or []
        if not allowlist:
            raise ConfigError(
                "execution.semantic_retries must be 0 unless an explicit "
                "retry_policy_experiment condition list is configured"
            )
    return config


def load_thresholds(path: str | Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: not a mapping")
    return raw
