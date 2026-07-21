"""Contract tests: provider adapter behavior (spec §20) and action-interface
equivalence (spec §15.6, §46.30)."""

from pathlib import Path

import httpx

from lexstab.artifacts import DomainStore, find_repo_root
from lexstab.config import RoleConfig
from lexstab.interfaces import (
    build_generic_interface,
    build_mcp_interface,
    build_typed_interface,
    compare_interfaces,
)
from lexstab.providers.anthropic import SYSTEM_ONLY_USER_TURN, _to_anthropic_messages
from lexstab.providers.base import BaseAdapter, ProviderResponse, extract_json_object
from lexstab.providers.local import MockProvider

ROOT = find_repo_root(Path(__file__))


def _invoke(provider, **metadata):
    return provider.invoke(
        role="execution_primary", model_id="mock",
        messages=[{"role": "user", "content": "Escalate incident INC-1047 to Tier 2."}],
        tools=None, response_schema=None, parameters={},
        metadata={"run_id": "t", "cell_id": "c1", "timestamp": "t0",
                  "response_kind": "direct_clarify_executor", **metadata},
    )


class TestProviderContract:
    def test_anthropic_system_only_prompt_gets_neutral_user_turn(self):
        system, messages = _to_anthropic_messages([
            {"role": "system", "content": "Return the required JSON."},
        ])
        assert system == "Return the required JSON."
        assert messages == [{"role": "user", "content": SYSTEM_ONLY_USER_TURN}]

    def test_anthropic_existing_user_turn_is_not_changed(self):
        system, messages = _to_anthropic_messages([
            {"role": "system", "content": "Use the supplied request."},
            {"role": "user", "content": "Escalate INC-1047."},
        ])
        assert system == "Use the supplied request."
        assert messages == [{"role": "user", "content": "Escalate INC-1047."}]

    def test_anthropic_sends_json_schema_through_output_config(self, monkeypatch):
        from lexstab.providers.anthropic import AnthropicProvider

        captured = {}

        def fake_post(url, *, json, headers, timeout):
            captured["payload"] = json
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": '{"preferred_term":"Close incident"}'}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "stop_reason": "end_turn",
                    "model": "claude-opus-4-8",
                },
                headers={"request-id": "req-test"},
            )

        monkeypatch.setattr("lexstab.providers.anthropic.httpx.post", fake_post)
        schema = {
            "type": "object",
            "properties": {"preferred_term": {"type": "string"}},
            "required": ["preferred_term"],
            "additionalProperties": False,
        }
        record = AnthropicProvider(api_key="test").invoke(
            role="execution_primary",
            model_id="claude-opus-4-8",
            messages=[{"role": "system", "content": "Name the operation."}],
            tools=None,
            response_schema=schema,
            parameters={"max_tokens": 100},
            metadata={"run_id": "test", "cell_id": "structured", "timestamp": ""},
        )
        assert captured["payload"]["output_config"] == {
            "format": {"type": "json_schema", "schema": schema}
        }
        assert record.accepted_parameters["response_format"] == "json_schema"

    def test_invocation_record_completeness(self):
        record = _invoke(MockProvider())
        assert record.provider == "mock"
        assert record.requested_model_id == "mock"
        assert record.transport_retries == 0
        assert record.parse_status in ("ok", "empty")
        assert record.content_hash and record.content_hash.startswith("sha256:")
        assert record.messages

    def test_transport_retries_bounded_and_logged(self):
        provider = MockProvider(script={"execution_primary:c1": {"__transport_error__": 2}})
        record = _invoke(provider)
        assert record.transport_retries == 2
        assert len(provider.attempt_log) == 2

    def test_transport_exhaustion_is_terminal_not_semantic(self):
        provider = MockProvider(script={"execution_primary:c1": {"__transport_error__": 99}})
        provider.max_transport_retries = 3
        record = _invoke(provider)
        assert record.parse_status == "error"
        assert record.transport_retries == 4  # bounded: initial + 3 retries
        assert record.finish_reason == "transport_error"

    def test_non_2xx_response_is_an_explicit_provider_error(self):
        class FailingProvider(BaseAdapter):
            def _call_once(self, **kwargs):
                return ProviderResponse(
                    raw={
                        "status": 400,
                        "body": '{"error":{"message":"messages are required"}}',
                    },
                    text=None,
                    tool_calls=[],
                    tool_call_mode="native",
                    usage={},
                    finish_reason="http_400",
                )

        provider = FailingProvider(name="failing")
        record = _invoke(provider)
        assert record.finish_reason == "http_400"
        assert record.parse_status == "error"
        assert "messages are required" in record.parse_error

    def test_malformed_output_is_recorded_not_repaired(self):
        provider = MockProvider(script={"execution_primary:c1": {"__text__": "{not json"}})
        record = _invoke(provider)
        assert record.normalized_text == "{not json"
        obj, err = extract_json_object(record.normalized_text)
        assert obj is None and err
        # exactly one attempt: no semantic retry happened
        assert record.transport_retries == 0

    def test_json_extraction_no_repair(self):
        assert extract_json_object('{"a": 1}')[0] == {"a": 1}
        assert extract_json_object('```json\n{"a": 1}\n```')[0] == {"a": 1}
        assert extract_json_object("")[0] is None
        assert extract_json_object("[1, 2]")[0] is None


class TestInterfaceEquivalence:
    def test_generated_interfaces_are_equivalent(self):
        domain = DomainStore.load(ROOT)
        report = compare_interfaces(
            domain, build_generic_interface(domain), build_typed_interface(domain)
        )
        assert report["equivalent"], report["problems"]
        assert set(report["tool_description_terminology_overlap"]) == set(domain.operations)

    def test_drifted_tool_schema_detected(self):
        domain = DomainStore.load(ROOT)
        typed = build_typed_interface(domain)
        typed["tools"][0]["input_schema"]["properties"]["surprise"] = {"type": "string"}
        report = compare_interfaces(domain, build_generic_interface(domain), typed)
        assert not report["equivalent"]

    def test_missing_operation_detected(self):
        domain = DomainStore.load(ROOT)
        typed = build_typed_interface(domain)
        typed["operation_ids"] = typed["operation_ids"][:-1]
        typed["tools"] = typed["tools"][:-1]
        report = compare_interfaces(domain, build_generic_interface(domain), typed)
        assert not report["equivalent"]

    def test_mcp_export_shares_argument_requirements(self):
        domain = DomainStore.load(ROOT)
        typed = build_typed_interface(domain)
        mcp = build_mcp_interface(domain)
        assert mcp["kind"] == "MCP_CAPABILITY"
        for typed_tool, mcp_tool in zip(typed["tools"], mcp["tools"]):
            assert mcp_tool["input_schema"] == typed_tool["input_schema"]
            assert mcp_tool["name"].endswith(typed_tool["name"])


def test_role_separation_policy():
    from lexstab.config import ModelsConfig, SeparationPolicy, validate_role_separation

    def _role(name, model):
        return RoleConfig(name=name, provider="p", model_id=model, purpose="", parameters={})

    config = ModelsConfig(
        schema_version="1.2.0",
        roles={
            "execution_primary": _role("execution_primary", "m1"),
            "evaluation_judge": _role("evaluation_judge", "m1"),
            "authoring_generator": _role("authoring_generator", "m2"),
            "authoring_equivalence_critic": _role("authoring_equivalence_critic", "m2"),
        },
        separation_policy=SeparationPolicy(),
        raw={},
    )
    violations = validate_role_separation(config)
    assert any("judge" in violation for violation in violations)
    assert any("sole critic" in violation for violation in violations)
