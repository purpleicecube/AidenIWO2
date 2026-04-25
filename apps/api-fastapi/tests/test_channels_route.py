"""MegaLoop Alpha α.6 — /channel/* route smoke tests.

Verifies:
  - POST /channel/auth_codes (operator-issued binding code; RBAC + audit)
  - GET  /channel/identities (tenant-scoped list; channel_kind filter)
  - POST /channel/identities/{id}/revoke (admin-only; emits audit)
  - 401 without X-IWO3-* headers
  - 403 when role lacks the permission
  - 400 for invalid channel_kind
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
KLEAR_REVIEWER = "00000000-0000-4000-8000-000001000004"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str) -> dict:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


# ── auth_codes ────────────────────────────────────────────────────────


def test_issue_auth_code_requires_headers() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/channel/auth_codes",
            json={"channel_kind": "telegram"},
        )
    assert r.status_code == 401


@iwo3_db
def test_issue_auth_code_403_for_viewer() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/channel/auth_codes",
            json={"channel_kind": "telegram"},
            headers=_hdr(KLEAR_VIEWER),
        )
    assert r.status_code == 403, r.text


@iwo3_db
def test_issue_auth_code_400_for_unknown_channel_kind() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/channel/auth_codes",
            json={"channel_kind": "carrier_pigeon"},
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "invalid_channel_kind"


@iwo3_db
def test_issue_auth_code_operator_succeeds_for_telegram() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/channel/auth_codes",
            json={"channel_kind": "telegram", "ttl_minutes": 30},
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["code"]) == 12  # AUTH_CODE_LENGTH
    assert body["channel_kind"] == "telegram"
    assert "/start" in body["instructions"]
    assert body["expires_at"]


# ── identities ────────────────────────────────────────────────────────


@iwo3_db
def test_list_identities_403_for_unmapped_role() -> None:
    # Viewers are NOT in the channel:identity:read mapping.
    with TestClient(app) as client:
        r = client.get(
            "/channel/identities",
            headers=_hdr(KLEAR_VIEWER),
        )
    assert r.status_code == 403, r.text


@iwo3_db
def test_list_identities_operator_returns_list() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/channel/identities",
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "identities" in body
    assert isinstance(body["identities"], list)


@iwo3_db
def test_list_identities_filters_invalid_kind_400() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/channel/identities",
            params={"channel_kind": "smoke_signals"},
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 400, r.text


@iwo3_db
def test_revoke_identity_403_for_operator() -> None:
    # Operators can read but cannot revoke.
    with TestClient(app) as client:
        r = client.post(
            "/channel/identities/00000000-0000-4000-8000-0000000ff999/revoke",
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 403, r.text


@iwo3_db
def test_revoke_identity_404_for_unknown_id() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/channel/identities/00000000-0000-4000-8000-0000000ff999/revoke",
            headers=_hdr(KLEAR_OWNER),
        )
    assert r.status_code == 404, r.text


@iwo3_db
def test_revoke_identity_400_for_malformed_id() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/channel/identities/not-a-uuid/revoke",
            headers=_hdr(KLEAR_OWNER),
        )
    assert r.status_code == 400, r.text
