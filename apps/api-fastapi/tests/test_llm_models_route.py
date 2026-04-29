"""Architect-lock §5 exception (2026-04-26) — GET /llm/models tests.

Covers the route added so the Streamlit Aiden Settings page can populate
its Model dropdown via live provider catalogs (IWO2 visual parity for
the ModelSelector). Verifies:

  - 401 without auth headers
  - 400 on unknown provider
  - 200 + keyConfigured=false + error="provider_not_callable_in_phase_9_3"
    for anthropic (registered but not Phase 9.3 callable)
  - 200 + keyConfigured=false on a callable provider whose tenant config
    references an unset env var (the test runtime never sets real keys)
  - 200 + keyConfigured=true + sorted models when the underlying httpx
    /models call succeeds (monkey-patched provider helper)
  - error path bubbles back as a 200 with keyConfigured=true + error
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def test_list_models_requires_auth() -> None:
    with TestClient(app) as client:
        r = client.get("/llm/models", params={"provider": "groq"})
    assert r.status_code == 401


@iwo3_db
def test_list_models_rejects_unknown_provider() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/llm/models",
            params={"provider": "cohere"},
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "unknown_provider"


@iwo3_db
def test_list_models_returns_not_callable_for_anthropic() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/llm/models",
            params={"provider": "anthropic"},
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "anthropic"
    assert body["keyConfigured"] is False
    assert body["models"] == []
    assert body["error"] == "provider_not_callable_in_phase_9_3"


@iwo3_db
def test_list_models_returns_key_unconfigured_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Klear has a seeded groq config pointing at GROQ_API_KEY. With
    GROQ_API_KEY unset, the route returns keyConfigured=false rather
    than erroring — caller falls back to manual entry."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with TestClient(app) as client:
        r = client.get(
            "/llm/models",
            params={"provider": "groq"},
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "groq"
    assert body["keyConfigured"] is False
    assert body["models"] == []
    assert body["error"] is None


@iwo3_db
def test_list_models_returns_sorted_catalog_when_provider_responds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live happy path — env var set + provider /models returns a list.
    Models come back alphabetically, normalized to {id, name, ...}."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")

    def fake_list_models(
        *, provider: str, api_key: str, base_url: Any = None
    ) -> list[dict[str, Any]]:
        return [
            {"id": "llama-3.3-70b-versatile", "name": "llama-3.3-70b-versatile"},
            {"id": "kimi-k2-instruct", "name": "kimi-k2-instruct", "owned_by": "moonshotai"},
            {"id": "openai/gpt-oss-120b", "name": "openai/gpt-oss-120b"},
        ]

    monkeypatch.setattr(
        "routes.llm.list_openai_compatible_models", fake_list_models
    )
    with TestClient(app) as client:
        r = client.get(
            "/llm/models",
            params={"provider": "groq"},
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["keyConfigured"] is True
    assert body["error"] is None
    ids = [m["id"] for m in body["models"]]
    # The provider helper sorts; the route preserves the order the
    # helper hands back. The fake helper here returns a fixed,
    # unsorted-by-id sequence — assert the route returns it byte-for-byte
    # (no re-sorting, no dropped rows, no inserted rows).
    assert ids == [
        "llama-3.3-70b-versatile",
        "kimi-k2-instruct",
        "openai/gpt-oss-120b",
    ]


@iwo3_db
def test_list_models_bubbles_provider_error_as_200_with_error_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider /models 401 (bad key) → keyConfigured=true (env was set),
    models=[], error="credential_invalid: …". The Streamlit picker uses
    this to swap the dropdown for a manual text input."""
    from llm.providers import LlmProviderError

    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")

    def fake_list_models_raising(**kwargs: Any) -> list[dict[str, Any]]:
        raise LlmProviderError(
            kind="credential_invalid",
            message="groq returned HTTP 401",
            http_status=401,
            provider="groq",
        )

    monkeypatch.setattr(
        "routes.llm.list_openai_compatible_models", fake_list_models_raising
    )
    with TestClient(app) as client:
        r = client.get(
            "/llm/models",
            params={"provider": "groq"},
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["keyConfigured"] is True
    assert body["models"] == []
    assert body["error"] is not None
    assert body["error"].startswith("credential_invalid:")


# ── Unit tests for the provider helper itself (no DB needed) ─────────


def test_list_openai_compatible_models_normalizes_and_sorts() -> None:
    import json

    import httpx

    from llm.providers import list_openai_compatible_models

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        body = {
            "data": [
                {"id": "zeta-model", "owned_by": "tester"},
                {"id": "alpha-model", "context_window": 32_768},
                {"id": "MIDDLE-Model"},
                # noise that should be dropped:
                {"id": ""},
                {"name": "no-id"},
                "not-a-dict",
            ]
        }
        return httpx.Response(
            200,
            content=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    out = list_openai_compatible_models(
        provider="groq",
        api_key="fake-key",
        base_url=None,
        transport=transport,
    )

    assert captured["url"].endswith("/models")
    assert captured["auth"] == "Bearer fake-key"
    ids = [m["id"] for m in out]
    # Alphabetical, case-insensitive
    assert ids == ["alpha-model", "MIDDLE-Model", "zeta-model"]
    alpha = next(m for m in out if m["id"] == "alpha-model")
    assert alpha["contextWindow"] == 32_768
    zeta = next(m for m in out if m["id"] == "zeta-model")
    assert zeta["owned_by"] == "tester"


def test_list_openai_compatible_models_rejects_non_callable_provider() -> None:
    from llm.providers import LlmProviderError, list_openai_compatible_models

    with pytest.raises(LlmProviderError) as exc:
        list_openai_compatible_models(
            provider="anthropic", api_key="x", base_url=None
        )
    assert exc.value.kind == "provider_not_callable"


def test_list_openai_compatible_models_maps_http_errors() -> None:
    import httpx

    from llm.providers import LlmProviderError, list_openai_compatible_models

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b"bad key")

    with pytest.raises(LlmProviderError) as exc:
        list_openai_compatible_models(
            provider="groq",
            api_key="bad",
            base_url=None,
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.kind == "credential_invalid"
    assert exc.value.http_status == 401
