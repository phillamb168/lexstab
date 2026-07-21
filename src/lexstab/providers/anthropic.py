"""Anthropic Messages API adapter (spec §20; decision D-004).

Exact model IDs come from configuration. Credentials come from the
environment only and are never logged.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from lexstab.providers.base import BaseAdapter, ProviderResponse, TransportError

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
RETRIABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
SYSTEM_ONLY_USER_TURN = "Complete the task exactly as specified in the system instructions."


def _to_anthropic_messages(messages: list[dict]) -> tuple[str | None, list[dict]]:
    system = None
    output = []
    for message in messages:
        if message["role"] == "system":
            system = (system + "\n\n" if system else "") + message["content"]
        else:
            output.append({"role": message["role"], "content": message["content"]})
    # The Anthropic Messages API requires at least one non-system message. Most
    # harness stages are intentionally expressed as a complete system prompt,
    # so add a semantically neutral user turn only for that wire-format case.
    if system and not output:
        output.append({"role": "user", "content": SYSTEM_ONLY_USER_TURN})
    return system, output


def _to_anthropic_tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool.get("input_schema")
            or tool.get("parameters")
            or {"type": "object"},
        }
        for tool in tools
    ]


class AnthropicProvider(BaseAdapter):
    def __init__(self, api_key: str | None = None, timeout: float = 120.0):
        super().__init__(name="anthropic")
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._timeout = timeout

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
            raise TransportError("ANTHROPIC_API_KEY is not configured")
        system, converted = _to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": converted,
            "max_tokens": int(parameters.get("max_tokens", 1024)),
        }
        if system:
            payload["system"] = system
        if "temperature" in parameters:
            payload["temperature"] = parameters["temperature"]
        if "top_p" in parameters:
            payload["top_p"] = parameters["top_p"]
        if "stop_sequences" in parameters:
            payload["stop_sequences"] = parameters["stop_sequences"]
        anthropic_tools = _to_anthropic_tools(tools)
        if anthropic_tools:
            payload["tools"] = anthropic_tools
        if response_schema is not None:
            payload["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": response_schema,
                }
            }

        try:
            response = httpx.post(
                API_URL,
                json=payload,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": API_VERSION,
                    "content-type": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.TransportError as exc:
            raise TransportError(f"transport failure: {exc}") from exc
        if response.status_code in RETRIABLE_STATUS:
            raise TransportError(f"HTTP {response.status_code}: {response.text[:200]}")
        if response.status_code != 200:
            # Non-retriable: surface as a terminal response record.
            return ProviderResponse(
                raw={"status": response.status_code, "body": response.text[:2000]},
                text=None,
                tool_calls=[],
                tool_call_mode="native",
                usage={},
                finish_reason=f"http_{response.status_code}",
                provider_request_id=response.headers.get("request-id"),
            )
        body = response.json()
        text_parts = []
        tool_calls = []
        for block in body.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {"tool": block.get("name"), "arguments": block.get("input", {})}
                )
        usage = body.get("usage", {})
        return ProviderResponse(
            raw=body,
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            tool_call_mode="native",
            usage={
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
            },
            finish_reason=body.get("stop_reason"),
            reported_model_id=body.get("model"),
            provider_request_id=response.headers.get("request-id"),
            accepted_parameters={
                **{
                    key: parameters[key]
                    for key in ("max_tokens", "temperature", "top_p", "stop_sequences")
                    if key in parameters
                },
                **({"response_format": "json_schema"} if response_schema is not None else {}),
            },
        )
