"""MegaLoop Beta-1 ε.3 — /auth/* routes + JWT round-trip tests."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_OWNER_EMAIL = "owner@klear.test"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@pytest.fixture(autouse=True)
def _signing_key_env(monkeypatch):
    """Provide a stable signing key for the JWT tests."""
    monkeypatch.setenv(
        "IWO3_JWT_SIGNING_KEY",
        "test-signing-key-32-bytes-minimum-for-hmac-sha256-shhhh",
    )


# ── pure JWT primitives ───────────────────────────────────────────────


def test_jwt_round_trip() -> None:
    from auth.jwt_tokens import decode, encode

    tok = encode(user_id=KLEAR_OWNER, client_id=KLEAR_CLIENT)
    claims = decode(tok, expected_typ="access")
    assert claims["sub"] == KLEAR_OWNER
    assert claims["cid"] == KLEAR_CLIENT
    assert claims["typ"] == "access"


def test_jwt_rejects_tampered_signature() -> None:
    from auth.jwt_tokens import TokenError, decode, encode

    tok = encode(user_id=KLEAR_OWNER, client_id=KLEAR_CLIENT)
    parts = tok.split(".")
    parts[2] = "AAAA" + parts[2][4:]
    bad = ".".join(parts)
    with pytest.raises(TokenError) as exc:
        decode(bad)
    assert exc.value.kind == "bad_signature"


def test_jwt_rejects_expired() -> None:
    from auth.jwt_tokens import TokenError, decode, encode

    tok = encode(
        user_id=KLEAR_OWNER, client_id=KLEAR_CLIENT, ttl_seconds=1, now=1
    )
    with pytest.raises(TokenError) as exc:
        decode(tok, now=10_000)
    assert exc.value.kind == "expired"


def test_jwt_rejects_wrong_typ() -> None:
    from auth.jwt_tokens import TokenError, decode, encode

    tok = encode(user_id=KLEAR_OWNER, client_id=KLEAR_CLIENT, typ="refresh")
    with pytest.raises(TokenError) as exc:
        decode(tok, expected_typ="access")
    assert exc.value.kind == "typ_mismatch"


# ── password hashing ──────────────────────────────────────────────────


def test_password_hash_round_trip() -> None:
    from auth.passwords import hash_password, verify_password

    h = hash_password("hunter2", iterations=100_000)
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False
    assert h.startswith("pbkdf2_sha256$100000$")


def test_password_verify_constant_time_friendly() -> None:
    from auth.passwords import verify_password

    # Malformed strings return False without raising.
    assert verify_password("any", "") is False
    assert verify_password("any", "garbage") is False
    assert verify_password("", "anything") is False


# ── /auth/login route ────────────────────────────────────────────────


@iwo3_db
def test_login_401_for_unknown_email() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/auth/login",
            json={
                "email": f"nobody-{uuid.uuid4().hex[:6]}@klear.test",
                "password": "x",
                "client_id": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 401, r.text


@iwo3_db
def test_login_401_for_user_without_password() -> None:
    """Seeded users have NULL password_hash — login must reject without
    accidentally treating NULL as a successful match."""
    with TestClient(app) as client:
        r = client.post(
            "/auth/login",
            json={
                "email": KLEAR_OWNER_EMAIL,
                "password": "anything",
                "client_id": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 401, r.text


def test_login_422_for_missing_fields() -> None:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={})
    assert r.status_code == 422, r.text


# ── auth-mode dep behaviour ──────────────────────────────────────────


@iwo3_db
def test_jwt_mode_accepts_signed_token(monkeypatch) -> None:
    """Auth dep accepts a JWT when Authorization: Bearer is set,
    even in dev_bearer mode (the bearer header takes precedence)."""
    from auth.jwt_tokens import encode

    tok = encode(user_id=KLEAR_OWNER, client_id=KLEAR_CLIENT)
    with TestClient(app) as client:
        r = client.get(
            "/work_orders",
            headers={"Authorization": f"Bearer {tok}"},
        )
    assert r.status_code == 200, r.text


@iwo3_db
def test_jwt_mode_rejects_bad_token() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/work_orders",
            headers={"Authorization": "Bearer not.a.real.jwt"},
        )
    assert r.status_code == 401, r.text


@iwo3_db
def test_jwt_mode_strict_when_env_set(monkeypatch) -> None:
    """When IWO3_AUTH_MODE=jwt, dev-bearer headers alone do not work."""
    monkeypatch.setenv("IWO3_AUTH_MODE", "jwt")
    with TestClient(app) as client:
        r = client.get(
            "/work_orders",
            headers={
                "X-IWO3-User": KLEAR_OWNER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 401, r.text


# Hosted Sandbox Bring-Up (2026-05-19) — sandbox-bounded
# service-to-service auth seam. The Node sandbox uses
# X-IWO3-Service-Token to pass dev-auth headers to FastAPI even in
# hosted JWT mode without minting a JWT per internal hop.

@iwo3_db
def test_service_token_accepts_dev_headers_in_jwt_mode(monkeypatch) -> None:
    """With IWO3_SERVICE_TOKEN set on FastAPI + IWO3_AUTH_MODE=jwt,
    a request carrying X-IWO3-Service-Token matching the env var +
    valid dev-auth headers succeeds."""
    monkeypatch.setenv("IWO3_AUTH_MODE", "jwt")
    monkeypatch.setenv("IWO3_SERVICE_TOKEN", "test-svc-secret")
    with TestClient(app) as client:
        r = client.get(
            "/work_orders",
            headers={
                "X-IWO3-User": KLEAR_OWNER,
                "X-IWO3-Client": KLEAR_CLIENT,
                "X-IWO3-Service-Token": "test-svc-secret",
            },
        )
    assert r.status_code == 200, r.text


@iwo3_db
def test_service_token_wrong_value_rejected_in_jwt_mode(monkeypatch) -> None:
    """Wrong service token must NOT silently fall through to JWT or
    dev_bearer paths — explicit 401 invalid_service_token."""
    monkeypatch.setenv("IWO3_AUTH_MODE", "jwt")
    monkeypatch.setenv("IWO3_SERVICE_TOKEN", "test-svc-secret")
    with TestClient(app) as client:
        r = client.get(
            "/work_orders",
            headers={
                "X-IWO3-User": KLEAR_OWNER,
                "X-IWO3-Client": KLEAR_CLIENT,
                "X-IWO3-Service-Token": "WRONG-SECRET",
            },
        )
    assert r.status_code == 401, r.text
    detail = r.json().get("detail") or {}
    assert isinstance(detail, dict)
    assert detail.get("error") == "invalid_service_token"


@iwo3_db
def test_service_token_unset_env_var_does_not_match_any_header(monkeypatch) -> None:
    """When IWO3_SERVICE_TOKEN is unset on FastAPI, the service-token
    header is IGNORED — request falls through to normal auth mode.
    Critical: an attacker cannot bypass auth by sending the header
    when no secret is configured."""
    monkeypatch.setenv("IWO3_AUTH_MODE", "jwt")
    monkeypatch.delenv("IWO3_SERVICE_TOKEN", raising=False)
    with TestClient(app) as client:
        r = client.get(
            "/work_orders",
            headers={
                "X-IWO3-User": KLEAR_OWNER,
                "X-IWO3-Client": KLEAR_CLIENT,
                "X-IWO3-Service-Token": "anything",
            },
        )
    # Falls through to JWT path which then 401s for missing Bearer.
    assert r.status_code == 401, r.text


@iwo3_db
def test_service_token_requires_dev_headers(monkeypatch) -> None:
    """Service token alone is not enough — caller must still pass
    X-IWO3-User + X-IWO3-Client. The token authorizes the bearer to
    SPEAK FOR a user, not to skip identity assertion entirely."""
    monkeypatch.setenv("IWO3_AUTH_MODE", "jwt")
    monkeypatch.setenv("IWO3_SERVICE_TOKEN", "test-svc-secret")
    with TestClient(app) as client:
        r = client.get(
            "/work_orders",
            headers={"X-IWO3-Service-Token": "test-svc-secret"},
        )
    assert r.status_code == 401, r.text
    detail = r.json().get("detail") or {}
    assert isinstance(detail, dict)
    assert detail.get("error") == "service_token_missing_identity"


@iwo3_db
def test_dev_bearer_mode_still_works_with_service_token_set(monkeypatch) -> None:
    """Regression: setting IWO3_SERVICE_TOKEN must not break local
    dev_bearer-mode operation. Dev headers without a service-token
    header still work in dev_bearer mode."""
    monkeypatch.setenv("IWO3_AUTH_MODE", "dev_bearer")
    monkeypatch.setenv("IWO3_SERVICE_TOKEN", "test-svc-secret")
    with TestClient(app) as client:
        r = client.get(
            "/work_orders",
            headers={
                "X-IWO3-User": KLEAR_OWNER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
