"""System Health parity — /system/checks aggregator.

Asserts the route returns the 5-row IWO2-parity check vocabulary
in the correct shape so the System Health UI can render the
Checks list without runtime-shape surprises.

Skips when IWO3_DATABASE_URL is unset (the endpoint depends on a
tenant-scoped Postgres connection).
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@iwo3_db
def test_system_checks_returns_five_iwo2_parity_rows() -> None:
    with TestClient(app) as client:
        resp = client.get(
            "/system/checks",
            headers={
                "X-IWO3-User": KLEAR_OWNER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "checks" in body
    assert "all_passed" in body
    assert "generated_at" in body

    names = [c["name"] for c in body["checks"]]
    assert names == ["api", "database", "llm", "gamma", "session_auth"], names

    # Each row has the required shape.
    for c in body["checks"]:
        assert isinstance(c["name"], str) and c["name"]
        assert isinstance(c["label"], str) and c["label"]
        assert isinstance(c["passed"], bool)
        # detail is Optional[str] — when present it's a short reason
        assert c.get("detail") is None or isinstance(c["detail"], str)


@iwo3_db
def test_system_checks_api_check_always_passes() -> None:
    """The `api` check returns True purely because the request
    reached the route. If it ever returns False, something is very
    wrong with the framing."""
    with TestClient(app) as client:
        resp = client.get(
            "/system/checks",
            headers={
                "X-IWO3-User": KLEAR_OWNER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    body = resp.json()
    api_check = next(c for c in body["checks"] if c["name"] == "api")
    assert api_check["passed"] is True


@iwo3_db
def test_system_checks_session_auth_reflects_signing_key_presence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session/Auth must be False when IWO3_JWT_SIGNING_KEY is unset
    or shorter than 32 bytes — mirrors the runtime contract enforced
    by auth.jwt_tokens._resolve_signing_key."""
    monkeypatch.delenv("IWO3_JWT_SIGNING_KEY", raising=False)
    with TestClient(app) as client:
        resp = client.get(
            "/system/checks",
            headers={
                "X-IWO3-User": KLEAR_OWNER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    body = resp.json()
    sa = next(c for c in body["checks"] if c["name"] == "session_auth")
    assert sa["passed"] is False
    assert "not set" in (sa.get("detail") or "")
