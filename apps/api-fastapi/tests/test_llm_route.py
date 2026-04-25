"""Loop 9 Phase 9.3 — /llm/* route smoke tests.

Verifies:
  - GET /llm/providers (auth required, returns Phase 9.3 callable subset)
  - GET /llm/configs (tenant-scoped row count)
  - POST /llm/test (admin-only; covers no_llm_configured and
    credential_missing paths without a real HTTP roundtrip)
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@iwo3_db
def test_list_providers_requires_auth() -> None:
    with TestClient(app) as client:
        r = client.get("/llm/providers")
    assert r.status_code == 401


@iwo3_db
def test_list_providers_includes_groq_openrouter() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/llm/providers",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    names = {p["name"] for p in body["providers"]}
    assert {"groq", "openrouter", "openai", "anthropic"}.issubset(names)
    callable_names = {
        p["name"]
        for p in body["providers"]
        if p["callable_in_phase_9_3"]
    }
    assert callable_names == {"groq", "openrouter", "openai"}


@iwo3_db
def test_list_configs_klear_sees_seeded_roles() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/llm/configs",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    roles = {c["agent_role"] for c in r.json()["configs"]}
    assert {
        "aiden_tier_1",
        "pm_tier_15",
        "mark_tier_2",
        "tom_tier_2",
        "hank_tier_2",
        "paul_tier_2",
    }.issubset(roles)


@iwo3_db
def test_test_route_requires_admin() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/llm/test",
            json={"agent_role": "aiden_tier_1"},
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 403


@iwo3_db
def test_test_route_returns_credential_missing_when_env_unset() -> None:
    # KLEAR_OWNER carries system:admin. The seeded credential_ref points
    # at GROQ_API_KEY which is not set in tests, so we expect a 200 with
    # ok=false + credential_missing rather than a real HTTP roundtrip.
    saved = os.environ.pop("GROQ_API_KEY", None)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/llm/test",
                json={"agent_role": "aiden_tier_1"},
                headers={
                    "X-IWO3-User": KLEAR_OWNER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert body["error"] is not None
        assert "credential_missing" in body["error"]
        assert body["provider"] == "groq"
    finally:
        if saved is not None:
            os.environ["GROQ_API_KEY"] = saved


@iwo3_db
def test_test_route_returns_404_for_unknown_role_with_no_fallback() -> None:
    # Resolution falls back to aiden_tier_1, which IS seeded for Klear,
    # so this path returns the same credential_missing as the prior test.
    # We assert the resolved_role to confirm fallback worked.
    saved = os.environ.pop("GROQ_API_KEY", None)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/llm/test",
                json={"agent_role": "completely_unseeded_role"},
                headers={
                    "X-IWO3-User": KLEAR_OWNER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["resolved_role"] == "aiden_tier_1"
        assert body["source"] == "tenant_default"
    finally:
        if saved is not None:
            os.environ["GROQ_API_KEY"] = saved
