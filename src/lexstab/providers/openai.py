"""OpenAI Chat Completions adapter (spec §20; D-004). Also the base class for
OpenAI-compatible endpoints such as OpenRouter."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from lexstab.providers.base import BaseAdapter, ProviderResponse, TransportError

RETRIABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


def _to_openai_tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema")
                or tool.get("parameters")
                or {"type": "object"},
            },
        }
        for tool in tools
    ]


class OpenAIProvider(BaseAdapter):
    api_url = "https://api.openai.com/v1/chat/completions"
    api_key_env = "OPENAI_API_KEY"

    def __init__(self, api_key: str | None = None, timeout: float = 120.0, name: str = "openai"):
        super().__init__(name=name)
        self._api_key = api_key or os.environ.get(self.api_key_env, "")
        self._timeout = timeout

    def _extra_headers(self) -> dict[str, str]:
        return {}

    def _call_once(
        self,
        *,
        model_id: str,
        messages: list[dict],
        tools: list[dict] | None,
        response_schema: dict | None,
        parameters: dict,
        metadata: dict,
    ) -> ProviderResponse:
        if not self._api_key:
            raise TransportError(f"{self.api_key_env} is not configured")
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
        }
        if "temperature" in parameters:
            payload["temperature"] = parameters["temperature"]
        if "max_tokens" in parameters:
            payload["max_tokens"] = parameters["max_tokens"]
        if "top_p" in parameters:
            payload["top_p"] = parameters["top_p"]
        if "seed" in parameters:
            payload["seed"] = parameters["seed"]
        openai_tools = _to_openai_tools(tools)
        if openai_tools:
            payload["tools"] = openai_tools
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": response_schema},
            }
        try:
            response = httpx.post(
                self.api_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                    **self._extra_headers(),
                },
                timeout=self._timeout,
            )
        except httpx.TransportError as exc:
            raise TransportError(f"transport failure: {exc}") from exc
        if response.status_code in RETRIABLE_STATUS:
            raise TransportError(f"HTTP {response.status_code}: {response.text[:200]}")
        if response.status_code != 200:
            return ProviderResponse(
                raw={"status": response.status_code, "body": response.text[:2000]},
                text=None,
                tool_calls=[],
                tool_call_mode="native",
                usage={},
                finish_reason=f"http_{response.status_code}",
                provider_request_id=response.headers.get("x-request-id"),
            )
        body = response.json()
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message", {})
        tool_calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {"__unparseable__": function.get("arguments")}
            tool_calls.append({"tool": function.get("name"), "arguments": arguments})
        usage = body.get("usage", {})
        return ProviderResponse(
            raw=body,
            text=message.get("content"),
            tool_calls=tool_calls,
            tool_call_mode="native",
            usage={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
            finish_reason=choice.get("finish_reason"),
            reported_model_id=body.get("model"),
            fingerprint=body.get("system_fingerprint"),
            provider_request_id=response.headers.get("x-request-id"),
        )
