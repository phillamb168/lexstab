"""Provider registry: role config -> adapter instance (spec §19, §20)."""

from __future__ import annotations

from typing import Any

from lexstab.config import ConfigError, RoleConfig
from lexstab.providers.anthropic import AnthropicProvider
from lexstab.providers.base import ADAPTER_VERSION, BaseAdapter
from lexstab.providers.local import MockProvider
from lexstab.providers.openai import OpenAIProvider
from lexstab.providers.openrouter import OpenRouterProvider

PROVIDER_NAMES = ("mock", "anthropic", "openai", "openrouter")


def build_provider(role: RoleConfig, mock_script: dict[str, Any] | None = None) -> BaseAdapter:
    if role.provider == "mock":
        return MockProvider(script=mock_script)
    if role.provider == "anthropic":
        return AnthropicProvider()
    if role.provider == "openai":
        return OpenAIProvider()
    if role.provider == "openrouter":
        return OpenRouterProvider()
    raise ConfigError(f"unknown provider {role.provider!r} for role {role.name}")


def adapter_versions() -> dict[str, str]:
    return {name: ADAPTER_VERSION for name in PROVIDER_NAMES}
