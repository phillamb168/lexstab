"""Common provider adapter contract (spec §20).

Every adapter implements ``invoke`` and returns a complete
:class:`lexstab.models.InvocationRecord`. Transport retries are bounded,
exponential, and recorded per attempt; semantic retries never happen here
(spec §20.1, D-018). Parsing is single-pass and never repaired.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from lexstab.hashing import sha256_text
from lexstab.models import InvocationRecord

ADAPTER_VERSION = "1.1.0"


class TransportError(Exception):
    """A retriable transport failure (rate limit, timeout, 5xx)."""


@dataclass
class ProviderResponse:
    """Raw normalized result an adapter's backend returns for one attempt."""

    raw: Any
    text: str | None
    tool_calls: list[dict[str, Any]]
    tool_call_mode: str
    usage: dict[str, Any]
    finish_reason: str | None
    reported_model_id: str | None = None
    fingerprint: str | None = None
    provider_request_id: str | None = None
    cost_estimate: float | None = None
    accepted_parameters: dict[str, Any] = field(default_factory=dict)


class ModelProvider(Protocol):
    name: str

    def invoke(
        self,
        *,
        role: str,
        model_id: str,
        messages: list[dict],
        tools: list[dict] | None,
        response_schema: dict | None,
        parameters: dict,
        metadata: dict,
    ) -> InvocationRecord: ...


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def provider_failure_category(finish_reason: str | None) -> str | None:
    """Return a stable infrastructure-failure label for terminal provider errors."""
    if finish_reason == "transport_error":
        return "provider_transport_error"
    if finish_reason and finish_reason.startswith("http_"):
        return f"provider_{finish_reason}"
    return None


def _provider_error_message(response: ProviderResponse) -> str:
    """Extract a concise provider error without losing the raw response artifact."""
    status = response.finish_reason or "provider_error"
    raw = response.raw if isinstance(response.raw, dict) else {}
    body: Any = raw.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = body.strip()
    detail: Any = body
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or error.get("type") or error
        else:
            detail = body.get("message") or body
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, sort_keys=True) if detail else ""
    detail = detail[:500]
    return f"provider {status.replace('_', ' ').upper()}" + (f": {detail}" if detail else "")


def extract_json_object(text: str | None) -> tuple[dict | None, str | None]:
    """Single-pass JSON extraction; no repair (spec §7.11).

    Returns (object, error). Accepts a bare object or one fenced/embedded
    object; anything else is a parse error scored as incorrect downstream.
    """
    if not text or not text.strip():
        return None, "empty response"
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped).strip()
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            return obj, None
        return None, "top-level JSON is not an object"
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(stripped)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                return obj, None
        except json.JSONDecodeError:
            pass
    return None, "no parseable JSON object"


@dataclass
class BaseAdapter:
    """Shared retry/record logic. Subclasses implement ``_call_once``."""

    name: str = "base"
    max_transport_retries: int = 3
    backoff_base_seconds: float = 0.5
    sleeper: Any = time.sleep  # injectable for tests
    attempt_log: list[dict] = field(default_factory=list)

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
        raise NotImplementedError

    def invoke(
        self,
        *,
        role: str,
        model_id: str,
        messages: list[dict],
        tools: list[dict] | None,
        response_schema: dict | None,
        parameters: dict,
        metadata: dict,
    ) -> InvocationRecord:
        metadata = {**metadata, "role": role}
        retries = 0
        last_error: Exception | None = None
        response: ProviderResponse | None = None
        start = time.monotonic()
        while retries <= self.max_transport_retries:
            try:
                response = self._call_once(
                    model_id=model_id,
                    messages=messages,
                    tools=tools,
                    response_schema=response_schema,
                    parameters=parameters,
                    metadata=metadata,
                )
                break
            except TransportError as exc:
                last_error = exc
                self.attempt_log.append(
                    {
                        "role": role,
                        "model_id": model_id,
                        "attempt": retries,
                        "error": str(exc),
                        "cell_id": metadata.get("cell_id"),
                    }
                )
                retries += 1
                if retries > self.max_transport_retries:
                    break
                self.sleeper(self.backoff_base_seconds * (2 ** (retries - 1)))
        latency_ms = (time.monotonic() - start) * 1000.0

        if response is None:
            return InvocationRecord(
                run_id=metadata.get("run_id", ""),
                cell_id=metadata.get("cell_id", ""),
                role=role,
                provider=self.name,
                requested_model_id=model_id,
                timestamp=metadata.get("timestamp", ""),
                messages=messages,
                tools=tools,
                response_schema_id=metadata.get("response_schema_id"),
                requested_parameters=parameters,
                raw_response=None,
                normalized_text=None,
                tool_calls=[],
                usage={},
                latency_ms=latency_ms,
                finish_reason="transport_error",
                transport_retries=retries,
                parse_status="error",
                parse_error=f"transport failure: {last_error}",
                content_hash=None,
            )

        parse_status = "ok"
        parse_error = None
        if provider_failure_category(response.finish_reason):
            parse_status = "error"
            parse_error = _provider_error_message(response)
        elif not response.tool_calls and (response.text is None or not response.text.strip()):
            parse_status = "empty"
            parse_error = "no text and no tool calls"

        return InvocationRecord(
            run_id=metadata.get("run_id", ""),
            cell_id=metadata.get("cell_id", ""),
            role=role,
            provider=self.name,
            requested_model_id=model_id,
            reported_model_id=response.reported_model_id,
            fingerprint=response.fingerprint,
            timestamp=metadata.get("timestamp", ""),
            messages=messages,
            tools=tools,
            response_schema_id=metadata.get("response_schema_id"),
            requested_parameters=parameters,
            accepted_parameters=(
                response.accepted_parameters
                or (dict(parameters) if self.name == "mock" else {})
            ),
            raw_response=response.raw,
            normalized_text=response.text,
            tool_calls=response.tool_calls,
            tool_call_mode=response.tool_call_mode,  # type: ignore[arg-type]
            usage=response.usage,
            latency_ms=latency_ms,
            cost_estimate=response.cost_estimate,
            finish_reason=response.finish_reason,
            provider_request_id=response.provider_request_id,
            transport_retries=retries,
            parse_status=parse_status,  # type: ignore[arg-type]
            parse_error=parse_error,
            content_hash=sha256_text(response.text or json.dumps(response.tool_calls, sort_keys=True)),
        )
