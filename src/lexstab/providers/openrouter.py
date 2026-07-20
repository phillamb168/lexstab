"""OpenRouter adapter (OpenAI-compatible endpoint; spec §20, D-004)."""

from __future__ import annotations

from lexstab.providers.openai import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    api_url = "https://openrouter.ai/api/v1/chat/completions"
    api_key_env = "OPENROUTER_API_KEY"

    def __init__(self, api_key: str | None = None, timeout: float = 120.0):
        super().__init__(api_key=api_key, timeout=timeout, name="openrouter")

    def _extra_headers(self) -> dict[str, str]:
        return {
            "HTTP-Referer": "https://lexstab.invalid",
            "X-Title": "lexstab harness",
        }
