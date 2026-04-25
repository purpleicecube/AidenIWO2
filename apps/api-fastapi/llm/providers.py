"""Loop 9 Phase 9.3 — LLM provider registry + OpenAI-compatible client.

Behavioral template: IWO2 ``server/llm-client.ts`` (callOpenAICompatible
+ getProviderConfig). Reshaped for IWO3 multi-tenant + credential-ref
discipline.

Three slots:
  - groq         OpenAI-compatible at https://api.groq.com/openai/v1
  - openrouter   OpenAI-compatible at https://openrouter.ai/api/v1
  - openai       OpenAI-compatible at https://api.openai.com/v1

Anthropic stays in the registry as a known name without a Phase 9.3
client (forward-compat). Adding it later is a `register_provider` call.

The provider produces a single ``complete()`` return that carries the
text response + provider metadata so `llm.invoked` audit rows can
record `{provider, model, latency_ms, prompt_chars, completion_chars}`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import httpx


# ──────────────────────────────────────────────────────────────────────
# Public types
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProviderConfig:
    """Static per-provider plumbing — base URL + auth header style."""

    name: str
    default_base_url: str
    auth_scheme: str  # "bearer" — every Phase 9.3 provider uses bearer.


@dataclass(frozen=True)
class LlmCallResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    prompt_chars: int
    completion_chars: int
    raw: Mapping[str, Any] = field(default_factory=dict)


class LlmProviderError(Exception):
    """Raised when a provider call fails. Carries kind + http_status."""

    def __init__(
        self,
        kind: str,
        message: str,
        http_status: Optional[int] = None,
        provider: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status
        self.provider = provider


# ──────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────


_PROVIDERS: dict[str, ProviderConfig] = {
    "groq": ProviderConfig(
        name="groq",
        default_base_url="https://api.groq.com/openai/v1",
        auth_scheme="bearer",
    ),
    "openrouter": ProviderConfig(
        name="openrouter",
        default_base_url="https://openrouter.ai/api/v1",
        auth_scheme="bearer",
    ),
    "openai": ProviderConfig(
        name="openai",
        default_base_url="https://api.openai.com/v1",
        auth_scheme="bearer",
    ),
    "anthropic": ProviderConfig(
        name="anthropic",
        default_base_url="https://api.anthropic.com/v1",
        auth_scheme="bearer",
    ),
}

# Subset that has a Phase 9.3 client implementation. Anthropic is in
# the registry for forward-compat but cannot be exercised yet.
_PHASE_9_3_CALLABLE = {"groq", "openrouter", "openai"}


def known_providers() -> list[str]:
    return sorted(_PROVIDERS.keys())


def callable_providers() -> set[str]:
    return set(_PHASE_9_3_CALLABLE)


def get_provider_config(name: str) -> ProviderConfig:
    cfg = _PROVIDERS.get(name)
    if not cfg:
        raise LlmProviderError("unknown_provider", f"unknown provider: {name}")
    return cfg


# ──────────────────────────────────────────────────────────────────────
# OpenAI-compatible client
# ──────────────────────────────────────────────────────────────────────


def _map_http_error(
    provider: str, status: int, body: str
) -> LlmProviderError:
    if status in (401, 403):
        kind = "credential_invalid"
    elif status == 429:
        kind = "rate_limited"
    elif status >= 500:
        kind = "server_error"
    else:
        kind = "response_invalid"
    return LlmProviderError(
        kind=kind,
        message=f"{provider} returned HTTP {status}: {body[:300]}",
        http_status=status,
        provider=provider,
    )


def call_openai_compatible(
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: Optional[str],
    system_prompt: Optional[str],
    user_message: str,
    options: Optional[Mapping[str, Any]] = None,
    timeout_seconds: float = 30.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> LlmCallResult:
    """Single-shot completion call against an OpenAI-compatible endpoint.

    `transport` is an httpx escape hatch for tests — pass an
    ``httpx.MockTransport`` to deterministically stub responses without
    booting a server.
    """
    if provider not in _PHASE_9_3_CALLABLE:
        raise LlmProviderError(
            "provider_not_callable",
            f"provider {provider} is registered but not callable in Phase 9.3",
            provider=provider,
        )

    cfg = get_provider_config(provider)
    url = (base_url or cfg.default_base_url).rstrip("/") + "/chat/completions"

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_message})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    opts = dict(options or {})
    # Pass through standard sampling knobs only — guard against an
    # accidental key that the upstream provider would 422 on.
    for k in ("temperature", "top_p", "max_tokens", "response_format"):
        if k in opts:
            payload[k] = opts[k]

    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout_seconds, transport=transport) as cli:
            resp = cli.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise LlmProviderError(
            "network_error",
            f"{provider} request failed: {exc}",
            provider=provider,
        )

    latency_ms = int((time.monotonic() - started) * 1000)

    if resp.status_code != 200:
        raise _map_http_error(provider, resp.status_code, resp.text)

    try:
        data = resp.json()
    except ValueError:
        raise LlmProviderError(
            "response_invalid",
            f"{provider} returned non-JSON body",
            http_status=resp.status_code,
            provider=provider,
        )

    choices = data.get("choices") or []
    if not choices:
        raise LlmProviderError(
            "response_invalid",
            f"{provider} returned no choices",
            http_status=resp.status_code,
            provider=provider,
        )
    msg = choices[0].get("message") or {}
    text = msg.get("content") or ""

    prompt_chars = sum(len(m.get("content", "")) for m in messages)
    return LlmCallResult(
        text=text,
        provider=provider,
        model=model,
        latency_ms=latency_ms,
        prompt_chars=prompt_chars,
        completion_chars=len(text),
        raw=data,
    )
