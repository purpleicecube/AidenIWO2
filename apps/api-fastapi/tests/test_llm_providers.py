"""Loop 9 Phase 9.3 — OpenAI-compatible client error matrix.

Uses ``httpx.MockTransport`` so we never hit the real provider. Covers:
  - 200 happy path → LlmCallResult populated
  - 401 → credential_invalid
  - 403 → credential_invalid
  - 429 → rate_limited
  - 500 → server_error
  - non-JSON body → response_invalid
  - non-callable provider → provider_not_callable
  - unknown provider → unknown_provider
"""

from __future__ import annotations

import json

import httpx
import pytest

from llm.providers import (
    LlmProviderError,
    call_openai_compatible,
    callable_providers,
    get_provider_config,
    known_providers,
)


def _transport_returning(
    status: int, body: object | str
) -> httpx.MockTransport:
    body_str = body if isinstance(body, str) else json.dumps(body)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            content=body_str.encode(),
            headers={"Content-Type": "application/json"},
        )

    return httpx.MockTransport(handler)


def test_known_providers_include_groq_openrouter_openai_anthropic() -> None:
    assert {"groq", "openrouter", "openai", "anthropic"}.issubset(
        set(known_providers())
    )


def test_callable_providers_phase_9_3_set() -> None:
    assert callable_providers() == {"groq", "openrouter", "openai"}


def test_groq_default_base_url() -> None:
    assert (
        get_provider_config("groq").default_base_url
        == "https://api.groq.com/openai/v1"
    )


def test_openrouter_default_base_url() -> None:
    assert (
        get_provider_config("openrouter").default_base_url
        == "https://openrouter.ai/api/v1"
    )


def test_call_200_happy_path() -> None:
    transport = _transport_returning(
        200,
        {
            "choices": [
                {"message": {"role": "assistant", "content": "pong"}}
            ]
        },
    )
    result = call_openai_compatible(
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key="test-key",
        base_url=None,
        system_prompt="you are a test agent",
        user_message="ping",
        transport=transport,
    )
    assert result.text == "pong"
    assert result.provider == "groq"
    assert result.model == "openai/gpt-oss-120b"
    assert result.completion_chars == 4
    assert result.prompt_chars > 0
    assert result.latency_ms >= 0


def test_call_401_credential_invalid() -> None:
    with pytest.raises(LlmProviderError) as ei:
        call_openai_compatible(
            provider="groq",
            model="m",
            api_key="bad",
            base_url=None,
            system_prompt=None,
            user_message="hi",
            transport=_transport_returning(
                401, {"error": {"message": "invalid api key"}}
            ),
        )
    assert ei.value.kind == "credential_invalid"
    assert ei.value.http_status == 401


def test_call_403_credential_invalid() -> None:
    with pytest.raises(LlmProviderError) as ei:
        call_openai_compatible(
            provider="openrouter",
            model="m",
            api_key="bad",
            base_url=None,
            system_prompt=None,
            user_message="hi",
            transport=_transport_returning(403, {"error": "forbidden"}),
        )
    assert ei.value.kind == "credential_invalid"


def test_call_429_rate_limited() -> None:
    with pytest.raises(LlmProviderError) as ei:
        call_openai_compatible(
            provider="groq",
            model="m",
            api_key="ok",
            base_url=None,
            system_prompt=None,
            user_message="hi",
            transport=_transport_returning(429, {"error": "rate"}),
        )
    assert ei.value.kind == "rate_limited"


def test_call_500_server_error() -> None:
    with pytest.raises(LlmProviderError) as ei:
        call_openai_compatible(
            provider="groq",
            model="m",
            api_key="ok",
            base_url=None,
            system_prompt=None,
            user_message="hi",
            transport=_transport_returning(500, "<html>internal</html>"),
        )
    assert ei.value.kind == "server_error"


def test_call_non_json_body_response_invalid() -> None:
    with pytest.raises(LlmProviderError) as ei:
        call_openai_compatible(
            provider="groq",
            model="m",
            api_key="ok",
            base_url=None,
            system_prompt=None,
            user_message="hi",
            transport=_transport_returning(200, "not json at all"),
        )
    assert ei.value.kind == "response_invalid"


def test_call_no_choices_response_invalid() -> None:
    with pytest.raises(LlmProviderError) as ei:
        call_openai_compatible(
            provider="groq",
            model="m",
            api_key="ok",
            base_url=None,
            system_prompt=None,
            user_message="hi",
            transport=_transport_returning(200, {"choices": []}),
        )
    assert ei.value.kind == "response_invalid"


def test_call_unknown_provider() -> None:
    with pytest.raises(LlmProviderError) as ei:
        call_openai_compatible(
            provider="bogus",
            model="m",
            api_key="ok",
            base_url=None,
            system_prompt=None,
            user_message="hi",
            transport=_transport_returning(200, {}),
        )
    assert ei.value.kind in {"unknown_provider", "provider_not_callable"}


def test_call_anthropic_not_callable_in_phase_9_3() -> None:
    with pytest.raises(LlmProviderError) as ei:
        call_openai_compatible(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key="ok",
            base_url=None,
            system_prompt=None,
            user_message="hi",
            transport=_transport_returning(200, {}),
        )
    assert ei.value.kind == "provider_not_callable"


def test_call_options_filter() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            content=json.dumps(
                {"choices": [{"message": {"content": "x"}}]}
            ).encode(),
        )

    call_openai_compatible(
        provider="groq",
        model="m",
        api_key="ok",
        base_url=None,
        system_prompt=None,
        user_message="hi",
        options={
            "temperature": 0.5,
            "max_tokens": 64,
            "top_p": 0.9,
            "non_existent_knob": "discarded",
        },
        transport=httpx.MockTransport(handler),
    )
    assert captured["body"]["temperature"] == 0.5
    assert captured["body"]["max_tokens"] == 64
    assert captured["body"]["top_p"] == 0.9
    assert "non_existent_knob" not in captured["body"]
